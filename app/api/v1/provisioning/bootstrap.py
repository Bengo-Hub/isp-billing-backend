"""
Bootstrap endpoints for MikroTik device provisioning.
Handles initial device connection and script generation.
"""
import logging
import secrets
import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import APIRouter, Depends, Query, HTTPException, Request, Path
from fastapi.responses import PlainTextResponse
from app.models.user import User
from app.models.provisioning import ProvisioningSession
from app.api.deps import require_technician_or_admin, get_db
from app.core.security import create_access_token
from app.core.secrets import get_secrets_manager
from app.services.router_provisioning import can_use_direct_api
from app.services.ping_monitor import ping_monitor
from app.core.config import settings

logger = logging.getLogger(__name__)

# Get default router IP and subnet from config (with fallbacks)
DEFAULT_ROUTER_IP = settings.mikrotik_default_ip
DEFAULT_SUBNET = settings.mikrotik_default_subnet
router = APIRouter()


async def ping_device(ip_address: str, timeout_ms: int = 1000) -> dict:
    """Check if device responds to ICMP ping or TCP port check.

    Uses ICMP ping first, falls back to TCP port check (API port 8728)
    if ICMP fails (common on Windows without admin privileges).

    Args:
        ip_address: IP address to ping
        timeout_ms: Ping timeout in milliseconds

    Returns:
        dict with 'reachable' (bool) and 'latency_ms' (float or None)
    """
    import platform
    import re
    import socket
    import time

    # Try ICMP ping first
    try:
        if platform.system().lower() == 'windows':
            cmd = ['ping', '-n', '1', '-w', str(timeout_ms), ip_address]
        else:
            cmd = ['ping', '-c', '1', '-W', str(max(1, timeout_ms // 1000)), ip_address]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
        output = stdout.decode('utf-8', errors='ignore')

        if process.returncode == 0:
            # Try to extract latency from output
            latency_match = re.search(r'time[=<]([0-9.]+)\s*ms', output)
            latency = float(latency_match.group(1)) if latency_match else None
            logger.debug(f"ICMP ping success for {ip_address}: latency={latency}ms")
            return {"reachable": True, "latency_ms": latency, "method": "icmp"}
        else:
            # Log why ICMP failed
            stderr_output = stderr.decode('utf-8', errors='ignore')
            logger.debug(f"ICMP ping failed for {ip_address}: returncode={process.returncode}, output={output[:100]}")

    except asyncio.TimeoutError:
        logger.debug(f"ICMP ping timeout for {ip_address}")
    except Exception as e:
        logger.debug(f"ICMP ping exception for {ip_address}: {type(e).__name__}: {e}")

    # Fallback: TCP port check (MikroTik API port or Winbox port)
    # This works without admin privileges on Windows
    tcp_ports = [
        settings.mikrotik_default_port,  # API port (usually 8728)
        8291,  # Winbox port
        80,    # HTTP (hotspot)
    ]

    for port in tcp_ports:
        try:
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_ms / 1000.0)
            result = sock.connect_ex((ip_address, port))
            latency = (time.time() - start_time) * 1000  # Convert to ms
            sock.close()

            if result == 0:
                logger.info(f"TCP port check success for {ip_address}:{port} (latency={latency:.1f}ms)")
                return {"reachable": True, "latency_ms": round(latency, 1), "method": f"tcp:{port}"}
        except socket.timeout:
            logger.debug(f"TCP port {port} timeout for {ip_address}")
        except Exception as e:
            logger.debug(f"TCP port {port} check failed for {ip_address}: {e}")

    logger.warning(f"Device {ip_address} not reachable via ICMP or TCP ports {tcp_ports}")
    return {"reachable": False, "latency_ms": None, "method": None}


def generate_encrypted_payload(data: dict) -> str:
    """Generate encrypted payload for secure URL parameter.
    
    Args:
        data: Dictionary to encrypt (identity, api_port, user_id, etc.)
        
    Returns:
        URL-safe encrypted string
    """
    secrets_manager = get_secrets_manager()
    json_data = json.dumps(data)
    encrypted = secrets_manager.encrypt(json_data)
    # Make URL-safe by replacing + and / characters
    return encrypted.replace('+', '-').replace('/', '_').replace('=', '')


def decrypt_payload(encrypted: str) -> dict:
    """Decrypt encrypted payload from URL.
    
    Args:
        encrypted: URL-safe encrypted string
        
    Returns:
        Decrypted dictionary
    """
    # Restore base64 padding and characters
    restored = encrypted.replace('-', '+').replace('_', '/')
    # Add padding if needed
    padding = 4 - (len(restored) % 4)
    if padding != 4:
        restored += '=' * padding
    
    secrets_manager = get_secrets_manager()
    decrypted = secrets_manager.decrypt(restored)
    return json.loads(decrypted)


@router.get("/command")
async def get_bootstrap_command(
    request: Request,
    identity: str = Query("MikroTik"),
    api_port: int = Query(8728),
    interface: str = Query("ether1"),
    ip_address: Optional[str] = Query(None, description="Device IP for pre-check"),
    use_encrypted_url: bool = Query(False, description="Use encrypted payload URL"),
    session_id: Optional[str] = Query(None, description="Optional provisioning session_id to include in bootstrap callback"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Generate a one-liner RouterOS command for initial device provisioning with proper access token.

    This command downloads and executes the bootstrap script from the current domain.
    The script enables API access and sets basic device configuration.
    
    Optional features:
    - Device ping pre-check (if ip_address provided)
    - Encrypted payload URL (if use_encrypted_url=true)
    - Optional `session_id` to let the router call back the backend once bootstrap completes
    """
    try:
        # Optional: Ping pre-check if IP address provided
        ping_result = None
        if ip_address:
            ping_result = await ping_device(ip_address)
            if not ping_result["reachable"]:
                logger.warning(f"Device {ip_address} not responding to ping")
                # Return warning but don't block - device might block ICMP
        
        # Determine canonical backend base URL.
        # Prefer `settings.backend_url` (configured via env/Helm). Fall back to
        # legacy BACKEND_URL env var, then to the request URL.
        base = settings.backend_url or os.getenv('BACKEND_URL')

        if base:
            # Respect force_https setting or reverse-proxy header to avoid
            # generating an http:// URL that will 308-redirect (RouterOS fetch
            # doesn't follow redirects).
            if settings.force_https or request.headers.get('x-forwarded-proto', '').lower() == 'https':
                base = base.replace('http://', 'https://')
            logger.info(f"Using backend base URL: {base}")
        else:
            # Fallback to request URL (development mode)
            base = f"{request.url.scheme}://{request.url.netloc}"
            logger.warning(f"BACKEND_URL not set, using request URL: {base}")

        # Generate provisioning token with limited permissions (1 hour expiry)
        token_data = {
            "sub": str(current_user.id),
            "username": current_user.username,
            "role": current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
            "type": "provisioning",
            "permissions": ["provisioning.execute", "router.configure"],
            "nonce": secrets.token_hex(8),  # Unique per request
        }
        provisioning_token = create_access_token(token_data, expires_delta=timedelta(hours=1))

        # Choose between encrypted payload URL or traditional query params
        if use_encrypted_url:
            # CodeVertex-style encrypted payload
            payload = {
                "identity": identity,
                "api_port": api_port,
                "interface": interface,
                "user_id": current_user.id,
                "tenant_id": current_user.organization_id if hasattr(current_user, 'organization_id') else None,
                "token": provisioning_token,
                "timestamp": datetime.utcnow().isoformat()
            }
            encrypted = generate_encrypted_payload(payload)
            script_url = f"{base}/api/v1/provisioning/bootstrap/script/{encrypted}"
        else:
            # Traditional query parameter approach
            script_url = f"{base}/api/v1/provisioning/bootstrap/script?token={provisioning_token}&identity={identity}&api_port={api_port}&interface={interface}"

        # Detect URL scheme and set mode to match (RouterOS 7.16+ requires consistency)
        fetch_mode = "https" if script_url.startswith("https://") else "http"

        # Use proper MikroTik syntax: :delay (with colon) and /import (with forward slash)
        command = f"/tool fetch mode={fetch_mode} url=\"{script_url}\" dst-path=codevertex.rsc;:delay 2s;/import codevertex.rsc;"

        # If the provisioning UI provided a session_id, append a callback from
        # the router back to the backend so the UI gets an immediate signal that
        # bootstrap executed (router-initiated callback works behind NAT).
        if session_id:
            notify_url = f"{base}/api/v1/provisioning/notify?session_id={session_id}&token={provisioning_token}&status=bootstrap_completed"
            notify_mode = "https" if notify_url.startswith("https://") else "http"
            # Append a lightweight fetch POST (RouterOS supports this syntax)
            command += f" :delay 1s; /tool fetch mode={notify_mode} url=\"{notify_url}\" http-method=post;"

        notes = [
            "Waiting for mikrotik to come online...",
            "Please paste and execute the command in your Mikrotik terminal. The system will automatically detect when the command is executed.",
            "If the device mode is not allowed, debug the power cord for 10 seconds, then restart power before retrying the provisioning command.",
            "Attempt 10 of 300"
        ]

        response_data = {
            "command": command,
            "script_url": script_url,
            "token": provisioning_token,
            "expires_in": 3600,  # 1 hour
            "notes": notes,
            "encrypted_url": use_encrypted_url
        }

        # Expose the notify URL in the response when session_id provided so the
        # frontend can display/record it for debugging.
        if session_id:
            response_data["notify_url"] = notify_url

        # Add ping result if available
        if ping_result:
            response_data["ping_check"] = ping_result
            if not ping_result["reachable"]:
                response_data["warnings"] = ["Device not responding to ping. Check network connection."]

        return response_data

    except Exception as e:
        logger.error(f"Failed to generate bootstrap command: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate bootstrap command")


@router.get("/script", response_class=PlainTextResponse)
@router.get("/script/{encrypted_payload}", response_class=PlainTextResponse)
async def get_bootstrap_script(
    request: Request,
    encrypted_payload: Optional[str] = None,
    token: Optional[str] = Query(None),
    identity: Optional[str] = Query(None),
    api_port: Optional[int] = Query(None),
    interface: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return a minimal RouterOS script for first-touch provisioning with token verification.

    Supports two modes:
    1. Traditional: Query parameters (token, identity, api_port, interface)
    2. Encrypted: Single encrypted payload in URL path

    The script now performs a best-effort HTTPS POST back to the backend
    notify endpoint after completion so the server can mark the device as
    bootstrapped (useful for NAT'd devices and UI auto-advancement).
    """
    try:
        # Determine which mode to use
        if encrypted_payload:
            # Decrypt the payload
            try:
                payload = decrypt_payload(encrypted_payload)
                token = payload.get("token")
                identity = payload.get("identity", "MikroTik")
                api_port = payload.get("api_port", 8728)
                interface = payload.get("interface", "ether1")
                logger.info(f"Using encrypted payload for user {payload.get('user_id')}")
            except Exception as e:
                logger.error(f"Failed to decrypt payload: {e}")
                raise HTTPException(status_code=400, detail="Invalid encrypted payload")
        else:
            # Traditional mode - validate required parameters
            if not token:
                raise HTTPException(status_code=400, detail="Token is required")
            identity = identity or "MikroTik"
            api_port = api_port or 8728
            interface = interface or "ether1"

        # Verify provisioning token using the security module
        from app.core.security import verify_token

        token_data = verify_token(token, token_type="access")
        if not token_data or not hasattr(token_data, 'user_id'):
            raise HTTPException(status_code=401, detail="Invalid provisioning token")

        # Log the provisioning attempt
        logger.info(f"Provisioning script requested by user {token_data.user_id} for identity: {identity}")

        # Get user_id from token_data (it's a Pydantic model, not a dict)
        user_id = token_data.user_id
        permissions = getattr(token_data, 'permissions', []) or []

        # Fetch user and organization to get org_slug for template URLs
        from app.models.organization import Organization
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        org_slug = None
        if user.organization_id:
            org_result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
            organization = org_result.scalar_one_or_none()
            if organization:
                org_slug = organization.slug

        # Get API user credentials from settings
        api_username = settings.mikrotik_api_username
        api_password = settings.mikrotik_api_password

        lines = [
            "# Codevertex Bootstrap Script - Initial Device Setup",
            "# Generated by Codevertex ISP Billing System",
            f"# User ID: {user_id}",
            f"# Permissions: {', '.join(permissions) if permissions else 'N/A'}",
            "# All operations are logged to /log and displayed in terminal",
            "",
            ":put \"\"",
            ":put \"=========================================\"",
            ":put \"Codevertex Bootstrap - Starting Setup\"",
            ":put \"=========================================\"",
            "",
            "# [STEP 1/8] Set system identity",
            f":do {{ /system/identity/set name={identity}; :put \"[OK] System identity set to {identity}\"; :log info \"[BOOTSTRAP] System identity set to {identity}\" }} on-error={{ :put \"[FAIL] Failed to set system identity\"; :log error \"[BOOTSTRAP] Failed to set system identity\" }}",
            "",
            "# [STEP 2/8] Enable API service on specified port",
            f":do {{ /ip/service/set api disabled=no port={api_port}; :put \"[OK] API service enabled on port {api_port}\"; :log info \"[BOOTSTRAP] API service enabled on port {api_port}\" }} on-error={{ :put \"[FAIL] Failed to enable API service\"; :log error \"[BOOTSTRAP] Failed to enable API service\" }}",
            "",
            "# [STEP 3/8] Enable FTP service (required for template upload)",
            ":do { /ip/service/set [find name=\"ftp\"] disabled=no port=21; :put \"[OK] FTP service enabled on port 21\"; :log info \"[BOOTSTRAP] FTP service enabled on port 21\" } on-error={ :put \"[FAIL] Failed to enable FTP service\"; :log error \"[BOOTSTRAP] Failed to enable FTP service\" }",
            "",
            "# [STEP 4/8] Enable Winbox service",
            ":do { /ip/service/set winbox disabled=no; :put \"[OK] Winbox service enabled\"; :log info \"[BOOTSTRAP] Winbox service enabled\" } on-error={ :put \"[FAIL] Failed to enable Winbox\"; :log error \"[BOOTSTRAP] Failed to enable Winbox\" }",
            "",
            "# [STEP 5/8] Configure SSH on custom port for security",
            ":do { /ip/service/set ssh port=2222; :put \"[OK] SSH configured on port 2222\"; :log info \"[BOOTSTRAP] SSH configured on port 2222\" } on-error={ :put \"[FAIL] Failed to configure SSH\"; :log error \"[BOOTSTRAP] Failed to configure SSH\" }",
            "",
            "# [STEP 6/8] Create API user group with full permissions",
            ":put \"Creating codevertex-api user group...\"",
            ":log info \"[BOOTSTRAP] Creating codevertex-api user group...\"",
            ":if ([:len [/user/group/find name=\"codevertex-api\"]] = 0) do={",
            "  :do {",
            "    /user/group/add name=\"codevertex-api\" policy=local,telnet,ssh,ftp,reboot,read,write,policy,test,winbox,password,web,sniff,sensitive,api,romon,rest-api;",
            "    :put \"[OK] User group 'codevertex-api' created successfully\";",
            "    :log info \"[BOOTSTRAP] User group 'codevertex-api' created successfully\"",
            "  } on-error={ :put \"[FAIL] Failed to create user group\"; :log error \"[BOOTSTRAP] Failed to create user group\" }",
            "} else={",
            "  :put \"[SKIP] User group 'codevertex-api' already exists\";",
            "  :log info \"[BOOTSTRAP] User group 'codevertex-api' already exists\"",
            "}",
            "",
            "# [STEP 7/8] Create dedicated API user for Codevertex ISP Billing",
            f":put \"Creating API user '{api_username}'...\"",
            ":log info \"[BOOTSTRAP] Creating API user...\"",
            f":if ([:len [/user/find name=\"{api_username}\"]] > 0) do={{",
            f"  :do {{ /user/remove [find name=\"{api_username}\"]; :put \"[OK] Removed existing user {api_username}\"; :log info \"[BOOTSTRAP] Removed existing user {api_username}\" }} on-error={{ :put \"[WARN] Could not remove existing user\"; :log warning \"[BOOTSTRAP] Could not remove existing user\" }}",
            "}",
            ":do {",
            f"  /user/add name=\"{api_username}\" password=\"{api_password}\" group=\"codevertex-api\" comment=\"Codevertex ISP Billing API User - DO NOT DELETE\";",
            f"  :put \"[OK] API user '{api_username}' created successfully\";",
            f"  :log info \"[BOOTSTRAP] API user '{api_username}' created successfully\"",
            "} on-error={ :put \"[FAIL] Failed to create API user\"; :log error \"[BOOTSTRAP] Failed to create API user\" }",
            "",
            "# [STEP 8/9] Verify interface exists",
            f":do {{ /interface/print where name={interface}; :put \"[OK] Interface {interface} verified\"; :log info \"[BOOTSTRAP] Interface {interface} verified\" }} on-error={{ :put \"[WARN] Interface {interface} not found\"; :log warning \"[BOOTSTRAP] Interface {interface} not found\" }}",
            "",
            "# [STEP 9/11] Optimize system logging (reduce log growth)",
            ":put \"Configuring system logging...\"",
            ":do {",
            "  /system logging action set memory memory-lines=500;",
            "  :put \"[OK] Set log memory limit to 500 lines\";",
            "  :log info \"[BOOTSTRAP] Set log memory limit to 500 lines\"",
            "} on-error={ :put \"[WARN] Failed to set log memory limit\"; :log warning \"[BOOTSTRAP] Failed to set log memory limit\" }",
            "",
            ":do {",
            "  /system logging set [find] disabled=yes;",
            "  :put \"[OK] Disabled all existing log rules\";",
            "  :log info \"[BOOTSTRAP] Disabled all existing log rules\"",
            "} on-error={ :put \"[WARN] Failed to disable existing log rules\" }",
            "",
            ":do {",
            "  /system logging add topics=error,warning action=memory;",
            "  :put \"[OK] Added error/warning logging to memory\";",
            "  :log info \"[BOOTSTRAP] Added error/warning logging to memory\"",
            "} on-error={ :put \"[WARN] Failed to add error/warning logging\" }",
            "",
            ":do {",
            "  /system logging add topics=script,fetch action=memory;",
            "  :put \"[OK] Added script/fetch logging to memory\";",
            "  :log info \"[BOOTSTRAP] Added script/fetch logging to memory\"",
            "} on-error={ :put \"[WARN] Failed to add script/fetch logging\" }",
            "",
            "# [STEP 10/11] Download hotspot templates from backend",
        ]

        # Add template download commands only if org_slug is available
        if org_slug and settings.backend_url:
            lines.extend([
                ":put \"Downloading hotspot templates...\"",
                ":log info \"[BOOTSTRAP] Downloading hotspot templates...\"",
                "",
                "# Download login.html template",
                ":do {",
                f"  /tool/fetch url=\"{settings.backend_url}/api/v1/provisioning/templates/login.html?org_slug={org_slug}\" dst-path=hotspot/login.html;",
                "  :put \"[OK] Downloaded login.html template\";",
                "  :log info \"[BOOTSTRAP] Downloaded login.html template\"",
                "} on-error={ :put \"[WARN] Failed to download login.html (will use FTP fallback)\"; :log warning \"[BOOTSTRAP] Failed to download login.html\" }",
                "",
                "# Download alogin.html template",
                ":do {",
                f"  /tool/fetch url=\"{settings.backend_url}/api/v1/provisioning/templates/alogin.html?org_slug={org_slug}\" dst-path=hotspot/alogin.html;",
                "  :put \"[OK] Downloaded alogin.html template\";",
                "  :log info \"[BOOTSTRAP] Downloaded alogin.html template\"",
                "} on-error={ :put \"[WARN] Failed to download alogin.html (will use FTP fallback)\"; :log warning \"[BOOTSTRAP] Failed to download alogin.html\" }",
                "",
            ])
        else:
            lines.extend([
                ":put \"[SKIP] Template download skipped (will use FTP fallback during provisioning)\"",
                ":log info \"[BOOTSTRAP] Template download skipped (will use FTP fallback)\"",
                "",
            ])

        # Add completion summary
        template_status = "downloaded" if org_slug and settings.backend_url else "will be uploaded via FTP"
        lines.extend([
            "# Bootstrap completion summary",
            ":put \"\"",
            ":put \"=========================================\"",
            f":put \"Bootstrap completed for {identity}\"",
            f":put \"API enabled on port {api_port}\"",
            ":put \"FTP enabled for template upload fallback\"",
            f":put \"API user '{api_username}' configured\"",
            ":put \"Logging optimized (500 line limit, errors/warnings only)\"",
            f":put \"Hotspot templates: {template_status}\"",
            ":put \"Ready for provisioning workflow\"",
            ":put \"=========================================\"",
            ":put \"\"",
            "",
            "# Log summary to system log",
            f":log info \"[BOOTSTRAP] ========================================\"",
            f":log info \"[BOOTSTRAP] Bootstrap completed for {identity}\"",
            f":log info \"[BOOTSTRAP] Token verified for user {user_id}\"",
            f":log info \"[BOOTSTRAP] API enabled on port {api_port}\"",
            f":log info \"[BOOTSTRAP] FTP enabled for template upload fallback\"",
            f":log info \"[BOOTSTRAP] API user '{api_username}' configured\"",
            f":log info \"[BOOTSTRAP] Logging optimized (500 line limit, errors/warnings only)\"",
            f":log info \"[BOOTSTRAP] Hotspot templates: {template_status}\"",
            f":log info \"[BOOTSTRAP] Ready for provisioning workflow\"",
            f":log info \"[BOOTSTRAP] ========================================\"",
        ])

        # Notify backend that bootstrap completed (router -> backend)
        # Use the provisioning token passed in the URL (required). The backend
        # will verify the token and associate the check-in with a provisioning
        # session or record the check-in for later consumption.
        try:
            notify_url = f"{settings.backend_url or (request.url.scheme + '://' + request.url.netloc)}/api/v1/provisioning/bootstrap/notify?token={token}&identity={identity}"
            lines.append(":put \"Notifying backend of bootstrap completion...\"")
            lines.append(f"/tool fetch mode=https url=\"{notify_url}\" http-method=post dst-path=notify.result; :put \"[OK] Notified backend (notify.result)\"; :log info \"[BOOTSTRAP] Notified backend of bootstrap completion\"")
        except Exception:
            # Best effort - don't fail script generation if notify_url cannot be built
            lines.append(":put \"[WARN] Could not append backend notify call to bootstrap script\"")

        return "\n".join(lines) + "\n"

    except Exception as e:
        logger.error(f"Failed to generate bootstrap script: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate bootstrap script")


@router.post('/notify')
async def provisioning_notify(
    request: Request,
    token: Optional[str] = Query(None),
    identity: Optional[str] = Query(None),
    ip_address: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Endpoint called by devices after bootstrap to notify backend.

    Query params:
    - token: provisioning access token (required)
    - identity: optional router identity (used for logging)
    - ip_address: optional router-reported IP (falls back to request.client.host)

    Behavior:
    - verify token
    - attempt to correlate to an existing provisioning session for the same router IP
    - if found, broadcast `provisioning_complete` via websocket and update ping_monitor
    - otherwise record a one-time pending check-in so a future session will see it
    """
    if not token:
        raise HTTPException(status_code=400, detail='token is required')

    from app.core.security import verify_token
    try:
        token_data = verify_token(token, token_type='access')
    except Exception as e:
        logger.warning(f'Provisioning notify token verification failed: {e}')
        raise HTTPException(status_code=401, detail='invalid token')

    # Resolve IP
    client_ip = ip_address or (request.client.host if request.client else None)

    # Broadcast to any active provisioning session associated with this router IP
    try:
        # Find router by IP
        from app.models.router import Router
        router_result = await db.execute(select(Router).where(Router.ip_address == client_ip))
        router = router_result.scalar_one_or_none()

        session_found = None
        if router:
            from app.models.provisioning import ProvisioningSession, ProvisioningStatus
            session_result = await db.execute(
                select(ProvisioningSession)
                .where(
                    ProvisioningSession.router_id == router.id,
                    ProvisioningSession.status.in_([ProvisioningStatus.PENDING, ProvisioningStatus.IN_PROGRESS])
                )
                .order_by(ProvisioningSession.created_at.desc())
                .limit(1)
            )
            session_found = session_result.scalar_one_or_none()

        # Inform ping monitor and live stream
        from app.api.v1.provisioning.stream import manager
        from app.services.ping_monitor import ping_monitor

        if session_found:
            sid = session_found.session_id
            # Mark ping_monitor result for this session so UI can advance
            ping_monitor.monitor_results[sid] = {
                'attempt': 0,
                'ping_verified': True,
                'api_verified': True,
                'ip_address': client_ip,
                'method': 'device-notify',
                'timestamp': datetime.utcnow().isoformat()
            }

            # Stop any active monitoring for this session (if running)
            try:
                if ping_monitor.is_monitoring(sid):
                    await ping_monitor.stop_monitoring(sid)
            except Exception:
                logger.debug('Failed to stop ping monitor after notify')

            # Broadcast websocket message to UI
            await manager.send_message(sid, {
                'type': 'provisioning_complete',
                'session_id': sid,
                'data': {
                    'message': 'Device reported bootstrap completion',
                    'ip_address': client_ip,
                    'identity': identity
                }
            })

            logger.info(f'Provisioning notify: associated with session {sid} (router {router.id})')
            return {'status': 'ok', 'session_id': sid}

        # No active session found: record a pending check-in for the IP so
        # future provisioning sessions will treat the device as already bootstrapped.
        ping_monitor.register_device_checkin(client_ip, {'identity': identity, 'token_sub': getattr(token_data, 'sub', None), 'timestamp': datetime.utcnow().isoformat()})

        logger.info(f'Provisioning notify: recorded pending check-in for IP {client_ip}')
        return {'status': 'ok', 'session_id': None, 'note': 'pending_checkin_recorded'}

    except Exception as e:
        logger.error(f'Error handling provisioning notify: {e}')
        raise HTTPException(status_code=500, detail='Failed to handle notify')


@router.post('/notify')
async def provisioning_notify(
    session_id: Optional[str] = Query(None, description="Provisioning session UUID"),
    token: Optional[str] = Query(None, description="Provisioning token (required)"),
    status: str = Query('bootstrap_completed'),
    db: AsyncSession = Depends(get_db),
):
    """Callback endpoint for routers to notify backend when bootstrap completes.

    - Verifies provisioning token
    - Marks provisioning session completed/successful when session_id provided
    - Broadcasts `provisioning_complete` over the provisioning websocket
    - Stops any active ping monitoring for the session

    This endpoint is intentionally lightweight and token-protected because it
    will be called directly from customer routers during first-touch.
    """
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    # Verify token and ensure it was minted for provisioning
    from app.core.security import verify_token
    try:
        token_data = verify_token(token, token_type='access')
    except Exception as e:
        logger.warning(f"Provisioning notify: token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    if not token_data or getattr(token_data, 'type', None) != 'provisioning':
        logger.warning("Provisioning notify: token is not a provisioning token")
        raise HTTPException(status_code=403, detail="Token not authorized for provisioning notifications")

    # Broadcast websocket message and update provisioning session if provided
    try:
        from app.api.v1.provisioning.stream import manager
        from app.models.provisioning import ProvisioningStatus

        if session_id:
            # Update ProvisioningSession if exists
            result = await db.execute(select(ProvisioningSession).where(ProvisioningSession.session_id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.status = ProvisioningStatus.COMPLETED
                session.success = True if status == 'bootstrap_completed' else False
                session.completed_at = datetime.utcnow()
                session.progress_percentage = 100.0
                await db.commit()
                logger.info(f"Provisioning notify: marked session {session_id} as completed (status={status})")

        # Update ping monitor internal state and stop monitoring if active
        try:
            ping_monitor.monitor_results[session_id] = {
                "ping_verified": True,
                "api_verified": True,
                "timestamp": datetime.utcnow().isoformat(),
                "status": status,
                "session_id": session_id,
            }
            # best-effort stop
            await ping_monitor.stop_monitoring(session_id)
        except Exception:
            # non-fatal
            logger.debug(f"Provisioning notify: ping_monitor update/stop failed for {session_id}")

        # Broadcast provisioning_complete for any connected UI clients
        if session_id:
            await manager.send_message(session_id, {
                "type": "provisioning_complete",
                "session_id": session_id,
                "data": {
                    "message": "Bootstrap completed on device",
                    "status": status,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            })

        return {"success": True, "session_id": session_id, "status": status}

    except Exception as e:
        logger.error(f"Provisioning notify failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process provisioning notify")


@router.get("/complete", response_class=PlainTextResponse)
async def get_complete_script(
    current_user: User = Depends(require_technician_or_admin()),
):
    """Return the complete RouterOS configuration script.

    This is the comprehensive script that configures all services
    after the initial bootstrap is complete.
    """
    try:
        # Parse default IP and subnet from config
        gateway_ip = DEFAULT_ROUTER_IP  # e.g., 192.168.88.1
        subnet = DEFAULT_SUBNET  # e.g., 192.168.88.0/24

        # Extract network base from subnet (e.g., 192.168.88 from 192.168.88.0/24)
        subnet_base = subnet.split('/')[0].rsplit('.', 1)[0]

        script_content = f"""
# Codevertex Complete Configuration Script
# This script configures all services after bootstrap
# Default Router IP: {gateway_ip}
# Default Subnet: {subnet}

# System logging
/system logging add topics=info action=memory
/system logging add topics=error action=memory

# Bridge configuration
/interface bridge add name=codevertex-bridge protocol-mode=none
/interface bridge port add bridge=codevertex-bridge interface=ether2
/interface bridge port add bridge=codevertex-bridge interface=ether3
/interface bridge port add bridge=codevertex-bridge interface=ether4
/interface bridge port add bridge=codevertex-bridge interface=ether5
/interface bridge port add bridge=codevertex-bridge interface=ether6
/interface bridge port add bridge=codevertex-bridge interface=ether7
/interface bridge port add bridge=codevertex-bridge interface=ether8

# IP configuration
/ip address add address={gateway_ip}/24 interface=codevertex-bridge

# DHCP Server
/ip dhcp-server add interface=codevertex-bridge address-pool=codevertex-pool disabled=no
/ip dhcp-server network add address={subnet} gateway={gateway_ip} dns-server=8.8.8.8,8.8.4.4
/ip pool add name=codevertex-pool ranges={subnet_base}.100-{subnet_base}.200

# DNS configuration
/ip dns set servers=8.8.8.8,8.8.4.4 allow-remote-requests=yes

# Hotspot configuration
/ip hotspot setup add name=codevertex-hotspot interface=codevertex-bridge address-pool=codevertex-pool profile=codevertex-profile
/ip hotspot profile add name=codevertex-profile use-radius=no
/ip hotspot ip-binding add address={gateway_ip} to-address={gateway_ip} type=bypassed

# PPPoE Server configuration
/interface pppoe-server server add interface=codevertex-bridge service-name=codevertex-pppoe authentication=pap,chap,mschap1,mschap2
/ppp profile add name=codevertex-pppoe local-address={gateway_ip} remote-address=codevertex-pppoe-pool

# Firewall rules
/ip firewall filter add chain=input action=accept connection-state=established,related
/ip firewall filter add chain=input action=accept src-address={subnet}
/ip firewall filter add chain=input action=drop

# NAT configuration
/ip firewall nat add chain=srcnat action=masquerade out-interface=ether1

# Anti-sharing rules (TTL modification)
/ip firewall mangle add chain=forward action=change-ttl new-ttl=64 ttl=65 protocol=tcp dst-port=80,443,53,21,22,23,25,110,143,993,995,8080,8443
/ip firewall mangle add chain=forward action=change-ttl new-ttl=64 ttl=65 protocol=udp dst-port=53,67,68,123,161,162,500,4500

# Queue tree for bandwidth management
/queue tree add name=codevertex-main parent=global max-limit=100M
/queue tree add name=codevertex-hotspot parent=codevertex-main max-limit=50M

# System configuration
/system clock set time-zone-name=UTC
/system ntp client set enabled=yes primary-ntp=pool.ntp.org

# Final system message
:log info message="Codevertex ISP Billing System - Router configured successfully"
"""
        
        return script_content
    
    except Exception as e:
        logger.error(f"Failed to generate complete script: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate complete script")


@router.get("/can-use-direct-api/{router_id}")
async def check_direct_api_access(
    router_id: int = Path(..., description="Router ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Check if router has stored credentials for direct API reprovisioning.
    
    Returns:
        {
            "can_use_direct_api": bool,
            "bootstrap_completed": bool,
            "provisioning_status": str
        }
    """
    try:
        has_access = await can_use_direct_api(db, router_id)
        
        # Get router details
        from sqlalchemy import select
        from app.models.router import Router
        result = await db.execute(select(Router).where(Router.id == router_id))
        router = result.scalar_one_or_none()
        
        if not router:
            raise HTTPException(status_code=404, detail="Router not found")
        
        return {
            "can_use_direct_api": has_access,
            "bootstrap_completed": router.bootstrap_completed or False,
            "provisioning_status": router.provisioning_status or 'pending',
            "last_provisioned_at": router.last_provisioned_at.isoformat() if router.last_provisioned_at else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check direct API access for router {router_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to check API access")


@router.post("/ping/start/{session_id}")
async def start_ping_monitoring(
    session_id: str,
    ip_address: str = Query(..., description="Device IP address to monitor"),
    api_port: int = Query(8728, description="MikroTik API port to verify", ge=1, le=65535),
    interval_seconds: float = Query(2.0, description="Check interval in seconds", ge=0.5, le=10.0),
    max_attempts: int = Query(300, description="Maximum check attempts", ge=1, le=1000),
    timeout_ms: int = Query(1000, description="Connection timeout in milliseconds", ge=100, le=5000),
    current_user: User = Depends(require_technician_or_admin()),
):
    """
    Start two-stage device monitoring for a provisioning session.

    Stage 1: ICMP Ping - Verify device is on the network
    Stage 2: API Port Check - Verify bootstrap command was executed

    Results will be broadcast via WebSocket to /ws/{session_id}

    Args:
        session_id: Provisioning session identifier
        ip_address: Target device IP address
        api_port: MikroTik API port to check (default 8728)
        interval_seconds: Time between check attempts (0.5-10 seconds)
        max_attempts: Maximum number of check attempts (1-1000)
        timeout_ms: Connection timeout in milliseconds (100-5000)
    """
    try:
        # Check if already monitoring
        if ping_monitor.is_monitoring(session_id):
            return {
                "message": "Device monitoring already active for this session",
                "session_id": session_id,
                "status": "already_running"
            }

        # Start two-stage monitoring in background
        await ping_monitor.start_monitoring(
            session_id=session_id,
            ip_address=ip_address,
            api_port=api_port,
            interval_seconds=interval_seconds,
            max_attempts=max_attempts,
            timeout_ms=timeout_ms
        )

        logger.info(
            f"Started two-stage monitoring for session {session_id} "
            f"targeting {ip_address}:{api_port} (user: {current_user.username})"
        )

        return {
            "message": "Device monitoring started successfully",
            "session_id": session_id,
            "ip_address": ip_address,
            "api_port": api_port,
            "stages": ["ICMP Ping (Network)", "API Port (Bootstrap)"],
            "interval_seconds": interval_seconds,
            "max_attempts": max_attempts,
            "status": "started"
        }

    except Exception as e:
        logger.error(f"Failed to start device monitoring: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start device monitoring: {str(e)}")


@router.post("/ping/stop/{session_id}")
async def stop_ping_monitoring(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
):
    """
    Stop ping monitoring for a provisioning session.

    This endpoint is idempotent - it returns success even if monitoring
    is not active (e.g., if it already completed after device came online).

    Args:
        session_id: Provisioning session identifier
    """
    try:
        if not ping_monitor.is_monitoring(session_id):
            # Return success even if not monitoring - idempotent behavior
            # This can happen if monitoring auto-completed after device came online
            logger.debug(
                f"Ping monitoring not active for session {session_id} "
                f"(already completed or never started)"
            )
            return {
                "message": "Ping monitoring not active (already completed)",
                "session_id": session_id,
                "status": "not_active"
            }

        await ping_monitor.stop_monitoring(session_id)

        logger.info(
            f"Stopped ping monitoring for session {session_id} "
            f"(user: {current_user.username})"
        )

        return {
            "message": "Ping monitoring stopped successfully",
            "session_id": session_id,
            "status": "stopped"
        }

    except Exception as e:
        logger.error(f"Failed to stop ping monitoring: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop ping monitoring: {str(e)}")


@router.get("/ping/status/{session_id}")
async def get_ping_status(
    session_id: str,
    current_user: User = Depends(require_technician_or_admin()),
):
    """
    Get the latest ping monitoring status for a session.
    
    Args:
        session_id: Provisioning session identifier
    """
    try:
        is_monitoring = ping_monitor.is_monitoring(session_id)
        latest_result = ping_monitor.get_latest_result(session_id)
        
        return {
            "session_id": session_id,
            "is_monitoring": is_monitoring,
            "latest_result": latest_result
        }
    
    except Exception as e:
        logger.error(f"Failed to get ping status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get ping status: {str(e)}")
