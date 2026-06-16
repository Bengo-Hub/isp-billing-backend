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
    router_id: Optional[int] = Query(None, description="Router ID - if provided, checks whether bootstrap was already done"),
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
    - Reprovisioning detection: if `router_id` provided and router already bootstrapped,
      returns `bootstrap_already_done=true` so the UI can skip straight to API provisioning.
    """
    try:
        # ── Reprovisioning auto-detection ──
        # If the caller provides a router_id, check whether this router already
        # completed bootstrap.  When it has stored API credentials, the frontend
        # can skip the bootstrap step and provision directly via the API.
        bootstrap_already_done = False
        if router_id:
            already_done = await can_use_direct_api(db, router_id)
            if already_done:
                bootstrap_already_done = True
                logger.info(f"Router {router_id} already bootstrapped — direct API provisioning available")

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
            # Pass session_id into the script URL so the script's notify callback can include it
            if session_id:
                script_url += f"&session_id={session_id}"

        # Detect URL scheme and set mode to match (RouterOS 7.16+ requires consistency)
        fetch_mode = "https" if script_url.startswith("https://") else "http"

        # Use proper MikroTik syntax: :delay (with colon) and /import (with forward slash)
        command = f"/tool fetch mode={fetch_mode} url=\"{script_url}\" dst-path=codevertex.rsc;:delay 2s;/import codevertex.rsc;"

        # Always append a callback from the router so the backend knows
        # bootstrap executed (works behind NAT).  Include session_id when
        # available for direct session correlation; otherwise the notify
        # handler falls back to IP/identity-based lookup.
        notify_params = f"token={provisioning_token}&identity={identity}&status=bootstrap_completed"
        if session_id:
            notify_params = f"session_id={session_id}&{notify_params}"
        notify_url = f"{base}/api/v1/provisioning/bootstrap/notify?{notify_params}"
        notify_mode = "https" if notify_url.startswith("https://") else "http"
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
            "encrypted_url": use_encrypted_url,
            "notify_url": notify_url,
            # Reprovisioning detection: if True, the router already ran bootstrap
            # and has stored API credentials.  The frontend can skip the bootstrap
            # step and start direct API provisioning immediately.
            "bootstrap_already_done": bootstrap_already_done,
        }

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
    session_id: Optional[str] = Query(None, description="Provisioning session ID for notify callback"),
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

        # Generate agent token for the polling agent (if router record exists)
        agent_token = None
        router_obj = None
        try:
            from app.models.router import Router as RouterModel
            from app.services.router_agent import RouterAgentService
            router_result = await db.execute(select(RouterModel).where(RouterModel.name == identity))
            router_obj = router_result.scalar_one_or_none()
            if router_obj:
                agent_service = RouterAgentService(db)
                # IMPORTANT: reuse the existing agent token if one is already
                # provisioned. Regenerating on every bootstrap-script fetch would
                # invalidate the token embedded in the agent already running on
                # the router (its polls would start returning 401), which breaks
                # a working device merely by re-previewing the bootstrap command.
                if router_obj.agent_token and router_obj.agent_token_plain:
                    agent_token = router_obj.agent_token_plain
                    logger.info(f"Reusing existing agent token for router {router_obj.id} ({identity})")
                else:
                    agent_token = await agent_service.generate_agent_token(router_obj.id)
                    logger.info(f"Generated agent token for router {router_obj.id} ({identity})")
                router_obj.agent_installed = True
                router_obj.agent_version = settings.agent_script_version
                await db.commit()
        except Exception as e:
            logger.warning(f"Could not generate agent token for {identity}: {e}")

        # Get API user credentials from settings
        api_username = settings.mikrotik_api_username
        api_password = settings.mikrotik_api_password

        # Helper: escape a string value for safe use inside RouterOS
        # double-quoted strings.  RouterOS expands $var inside "..." so we
        # must backslash-escape dollars, backslashes, and double-quotes.
        def _ros_escape(value: str) -> str:
            s = str(value)
            s = s.replace("\\", "\\\\")
            s = s.replace("\"", "\\\"")
            s = s.replace("$", "\\$")
            return s

        safe_password = _ros_escape(api_password)
        safe_username = _ros_escape(api_username)

        lines = [
            "# Codevertex Bootstrap Script - Initial Device Setup",
            "# Generated by Codevertex ISP Billing System",
            f"# User ID: {user_id}",
            "",
            ":put \"\"",
            ":put \"=========================================\"",
            ":put \"Codevertex Bootstrap - Starting Setup\"",
            ":put \"=========================================\"",
            "",
            "# Step 1/8 - Set system identity",
            ":do {",
            f"  /system/identity/set name={identity}",
            f"  :put \"[OK] System identity set to {identity}\"",
            f"  :log info \"BOOTSTRAP: identity set to {identity}\"",
            "} on-error={",
            "  :put \"[FAIL] Failed to set system identity\"",
            "  :log error \"BOOTSTRAP: Failed to set identity\"",
            "}",
            "",
            "# Step 2/8 - Enable API service",
            ":do {",
            f"  /ip/service/set api disabled=no port={api_port}",
            f"  :put \"[OK] API service enabled on port {api_port}\"",
            f"  :log info \"BOOTSTRAP: API enabled on port {api_port}\"",
            "} on-error={",
            "  :put \"[FAIL] Failed to enable API service\"",
            "  :log error \"BOOTSTRAP: Failed to enable API\"",
            "}",
            "",
            "# Step 3/8 - Enable FTP service",
            ":do {",
            "  /ip/service/set [find name=ftp] disabled=no port=21",
            "  :put \"[OK] FTP service enabled on port 21\"",
            "  :log info \"BOOTSTRAP: FTP enabled on port 21\"",
            "} on-error={",
            "  :put \"[FAIL] Failed to enable FTP service\"",
            "  :log error \"BOOTSTRAP: Failed to enable FTP\"",
            "}",
            "",
            "# Step 4/8 - Enable Winbox service",
            ":do {",
            "  /ip/service/set winbox disabled=no",
            "  :put \"[OK] Winbox service enabled\"",
            "  :log info \"BOOTSTRAP: Winbox enabled\"",
            "} on-error={",
            "  :put \"[FAIL] Failed to enable Winbox\"",
            "  :log error \"BOOTSTRAP: Failed to enable Winbox\"",
            "}",
            "",
            "# Step 5/8 - Configure SSH on custom port",
            ":do {",
            "  /ip/service/set ssh port=2222",
            "  :put \"[OK] SSH configured on port 2222\"",
            "  :log info \"BOOTSTRAP: SSH on port 2222\"",
            "} on-error={",
            "  :put \"[FAIL] Failed to configure SSH\"",
            "  :log error \"BOOTSTRAP: Failed to configure SSH\"",
            "}",
            "",
            "# Step 6/8 - Create API user group",
            ":put \"Creating codevertex-api user group...\"",
            ":if ([:len [/user/group/find name=codevertex-api]] = 0) do={",
            "  :do {",
            "    /user/group/add name=codevertex-api policy=local,telnet,ssh,ftp,reboot,read,write,policy,test,winbox,password,web,sniff,sensitive,api,romon,rest-api",
            "    :put \"[OK] User group created\"",
            "    :log info \"BOOTSTRAP: User group codevertex-api created\"",
            "  } on-error={",
            "    :put \"[FAIL] Failed to create user group\"",
            "    :log error \"BOOTSTRAP: Failed to create user group\"",
            "  }",
            "} else={",
            "  :put \"[SKIP] User group already exists\"",
            "  :log info \"BOOTSTRAP: User group already exists\"",
            "}",
            "",
            "# Step 7/8 - Create API user",
            f":put \"Creating API user {api_username}...\"",
            f":if ([:len [/user/find name=\"{safe_username}\"]] > 0) do={{",
            "  :do {",
            f"    /user/remove [find name=\"{safe_username}\"]",
            f"    :put \"[OK] Removed existing user {api_username}\"",
            "  } on-error={",
            "    :put \"[WARN] Could not remove existing user\"",
            "  }",
            "}",
            ":do {",
            f"  /user/add name=\"{safe_username}\" password=\"{safe_password}\" group=codevertex-api comment=\"Codevertex ISP Billing API - DO NOT DELETE\"",
            f"  :put \"[OK] API user {api_username} created\"",
            f"  :log info \"BOOTSTRAP: API user {api_username} created\"",
            "} on-error={",
            "  :put \"[FAIL] Failed to create API user\"",
            "  :log error \"BOOTSTRAP: Failed to create API user\"",
            "}",
            "",
            "# Step 8/8 - Verify interface exists",
            ":do {",
            f"  /interface/print where name={interface}",
            f"  :put \"[OK] Interface {interface} verified\"",
            f"  :log info \"BOOTSTRAP: Interface {interface} verified\"",
            "} on-error={",
            f"  :put \"[WARN] Interface {interface} not found\"",
            f"  :log warning \"BOOTSTRAP: Interface {interface} not found\"",
            "}",
            "",
            "# Optimize system logging",
            ":do {",
            "  /system/logging/action/set memory memory-lines=500",
            "  :put \"[OK] Log memory limit set to 500\"",
            "} on-error={",
            "  :put \"[WARN] Failed to set log memory limit\"",
            "}",
            "",
            ":do {",
            "  /system/logging/set [find] disabled=yes",
            "  :put \"[OK] Disabled existing log rules\"",
            "} on-error={",
            "  :put \"[WARN] Failed to disable log rules\"",
            "}",
            "",
            ":do {",
            "  /system/logging/add topics=error,warning action=memory",
            "  :put \"[OK] Added error/warning logging\"",
            "} on-error={",
            "  :put \"[WARN] Failed to add error logging\"",
            "}",
            "",
            ":do {",
            "  /system/logging/add topics=script,fetch action=memory",
            "  :put \"[OK] Added script/fetch logging\"",
            "} on-error={",
            "  :put \"[WARN] Failed to add script logging\"",
            "}",
        ]

        # POST scan data to backend scan-report endpoint
        try:
            base_scan = settings.backend_url or (request.url.scheme + '://' + request.url.netloc)
            scan_report_url = f"{base_scan}/api/v1/provisioning/bootstrap/scan-report?token={token}&identity={identity}"
            if session_id:
                scan_report_url += f"&session_id={session_id}"
            scan_mode = "https" if scan_report_url.startswith("https://") else "http"
            lines.extend([
                "# Collect device scan data (interfaces, system info, network, services)",
                ":local ifList \"\"",
                ":foreach i in=[/interface/ethernet/find] do={ :local n [/interface/ethernet/get $i name]; :if ([:len $ifList] > 0) do={ :set ifList ($ifList . \",\") }; :set ifList ($ifList . $n) }",
                ":local sysVersion [/system/resource/get version]",
                ":local sysBoard [/system/resource/get board-name]",
                ":local sysArch [/system/resource/get architecture-name]",
                ":local sysCpu [/system/resource/get cpu-count]",
                ":local sysUptime [/system/resource/get uptime]",
                ":local sysTotalMem [/system/resource/get total-memory]",
                ":local sysFreeMem [/system/resource/get free-memory]",
                ":local wanIf \"ether1\"",
                ":do { :foreach r in=[/ip/route/find where dst-address=\"0.0.0.0/0\"] do={ :local gi [/ip/route/get $r gateway]; :if ([:len [/interface/ethernet/find where name=$gi]] > 0) do={ :set wanIf $gi } } } on-error={}",
                ":local hotspotActive 0",
                ":local pppoeActive 0",
                ":local dhcpActive 0",
                ":do { :set hotspotActive [:len [/ip/hotspot/find]] } on-error={}",
                ":do { :set pppoeActive [:len [/interface/pppoe-server/server/find]] } on-error={}",
                ":do { :set dhcpActive [:len [/ip/dhcp-server/find]] } on-error={}",
                ":local ipAddresses \"\"",
                ":foreach a in=[/ip/address/find] do={ :local ad [/ip/address/get $a address]; :local af [/ip/address/get $a interface]; :if ([:len $ipAddresses] > 0) do={ :set ipAddresses ($ipAddresses . \"|\") }; :set ipAddresses ($ipAddresses . $ad . \"@\" . $af) }",
                ":local dnsServers \"\"",
                ":do { :set dnsServers [/ip/dns/get servers] } on-error={}",
                "# POST scan data to backend",
                ":local scanPostData (\"interfaces=\" . $ifList . \"&version=\" . $sysVersion . \"&board=\" . $sysBoard . \"&arch=\" . $sysArch . \"&cpu_count=\" . $sysCpu . \"&uptime=\" . $sysUptime . \"&total_memory=\" . $sysTotalMem . \"&free_memory=\" . $sysFreeMem . \"&wan_interface=\" . $wanIf . \"&hotspot_active=\" . $hotspotActive . \"&pppoe_active=\" . $pppoeActive . \"&dhcp_active=\" . $dhcpActive . \"&ip_addresses=\" . $ipAddresses . \"&dns_servers=\" . $dnsServers)",
                ":do {",
                f"  /tool/fetch mode={scan_mode} url=\"{scan_report_url}\" http-method=post http-data=$scanPostData dst-path=scan-report.result",
                "  :put \"[OK] Scan data sent to backend\"",
                "  :log info \"[BOOTSTRAP] Scan data sent to backend\"",
                "} on-error={ :put \"[WARN] Failed to send scan data (non-critical)\"; :log warning \"[BOOTSTRAP] Failed to send scan data\" }",
                "",
            ])
        except Exception:
            lines.append(":put \"[WARN] Could not build scan-report URL\"")
            lines.append("")

        lines.append(
            "# [STEP 11/13] Download hotspot templates from backend",
        )

        # Add template download commands only if org_slug is available
        if org_slug and settings.backend_url:
            lines.extend([
                "",
                "# Download hotspot templates",
                ":put \"Downloading hotspot templates...\"",
                ":do {",
                f"  /tool/fetch url=\"{settings.backend_url}/api/v1/provisioning/templates/login.html?org_slug={org_slug}\" dst-path=hotspot/login.html",
                "  :put \"[OK] Downloaded login.html\"",
                "} on-error={",
                "  :put \"[WARN] Failed to download login.html\"",
                "}",
                "",
                ":do {",
                f"  /tool/fetch url=\"{settings.backend_url}/api/v1/provisioning/templates/alogin.html?org_slug={org_slug}\" dst-path=hotspot/alogin.html",
                "  :put \"[OK] Downloaded alogin.html\"",
                "} on-error={",
                "  :put \"[WARN] Failed to download alogin.html\"",
                "}",
            ])
        else:
            lines.extend([
                "",
                ":put \"[SKIP] Template download skipped (FTP fallback during provisioning)\"",
            ])

        # Install the CodeVertex polling agent so the router phones home for
        # commands on a recurring schedule. Without this, queued subscriber
        # commands (create_user on payment, disable on expiry) are NEVER
        # delivered to a NAT'd router — which was the case in production
        # (agent_installed=true was set but nothing actually installed it).
        if router_obj and agent_token and settings.backend_url:
            agent_install_url = (
                f"{settings.backend_url}/api/v1/router-agent/script/{router_obj.id}"
                f"?token={agent_token}"
            )
            agent_mode = "https" if agent_install_url.startswith("https://") else "http"
            lines.extend([
                "",
                "# Install CodeVertex polling agent (NAT-safe command channel)",
                ":put \"Installing CodeVertex polling agent...\"",
                ":do {",
                f"  /tool/fetch mode={agent_mode} url=\"{agent_install_url}\" dst-path=cvagent-install.rsc",
                "  :delay 2s",
                "  /import file-name=cvagent-install.rsc",
                "  :put \"[OK] Polling agent installed\"",
                "  :log info \"BOOTSTRAP: polling agent installed\"",
                "} on-error={",
                "  :put \"[WARN] Failed to install polling agent (non-critical)\"",
                "  :log warning \"BOOTSTRAP: agent install failed\"",
                "}",
            ])
        else:
            lines.append(":put \"[SKIP] Polling agent install skipped (no router record/token)\"")

        # ── WireGuard VPN overlay enrollment ──
        # If the platform has a WG server pubkey configured AND we have a router
        # record, allocate a tunnel IP and emit the RouterOS WireGuard client
        # config. The router generates + keeps its own private key and POSTs its
        # public key back to /bootstrap/wg-register. Skipped entirely (router
        # stays on the polling-agent fallback) when WG is not configured.
        try:
            from app.services.wireguard import WireGuardService

            wg_service = WireGuardService(db)
            if router_obj and wg_service.enabled and settings.backend_url:
                tunnel_ip = await wg_service.allocate_ip(router_obj)
                # Pre-assign the tunnel IP so the reconcile loop and the
                # register callback agree on the address (idempotent allocate).
                router_obj.vpn_address = tunnel_ip
                await db.commit()

                wg_register_url = (
                    f"{settings.backend_url}/api/v1/provisioning/bootstrap/wg-register"
                    f"?token={token}&identity={identity}"
                )
                lines.extend(
                    wg_service.build_bootstrap_lines(
                        tunnel_ip=tunnel_ip,
                        wg_register_url=wg_register_url,
                    )
                )
                logger.info(
                    f"Bootstrap: emitted WG VPN config for router {router_obj.id} "
                    f"(tunnel_ip={tunnel_ip})"
                )
            elif not wg_service.enabled:
                lines.append(":put \"[SKIP] VPN tunnel skipped (WireGuard not configured on platform)\"")
        except Exception as e:
            logger.warning(f"Bootstrap: could not emit WG VPN config: {e}")
            lines.append(":put \"[WARN] VPN tunnel config skipped (error)\"")

        # Completion summary
        lines.extend([
            "",
            ":put \"\"",
            ":put \"=========================================\"",
            f":put \"Bootstrap completed for {identity}\"",
            f":put \"API enabled on port {api_port}\"",
            f":put \"API user: {api_username}\"",
            ":put \"Ready for provisioning workflow\"",
            ":put \"=========================================\"",
            ":put \"\"",
            f":log info \"BOOTSTRAP: completed for {identity}\"",
        ])

        # NOTE: The bootstrap command (one-liner) already appends a
        # /tool fetch POST to the notify endpoint when session_id is
        # provided.  We intentionally do NOT embed a notify call inside
        # the .rsc script itself because the JWT token would make the
        # URL extremely long and fragile.  The outer command handles it.

        return "\n".join(lines) + "\n"

    except Exception as e:
        logger.error(f"Failed to generate bootstrap script: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate bootstrap script")


@router.post('/scan-report')
async def bootstrap_scan_report(
    request: Request,
    token: str = Query(..., description="Provisioning token (required)"),
    identity: Optional[str] = Query(None, description="Router identity"),
    session_id: Optional[str] = Query(None, description="Provisioning session ID"),
    db: AsyncSession = Depends(get_db),
):
    """Receive device scan data collected by the bootstrap script running on the router.

    The bootstrap script collects interface names, service status, system info, and
    network configuration from the router itself, then POSTs this data here. This
    eliminates the need for the cloud backend to connect directly to the router's
    API port (which is impossible when the router is on a private/NAT'd network).

    The scan data is stored via store_scanned_config() so the frontend's device scan
    endpoint can return cached data without needing a direct connection.
    """
    from app.core.security import verify_token
    from app.services.router_provisioning import store_scanned_config

    # Verify token
    try:
        token_data = verify_token(token, token_type='access')
    except Exception as e:
        logger.warning(f'Scan report: token verification failed: {e}')
        raise HTTPException(status_code=401, detail='Invalid token')

    # Parse POST body (form-encoded from RouterOS /tool/fetch http-data=)
    try:
        body = await request.body()
        body_str = body.decode('utf-8', errors='replace')
        # Parse URL-encoded form data
        from urllib.parse import parse_qs
        form_data = parse_qs(body_str, keep_blank_values=True)
        # parse_qs returns lists; flatten to single values
        data = {k: v[0] if v else '' for k, v in form_data.items()}
    except Exception as e:
        logger.error(f'Scan report: failed to parse body: {e}')
        raise HTTPException(status_code=400, detail='Failed to parse scan data')

    logger.info(f"Scan report received: identity={identity}, interfaces={data.get('interfaces', '')}, version={data.get('version', '')}")

    # Build structured scan data
    interfaces_str = data.get('interfaces', '')
    interfaces = [i.strip() for i in interfaces_str.split(',') if i.strip()] if interfaces_str else []

    # Parse IP addresses (format: addr@iface|addr@iface)
    ip_addresses_str = data.get('ip_addresses', '')
    ip_entries = []
    wan_interface = data.get('wan_interface', 'ether1')
    router_ip = ''
    router_ip_cidr = ''
    if ip_addresses_str:
        for entry in ip_addresses_str.split('|'):
            if '@' in entry:
                addr, iface = entry.split('@', 1)
                ip_entries.append({'address': addr, 'interface': iface})
                # Use first non-WAN address as router_ip
                if iface != wan_interface and not router_ip:
                    router_ip_cidr = addr
                    router_ip = addr.split('/')[0] if '/' in addr else addr

    # If no non-WAN IP found, use first available
    if not router_ip and ip_entries:
        router_ip_cidr = ip_entries[0]['address']
        router_ip = router_ip_cidr.split('/')[0] if '/' in router_ip_cidr else router_ip_cidr

    # Calculate network config from router IP CIDR
    cidr = 24
    network_address = ''
    gateway = ''
    subnet_mask = '255.255.255.0'
    if '/' in router_ip_cidr:
        ip_part, cidr_str = router_ip_cidr.split('/')
        cidr = int(cidr_str)
        parts = ip_part.split('.')
        if cidr == 24:
            network_address = f"{parts[0]}.{parts[1]}.{parts[2]}.0"
            gateway = f"{parts[0]}.{parts[1]}.{parts[2]}.1"
            subnet_mask = '255.255.255.0'
        elif cidr == 16:
            network_address = f"{parts[0]}.{parts[1]}.0.0"
            gateway = f"{parts[0]}.{parts[1]}.0.1"
            subnet_mask = '255.255.0.0'
        else:
            network_address = f"{parts[0]}.{parts[1]}.{parts[2]}.0"
            gateway = f"{parts[0]}.{parts[1]}.{parts[2]}.1"

    # Parse DNS servers
    dns_str = data.get('dns_servers', '')
    dns_servers = [d.strip() for d in dns_str.split(',') if d.strip()] if dns_str else []

    # Build service status
    services = [
        {
            'name': 'hotspot',
            'active': data.get('hotspot_active', 'false').lower() == 'true',
            'available': True,
        },
        {
            'name': 'pppoe',
            'active': data.get('pppoe_active', 'false').lower() == 'true',
            'available': True,
        },
        {
            'name': 'dhcp',
            'active': data.get('dhcp_active', 'false').lower() == 'true',
            'available': True,
        },
    ]

    # Build network config
    network_config = {
        'router_ip': router_ip,
        'router_ip_cidr': router_ip_cidr,
        'network': f"{network_address}/{cidr}" if network_address else '',
        'network_address': network_address,
        'gateway': gateway,
        'broadcast': '',
        'dhcp_start': '',
        'dhcp_end': '',
        'dhcp_pool': '',
        'subnet_mask': subnet_mask,
        'cidr': cidr,
        'total_hosts': (2 ** (32 - cidr)) - 2 if cidr < 32 else 1,
        'dns_servers': dns_servers,
        'current_subnet': router_ip_cidr,
        'wan_interface': wan_interface,
        'ip_addresses': ip_entries,
    }

    # Build system info
    system_info = {
        'identity': identity or data.get('identity', ''),
        'board_name': data.get('board', ''),
        'model': data.get('board', ''),
        'version': data.get('version', ''),
        'architecture': data.get('arch', ''),
        'cpu_count': int(data.get('cpu_count', '0') or '0'),
        'cpu_load': None,
        'total_memory': data.get('total_memory', ''),
        'free_memory': data.get('free_memory', ''),
        'uptime': data.get('uptime', ''),
        'time': '',
        'timezone': '',
    }

    # Find router by identity or IP
    from app.models.router import Router as RouterModel
    client_ip = request.client.host if request.client else None
    router_obj = None

    if identity:
        result = await db.execute(select(RouterModel).where(RouterModel.name == identity))
        router_obj = result.scalar_one_or_none()

    if not router_obj and client_ip:
        result = await db.execute(select(RouterModel).where(RouterModel.ip_address == client_ip))
        router_obj = result.scalar_one_or_none()

    if router_obj:
        try:
            await store_scanned_config(
                db=db,
                router_id=router_obj.id,
                interfaces=interfaces,
                services=services,
                network_config=network_config,
                system_info=system_info,
            )
            logger.info(f"Scan report: stored config for router {router_obj.id} ({identity}): {len(interfaces)} interfaces")
        except Exception as e:
            logger.error(f"Scan report: failed to store config: {e}")
            # Don't fail - the data was received, just couldn't persist
    else:
        logger.info(
            f"Scan report: no router record yet for identity={identity} "
            f"(first-time provisioning) — caching {len(interfaces)} interfaces by session/identity"
        )

    # Cache the scan by session_id + identity REGARDLESS of a router record, so
    # the wizard reads the device's REAL interfaces during first-time provisioning
    # (before any Router DB row exists) instead of a hardcoded fallback list.
    scan_payload = {
        'interfaces': interfaces,
        'wan_interface': wan_interface,
        'services': services,
        'network_config': network_config,
        'system_info': system_info,
    }
    try:
        from app.services.ping_monitor import ping_monitor
        if session_id:
            ping_monitor.scanned_configs[session_id] = scan_payload
        if identity:
            ping_monitor.scanned_configs[f'identity:{identity}'] = scan_payload
    except Exception:
        pass

    # ALWAYS broadcast scan_complete (router record or not) so the live wizard
    # replaces the fallback ports with the device's actual interfaces.
    if session_id:
        try:
            from app.api.v1.provisioning.stream import manager
            await manager.send_message(session_id, {
                'type': 'scan_complete',
                'session_id': session_id,
                'data': {
                    'interfaces': interfaces,
                    'wan_interface': wan_interface,
                    'version': system_info.get('version', ''),
                    'board': system_info.get('board_name', ''),
                    'services': services,
                    'network_config': network_config,
                    'message': 'Device scan data received from bootstrap',
                }
            })
        except Exception:
            pass  # WebSocket broadcast is best-effort

    return {
        'success': True,
        'router_id': router_obj.id if router_obj else None,
        'interfaces_count': len(interfaces),
        'version': system_info.get('version', ''),
    }


@router.post('/notify')
async def provisioning_notify(
    request: Request,
    session_id: Optional[str] = Query(None, description="Provisioning session UUID"),
    token: Optional[str] = Query(None, description="Provisioning token (required)"),
    identity: Optional[str] = Query(None, description="Router identity name"),
    ip_address: Optional[str] = Query(None, description="Router-reported IP"),
    status: str = Query('bootstrap_completed'),
    db: AsyncSession = Depends(get_db),
):
    """Unified callback endpoint for routers to notify backend when bootstrap completes.

    Supports two correlation strategies (tried in order):
    1. **session_id** - Direct session lookup (preferred, provided by bootstrap command)
    2. **IP / identity** - Fallback: find router by IP or name, then find active session

    After correlating:
    - Marks provisioning session as bootstrap_completed
    - Stores encrypted API credentials on the router for future reprovisioning
    - Broadcasts `provisioning_complete` over WebSocket so UI auto-advances
    - Stops any active ping monitoring
    """
    if not token:
        raise HTTPException(status_code=400, detail='Token is required')

    from app.core.security import verify_token
    try:
        token_data = verify_token(token, token_type='access')
    except Exception as e:
        logger.warning(f'Provisioning notify: token verification failed: {e}')
        raise HTTPException(status_code=401, detail='Invalid token')

    client_ip = ip_address or (request.client.host if request.client else None)

    try:
        from app.models.router import Router
        from app.models.provisioning import ProvisioningSession, ProvisioningStatus
        from app.api.v1.provisioning.stream import manager
        from app.services.router_provisioning import store_router_credentials

        session_found = None
        found_router = None

        # Strategy 1: Direct session_id lookup
        if session_id:
            result = await db.execute(
                select(ProvisioningSession).where(ProvisioningSession.session_id == session_id)
            )
            session_found = result.scalar_one_or_none()
            if session_found:
                # Resolve the router for credential storage
                if session_found.router_id:
                    rr = await db.execute(select(Router).where(Router.id == session_found.router_id))
                    found_router = rr.scalar_one_or_none()

        # Strategy 2: IP / identity based lookup
        if not session_found:
            if client_ip:
                rr = await db.execute(select(Router).where(Router.ip_address == client_ip))
                found_router = rr.scalar_one_or_none()
            if not found_router and identity:
                try:
                    rr = await db.execute(select(Router).where(Router.name == identity))
                    found_router = rr.scalar_one_or_none()
                except Exception:
                    pass

            if found_router:
                sr = await db.execute(
                    select(ProvisioningSession)
                    .where(
                        ProvisioningSession.router_id == found_router.id,
                        ProvisioningSession.status.in_([
                            ProvisioningStatus.PENDING,
                            ProvisioningStatus.IN_PROGRESS,
                        ])
                    )
                    .order_by(ProvisioningSession.created_at.desc())
                    .limit(1)
                )
                session_found = sr.scalar_one_or_none()

        # ── Store API credentials on the router for future reprovisioning ──
        if found_router:
            try:
                await store_router_credentials(db, found_router.id)
                logger.info(f'Provisioning notify: stored credentials for router {found_router.id}')
            except Exception as e:
                logger.warning(f'Provisioning notify: failed to store credentials: {e}')

        # ── Update session & broadcast ──
        sid = None
        if session_found:
            sid = session_found.session_id
            session_found.status = ProvisioningStatus.COMPLETED
            session_found.completed_at = datetime.utcnow()
            try:
                session_found.progress_percentage = 100.0
            except Exception:
                pass
            await db.commit()
            logger.info(f'Provisioning notify: session {sid} marked completed')

        # Mark the device ONLINE for the UI via the authoritative router->backend
        # check-in (NAT-safe). This flips Stage 1 (network) + Stage 2 (API) to
        # success and pushes device_online — whether the UI is already listening
        # OR opens monitoring later (start_monitoring re-emits from the stored
        # verified result instead of running the cloud-ping loop that aborts on a
        # private RFC1918 IP). Keyed by the session in the notify URL so it
        # correlates with the UI even when the DB session isn't matched.
        effective_sid = sid or session_id
        if effective_sid:
            try:
                await ping_monitor.mark_online_from_notify(effective_sid, client_ip, identity)
            except Exception:
                logger.debug('Provisioning notify: ping_monitor mark_online failed')
            # Legacy event some UIs also listen for.
            try:
                await manager.send_message(effective_sid, {
                    'type': 'provisioning_complete',
                    'session_id': effective_sid,
                    'data': {
                        'message': 'Device reported bootstrap completion',
                        'ip_address': client_ip,
                        'identity': identity,
                        'status': status,
                    }
                })
            except Exception:
                pass
            return {'status': 'ok', 'session_id': effective_sid}

        # No session found — record pending check-in for future correlation
        ping_monitor.register_device_checkin(
            client_ip,
            {
                'identity': identity,
                'token_sub': getattr(token_data, 'sub', None),
                'timestamp': datetime.utcnow().isoformat(),
            },
        )
        logger.info(f'Provisioning notify: recorded pending check-in for IP {client_ip}')
        return {'status': 'ok', 'session_id': None, 'note': 'pending_checkin_recorded'}

    except Exception as e:
        logger.error(f'Provisioning notify failed: {e}')
        raise HTTPException(status_code=500, detail='Failed to handle notify')


@router.post('/wg-register')
async def bootstrap_wg_register(
    request: Request,
    token: str = Query(..., description="Provisioning token (required)"),
    identity: Optional[str] = Query(None, description="Router identity name"),
    db: AsyncSession = Depends(get_db),
):
    """Receive a router's WireGuard PUBLIC key during bootstrap.

    The router generated and KEPT its own private key (RouterOS auto-generates
    it); only the public key is POSTed here (form-encoded ``public_key=…`` from
    RouterOS ``/tool/fetch http-data=``). We store the public key + tunnel IP and
    flip ``vpn_enabled`` so the WG server reconcile loop picks the peer up and
    the backend starts addressing the router over the tunnel.

    Auth: the provisioning token (same as the other bootstrap callbacks). No
    private key material is ever transmitted or stored.
    """
    from app.core.security import verify_token
    from urllib.parse import parse_qs

    try:
        verify_token(token, token_type='access')
    except Exception as e:
        logger.warning(f'wg-register: token verification failed: {e}')
        raise HTTPException(status_code=401, detail='Invalid token')

    # Parse the form body for public_key
    public_key = None
    try:
        body = await request.body()
        form = parse_qs(body.decode('utf-8', errors='replace'), keep_blank_values=True)
        public_key = (form.get('public_key', [''])[0] or '').strip()
    except Exception as e:
        logger.error(f'wg-register: failed to parse body: {e}')
    if not public_key:
        # Fall back to a query param (some RouterOS fetch variants send it there)
        public_key = (request.query_params.get('public_key') or '').strip()
    if not public_key:
        raise HTTPException(status_code=400, detail='Missing public_key')

    from app.models.router import Router as RouterModel
    from app.services.wireguard import WireGuardService

    # Correlate the router by identity (name) then by reporting IP.
    router_obj = None
    if identity:
        result = await db.execute(select(RouterModel).where(RouterModel.name == identity))
        router_obj = result.scalar_one_or_none()
    if not router_obj and request.client:
        result = await db.execute(
            select(RouterModel).where(RouterModel.ip_address == request.client.host)
        )
        router_obj = result.scalar_one_or_none()

    if not router_obj:
        logger.warning(f'wg-register: no router found for identity={identity}')
        raise HTTPException(status_code=404, detail='Router not found')

    try:
        svc = WireGuardService(db)
        await svc.register_peer(router_obj, public_key)
        await db.commit()
        logger.info(
            f'wg-register: router {router_obj.id} enrolled '
            f'(vpn_address={router_obj.vpn_address})'
        )
        return {
            'status': 'ok',
            'router_id': router_obj.id,
            'vpn_address': router_obj.vpn_address,
            'vpn_enabled': router_obj.vpn_enabled,
        }
    except Exception as e:
        await db.rollback()
        logger.error(f'wg-register failed: {e}')
        raise HTTPException(status_code=500, detail='Failed to register WireGuard peer')


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
            "provisioning_status": str,
            "agent_installed": bool,
            "agent_online": bool,
            "has_cached_scan": bool
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

        # Determine if agent is online based on last_poll_at
        agent_online = False
        if router.agent_installed and router.last_poll_at:
            elapsed = (datetime.utcnow() - router.last_poll_at).total_seconds()
            threshold = (router.agent_poll_interval or 30) * 3  # 3x poll interval
            agent_online = elapsed < threshold

        # Check if we have cached scan data in router.config
        has_cached_scan = False
        try:
            if router.config:
                config_data = json.loads(router.config) if isinstance(router.config, str) else router.config
                has_cached_scan = bool(config_data.get("scanned_data"))
        except Exception:
            pass

        return {
            "can_use_direct_api": has_access,
            "bootstrap_completed": router.bootstrap_completed or False,
            "provisioning_status": router.provisioning_status or 'pending',
            "last_provisioned_at": router.last_provisioned_at.isoformat() if router.last_provisioned_at else None,
            "agent_installed": router.agent_installed or False,
            "agent_online": agent_online,
            "has_cached_scan": has_cached_scan,
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
    identity: Optional[str] = Query(None, description="Router identity (for NAT-safe cross-session check-in correlation)"),
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
            timeout_ms=timeout_ms,
            identity=identity,
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
