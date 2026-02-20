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
            # Pass session_id into the script URL so the script's notify callback can include it
            if session_id:
                script_url += f"&session_id={session_id}"

        # Detect URL scheme and set mode to match (RouterOS 7.16+ requires consistency)
        fetch_mode = "https" if script_url.startswith("https://") else "http"

        # Use proper MikroTik syntax: :delay (with colon) and /import (with forward slash)
        command = f"/tool fetch mode={fetch_mode} url=\"{script_url}\" dst-path=codevertex.rsc;:delay 2s;/import codevertex.rsc;"

        # If the provisioning UI provided a session_id, append a callback from
        # the router back to the backend so the UI gets an immediate signal that
        # bootstrap executed (router-initiated callback works behind NAT).
        if session_id:
            notify_url = f"{base}/api/v1/provisioning/bootstrap/notify?session_id={session_id}&token={provisioning_token}&status=bootstrap_completed"
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
                agent_token = await agent_service.generate_agent_token(router_obj.id)
                router_obj.agent_installed = True
                router_obj.agent_version = settings.agent_script_version
                await db.commit()
                logger.info(f"Generated agent token for router {router_obj.id} ({identity})")
        except Exception as e:
            logger.warning(f"Could not generate agent token for {identity}: {e}")

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
            "# Try v7 policies first (includes romon,rest-api), fall back to v6 if unsupported",
            ":put \"Creating codevertex-api user group...\"",
            ":log info \"[BOOTSTRAP] Creating codevertex-api user group...\"",
            ":if ([:len [/user/group/find name=\"codevertex-api\"]] = 0) do={",
            "  :do {",
            "    /user/group/add name=\"codevertex-api\" policy=local,telnet,ssh,ftp,reboot,read,write,policy,test,winbox,password,web,sniff,sensitive,api,romon,rest-api;",
            "    :put \"[OK] User group 'codevertex-api' created (v7 policies)\";",
            "    :log info \"[BOOTSTRAP] User group 'codevertex-api' created with v7 policies\"",
            "  } on-error={",
            "    :do {",
            "      /user/group/add name=\"codevertex-api\" policy=local,telnet,ssh,ftp,reboot,read,write,policy,test,winbox,password,web,sniff,sensitive,api;",
            "      :put \"[OK] User group 'codevertex-api' created (v6 policies)\";",
            "      :log info \"[BOOTSTRAP] User group 'codevertex-api' created with v6 policies (romon/rest-api not available)\"",
            "    } on-error={ :put \"[FAIL] Failed to create user group\"; :log error \"[BOOTSTRAP] Failed to create user group\" }",
            "  }",
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
            "# [STEP 10/13] Collect device scan data and report to backend",
            "# This allows the cloud backend to know the router's interfaces, services,",
            "# and system info without needing direct API connectivity to the router.",
            ":put \"Collecting device scan data...\"",
            ":log info \"[BOOTSTRAP] Collecting device scan data...\"",
            "",
            "# Collect ethernet interface names",
            ":local ifList \"\"",
            ":do {",
            "  :foreach i in=[/interface/ethernet/find] do={",
            "    :local ifName [/interface/ethernet/get $i name]",
            "    :if ([:len $ifList] > 0) do={ :set ifList ($ifList . \",\") }",
            "    :set ifList ($ifList . $ifName)",
            "  }",
            "  :put (\"[OK] Ethernet interfaces: \" . $ifList)",
            "} on-error={ :put \"[WARN] Failed to collect ethernet interfaces\" }",
            "",
            "# Note: SFP interfaces are included under /interface/ethernet/ on RouterOS v7",
            "# No separate SFP collection needed (avoids parse error on routers without SFP menu)",
            "",
            "# Collect system info",
            ":local sysVersion \"\"",
            ":local sysBoard \"\"",
            ":local sysArch \"\"",
            ":local sysCpu \"0\"",
            ":local sysUptime \"\"",
            ":local sysTotalMem \"0\"",
            ":local sysFreeMem \"0\"",
            ":do {",
            "  :set sysVersion [/system/resource/get version]",
            "  :set sysBoard [/system/resource/get board-name]",
            "  :set sysArch [/system/resource/get architecture-name]",
            "  :set sysCpu [:tostr [/system/resource/get cpu-count]]",
            "  :set sysUptime [/system/resource/get uptime]",
            "  :set sysTotalMem [:tostr [/system/resource/get total-memory]]",
            "  :set sysFreeMem [:tostr [/system/resource/get free-memory]]",
            "  :put (\"[OK] System: \" . $sysBoard . \" / RouterOS \" . $sysVersion . \" / \" . $sysArch)",
            "} on-error={ :put \"[WARN] Failed to collect system info\" }",
            "",
            "# Detect WAN interface (interface with default route)",
            ":local wanIf \"ether1\"",
            ":do {",
            "  :foreach i in=[/ip/route/find where dst-address=\"0.0.0.0/0\" active=yes] do={",
            "    :local gw [/ip/route/get $i gateway]",
            "    :foreach a in=[/ip/address/find] do={",
            "      :local addr [/ip/address/get $a address]",
            "      :local net [/ip/address/get $a network]",
            "      :local iface [/ip/address/get $a interface]",
            "      :if ($net = [:pick $gw 0 [:find $gw \"/\"]]) do={ :set wanIf $iface }",
            "    }",
            "  }",
            "  :put (\"[OK] WAN interface: \" . $wanIf)",
            "} on-error={ :put \"[WARN] WAN detection failed, defaulting to ether1\" }",
            "",
            "# Check service status",
            ":local hotspotActive \"false\"",
            ":local pppoeActive \"false\"",
            ":local dhcpActive \"false\"",
            ":do { :if ([:len [/ip/hotspot/find]] > 0) do={ :set hotspotActive \"true\" } } on-error={}",
            ":do { :if ([:len [/interface/pppoe-server/server/find]] > 0) do={ :set pppoeActive \"true\" } } on-error={}",
            ":do { :if ([:len [/ip/dhcp-server/find]] > 0) do={ :set dhcpActive \"true\" } } on-error={}",
            ":put (\"[OK] Services - Hotspot: \" . $hotspotActive . \", PPPoE: \" . $pppoeActive . \", DHCP: \" . $dhcpActive)",
            "",
            "# Collect IP addresses (format: addr@iface separated by |)",
            ":local ipAddresses \"\"",
            ":do {",
            "  :foreach i in=[/ip/address/find] do={",
            "    :local addr [/ip/address/get $i address]",
            "    :local iface [/ip/address/get $i interface]",
            "    :if ([:len $ipAddresses] > 0) do={ :set ipAddresses ($ipAddresses . \"|\") }",
            "    :set ipAddresses ($ipAddresses . $addr . \"@\" . $iface)",
            "  }",
            "} on-error={ :put \"[WARN] Failed to collect IP addresses\" }",
            "",
            "# Collect DNS servers",
            ":local dnsServers \"\"",
            ":do { :set dnsServers [/ip/dns/get servers] } on-error={}",
            "",
        ]

        # POST scan data to backend scan-report endpoint
        try:
            base_scan = settings.backend_url or (request.url.scheme + '://' + request.url.netloc)
            scan_report_url = f"{base_scan}/api/v1/provisioning/bootstrap/scan-report?token={token}&identity={identity}"
            if session_id:
                scan_report_url += f"&session_id={session_id}"
            scan_mode = "https" if scan_report_url.startswith("https://") else "http"
            lines.extend([
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

        # [STEP 12/14] Install CodeVertex polling agent
        # Downloads agent code as a standalone .rsc file, then creates a scheduler
        # that runs /import on it every N seconds. No complex escaping needed.
        if agent_token and settings.backend_url and router_obj:
            agent_script_url = f"{settings.backend_url}/api/v1/router-agent/script/{router_obj.id}?token={agent_token}"
            agent_fetch_mode = "https" if agent_script_url.startswith("https://") else "http"
            poll_interval = settings.agent_default_poll_interval

            lines.extend([
                f"# [STEP 12/14] Install CodeVertex polling agent (polls every {poll_interval}s)",
                ":put \"Installing CodeVertex billing agent...\"",
                ":log info \"[BOOTSTRAP] Installing CodeVertex billing agent...\"",
                "",
                "# Download agent code to router filesystem",
                ":do {",
                f"  /tool/fetch mode={agent_fetch_mode} url=\"{agent_script_url}\" dst-path=codevertex-agent.rsc",
                "  :put \"[OK] Agent code downloaded\"",
                "  :log info \"[BOOTSTRAP] Agent code downloaded\"",
                "} on-error={",
                "  :put \"[WARN] Failed to download agent code\"",
                "  :log warning \"[BOOTSTRAP] Failed to download agent code\"",
                "}",
                "",
                "# Remove existing agent scheduler",
                ":do { /system/scheduler/remove [find name=\"codevertex-agent\"] } on-error={}",
                "",
                f"# Create scheduler to run agent every {poll_interval} seconds",
                ":do {",
                f"  /system/scheduler/add name=\"codevertex-agent\" interval={poll_interval}s on-event=\"/import codevertex-agent.rsc\" policy=ftp,reboot,read,write,policy,test,password,sniff,sensitive,api",
                f"  :put \"[OK] Agent scheduler created (every {poll_interval}s)\"",
                f"  :log info \"[BOOTSTRAP] Agent scheduler created (every {poll_interval}s)\"",
                "} on-error={",
                "  :put \"[WARN] Failed to create agent scheduler\"",
                "  :log warning \"[BOOTSTRAP] Failed to create agent scheduler\"",
                "}",
                "",
            ])
        else:
            lines.extend([
                "# [STEP 12/14] Polling agent skipped (no router record or backend URL)",
                ":put \"[SKIP] Billing agent not installed (router record not found)\"",
                ":log info \"[BOOTSTRAP] Billing agent skipped - router record not found\"",
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
            base_notify = settings.backend_url or (request.url.scheme + '://' + request.url.netloc)
            notify_url = f"{base_notify}/api/v1/provisioning/bootstrap/notify?token={token}&identity={identity}"
            # Include session_id in the notify callback so the backend can correlate
            # with the WebSocket session and broadcast stage_complete/device_online
            if session_id:
                notify_url += f"&session_id={session_id}"
            notify_mode = "https" if notify_url.startswith("https://") else "http"
            lines.append(":put \"Notifying backend of bootstrap completion...\"")
            lines.append(f"/tool fetch mode={notify_mode} url=\"{notify_url}\" http-method=post dst-path=notify.result; :put \"[OK] Notified backend (notify.result)\"; :log info \"[BOOTSTRAP] Notified backend of bootstrap completion\"")
        except Exception:
            # Best effort - don't fail script generation if notify_url cannot be built
            lines.append(":put \"[WARN] Could not append backend notify call to bootstrap script\"")

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

            # Broadcast scan_complete via WebSocket if session_id provided
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
                            'message': 'Device scan data received from bootstrap',
                        }
                    })
                except Exception:
                    pass  # WebSocket broadcast is best-effort

        except Exception as e:
            logger.error(f"Scan report: failed to store config: {e}")
            # Don't fail - the data was received, just couldn't persist
    else:
        logger.warning(f"Scan report: no router found for identity={identity}, ip={client_ip}")

    return {
        'success': True,
        'router_id': router_obj.id if router_obj else None,
        'interfaces_count': len(interfaces),
        'version': system_info.get('version', ''),
    }


@router.post('/notify')
async def provisioning_notify(
    request: Request,
    session_id: Optional[str] = Query(None, description="Provisioning session UUID (from ping monitoring)"),
    token: Optional[str] = Query(None, description="Provisioning token (required)"),
    status: str = Query('bootstrap_completed'),
    identity: Optional[str] = Query(None, description="Router identity reported by device"),
    ip_address: Optional[str] = Query(None, description="Router IP (falls back to request.client.host)"),
    db: AsyncSession = Depends(get_db),
):
    """Unified callback endpoint for routers to notify backend when bootstrap completes.

    Called by the router after executing the bootstrap script. This endpoint:
    1. Verifies the provisioning token
    2. Resolves the target WebSocket session (by session_id, or by IP/identity lookup)
    3. Broadcasts stage_complete + device_online messages so the frontend Step 2
       verification advances (NOT provisioning_complete, which is for Step 3)
    4. Updates ping_monitor state and stops active monitoring
    5. Records a pending check-in if no active session is found

    This works for both cloud deployments (where the backend can't ping the router)
    and local deployments (where ping monitoring may already be running).
    """
    if not token:
        raise HTTPException(status_code=400, detail='Token is required')

    from app.core.security import verify_token
    try:
        token_data = verify_token(token, token_type='access')
    except Exception as e:
        logger.warning(f'Provisioning notify: token verification failed: {e}')
        raise HTTPException(status_code=401, detail='Invalid token')

    # Resolve client IP
    client_ip = ip_address or (request.client.host if request.client else None)

    try:
        from app.api.v1.provisioning.stream import manager
        from app.services.ping_monitor import ping_monitor

        # Determine which WebSocket session to broadcast to.
        # Priority: explicit session_id > DB session lookup by IP/identity
        target_sid = session_id

        # If no session_id provided (or it's a temp ping-* ID with no DB record),
        # try to find a matching ProvisioningSession via router IP or identity
        if not target_sid:
            from app.models.router import Router as RouterModel
            found_router = None

            if client_ip:
                router_result = await db.execute(select(RouterModel).where(RouterModel.ip_address == client_ip))
                found_router = router_result.scalar_one_or_none()

            if not found_router and identity:
                try:
                    router_result = await db.execute(select(RouterModel).where(RouterModel.name == identity))
                    found_router = router_result.scalar_one_or_none()
                except Exception:
                    found_router = None

            if found_router:
                from app.models.provisioning import ProvisioningStatus
                session_result = await db.execute(
                    select(ProvisioningSession)
                    .where(
                        ProvisioningSession.router_id == found_router.id,
                        ProvisioningSession.status.in_([ProvisioningStatus.PENDING, ProvisioningStatus.IN_PROGRESS])
                    )
                    .order_by(ProvisioningSession.created_at.desc())
                    .limit(1)
                )
                session_found = session_result.scalar_one_or_none()
                if session_found:
                    target_sid = session_found.session_id

        if target_sid:
            # Update ping_monitor state so it knows the device is online
            ping_monitor.monitor_results[target_sid] = {
                'attempt': 0,
                'ping_verified': True,
                'api_verified': True,
                'ip_address': client_ip,
                'method': 'device-notify',
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            }

            # Stop any active ping monitoring for this session
            try:
                if ping_monitor.is_monitoring(target_sid):
                    await ping_monitor.stop_monitoring(target_sid)
            except Exception:
                logger.debug(f'Provisioning notify: ping_monitor stop failed for {target_sid}')

            # Broadcast Step 2-compatible messages so the frontend verification
            # stages advance. The frontend expects stage_complete for stages 1
            # and 2, then device_online to enable the Continue button.
            now_iso = datetime.utcnow().isoformat()

            # Stage 1: Network reachability confirmed (device called us)
            await manager.send_message(target_sid, {
                'type': 'stage_complete',
                'session_id': target_sid,
                'data': {
                    'stage': 1,
                    'stage_name': 'Network',
                    'message': 'Device reachable (bootstrap callback received)',
                    'timestamp': now_iso,
                }
            })

            # Stage 2: API port confirmed (bootstrap enables API before calling notify)
            await manager.send_message(target_sid, {
                'type': 'stage_complete',
                'session_id': target_sid,
                'data': {
                    'stage': 2,
                    'stage_name': 'API',
                    'message': 'API service enabled (bootstrap confirmed)',
                    'timestamp': now_iso,
                }
            })

            # Device online: triggers the full verification in DeviceDetailsStep
            await manager.send_message(target_sid, {
                'type': 'device_online',
                'session_id': target_sid,
                'data': {
                    'message': 'Device connected and API enabled - ready for configuration',
                    'ip_address': client_ip,
                    'identity': identity,
                    'timestamp': now_iso,
                }
            })

            logger.info(f'Provisioning notify: broadcast stage_complete + device_online to session {target_sid}')
            return {'success': True, 'session_id': target_sid, 'status': status}

        # No active session found: record a pending check-in for the IP so
        # future provisioning sessions will treat the device as already bootstrapped.
        if client_ip:
            ping_monitor.register_device_checkin(client_ip, {
                'identity': identity,
                'token_sub': getattr(token_data, 'sub', None),
                'timestamp': datetime.utcnow().isoformat()
            })

        logger.info(f'Provisioning notify: recorded pending check-in for IP {client_ip}')
        return {'success': True, 'session_id': None, 'note': 'pending_checkin_recorded'}

    except Exception as e:
        logger.error(f'Provisioning notify failed: {e}')
        raise HTTPException(status_code=500, detail='Failed to process provisioning notify')


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
