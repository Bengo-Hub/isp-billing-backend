"""Command generation and helpers for Codevertex MikroTik provisioning.

These helpers are imported by ProvisioningService to keep the service file
small and focused on orchestration. Functions here are stateless and accept
explicit parameters.
"""

from __future__ import annotations

import re as _re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provisioning import ProvisioningCommand, ProvisioningStatus, ServiceType
from .live_streaming import streaming_manager


# ============================================================================
# RouterOS Version Detection Helpers
# ============================================================================

def parse_routeros_version(version_string: str) -> Tuple[int, int, int]:
    """Parse a RouterOS version string into a (major, minor, patch) tuple.

    Examples:
        '7.18.2 (stable)' -> (7, 18, 2)
        '6.48.3'          -> (6, 48, 3)
        '7.1beta4'        -> (7, 1, 0)
    """
    if not version_string:
        return (7, 0, 0)  # Default to v7 if unknown
    m = _re.match(r'(\d+)\.(\d+)(?:\.(\d+))?', version_string.strip())
    if not m:
        return (7, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def is_v7_or_later(version_string: Optional[str]) -> bool:
    """Check if a RouterOS version is 7.x or later.

    Returns True if version is 7+ or if version_string is None/empty
    (default to v7 since it's the current standard).
    """
    if not version_string:
        return True
    major, _, _ = parse_routeros_version(version_string)
    return major >= 7


def load_command_templates() -> Dict[str, Dict[str, Any]]:
    return {
        "connection": {
            "system_info": "/system/resource/print",
            "identity_check": "/system/identity/print",
            "interface_list": "/interface/print",
            "ip_address_list": "/ip/address/print",
            "version_check": "/system/package/print where name=system",
        },
        "security": {
            "disable_default_services": [
                "/ip/service/set telnet disabled=yes",
                "/ip/service/set ftp disabled=yes",
                "/ip/service/set www disabled=yes",
                "/ip/service/set ssh port=2222",
            ],
            # IMPORTANT: Firewall rules are intentionally PERMISSIVE to avoid lockout
            # The DROP-ALL rule has been REMOVED because it can cause management lockout
            # if rules get applied out of order during retries/reconnections.
            # Admins should manually configure restrictive firewall rules after provisioning.
            "create_firewall_rules": [
                # Allow established connections (safe, always needed)
                "/ip/firewall/filter/add chain=input action=accept connection-state=established,related comment=codevertex-allow-established",
                # Allow ICMP for ping/diagnostics
                "/ip/firewall/filter/add chain=input action=accept protocol=icmp comment=codevertex-allow-icmp",
                # Allow API access (8728) from management network
                "/ip/firewall/filter/add chain=input action=accept dst-port=8728 protocol=tcp src-address={management_ip} comment=codevertex-allow-api",
                # Allow WinBox (8291) for emergency access
                "/ip/firewall/filter/add chain=input action=accept dst-port=8291 protocol=tcp comment=codevertex-allow-winbox",
                # NOTE: No DROP rule - admin should add restrictive rules manually
            ],
        },
    }


def calculate_network_config(subnet_address: str, cidr: int) -> Dict[str, str]:
    """Calculate network configuration from subnet address and CIDR.

    Args:
        subnet_address: Base subnet address (e.g., "172.31.0.0")
        cidr: CIDR notation (e.g., 16)

    Returns:
        Dict with gateway, pool_start, pool_end, network
    """
    parts = subnet_address.split(".")

    if cidr == 16:
        # /16 = 65534 hosts
        gateway = f"{parts[0]}.{parts[1]}.0.1"
        pool_start = f"{parts[0]}.{parts[1]}.0.2"
        pool_end = f"{parts[0]}.{parts[1]}.255.254"
    elif cidr == 22:
        # /22 = 1022 hosts
        gateway = f"{parts[0]}.{parts[1]}.{parts[2]}.1"
        pool_start = f"{parts[0]}.{parts[1]}.{parts[2]}.2"
        pool_end = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 3}.254"
    elif cidr == 23:
        # /23 = 510 hosts
        gateway = f"{parts[0]}.{parts[1]}.{parts[2]}.1"
        pool_start = f"{parts[0]}.{parts[1]}.{parts[2]}.2"
        pool_end = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}.254"
    else:
        # /24 = 254 hosts (default)
        gateway = f"{parts[0]}.{parts[1]}.{parts[2]}.1"
        pool_start = f"{parts[0]}.{parts[1]}.{parts[2]}.2"
        pool_end = f"{parts[0]}.{parts[1]}.{parts[2]}.254"

    return {
        "gateway": gateway,
        "pool_start": pool_start,
        "pool_end": pool_end,
        "network": f"{subnet_address}/{cidr}",
    }


def filter_wan_from_bridge_ports(
    ports: List[str],
    wan_interface: str,
    logger=None
) -> Tuple[List[str], bool]:
    """Filter out WAN interface from bridge ports to prevent network lockout.

    CRITICAL SAFEGUARD: Adding the WAN interface to a bridge will cause loss of
    IP-based management access to the router. This function ensures the WAN
    interface is NEVER included in bridge ports.

    Args:
        ports: List of interface names to add to bridge
        wan_interface: The WAN interface name (e.g., "ether1")
        logger: Optional logger for warnings

    Returns:
        Tuple of (filtered_ports, was_wan_filtered)
    """
    wan_interface_lower = wan_interface.lower().strip()
    filtered_ports = []
    was_wan_filtered = False

    for port in ports:
        port_lower = port.lower().strip()
        # Check if this port matches the WAN interface
        if port_lower == wan_interface_lower:
            was_wan_filtered = True
            if logger:
                logger.warning(
                    f"SECURITY: Blocked attempt to add WAN interface '{port}' to bridge. "
                    f"This would cause loss of management access."
                )
        else:
            filtered_ports.append(port)

    return filtered_ports, was_wan_filtered


def generate_configuration_commands(
    config: Dict[str, Any], service_type: ServiceType,
    routeros_version: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Generate MikroTik configuration commands for basic network setup.

    This includes:
    - System identity
    - Bridge creation and port assignment
    - IP address assignment (gateway)
    - IP pool creation
    - DHCP server configuration
    - DNS configuration
    - NAT/Masquerade for internet access

    IMPORTANT: WAN interface is automatically excluded from bridge ports to prevent
    loss of management access. See filter_wan_from_bridge_ports().
    """
    commands: List[Dict[str, Any]] = []

    # Calculate network config from subnet/CIDR if provided
    subnet_address = config.get("subnet_address", "172.31.0.0")
    cidr = int(config.get("cidr", 16))
    net_config = calculate_network_config(subnet_address, cidr)

    # Use calculated values or config overrides
    gateway = config.get("gateway", net_config["gateway"])
    pool_start = config.get("ip_pool_start", net_config["pool_start"])
    pool_end = config.get("ip_pool_end", net_config["pool_end"])
    pool_name = config.get("pool_name", "codevertex-pool")
    bridge_name = config.get("bridge_name", "codevertex-bridge")

    # Get WAN interface - critical for safeguard
    wan_interface = config.get("wan_interface", "ether1")

    # Set system identity
    identity = config.get("identity") or config.get("router_identity")
    if identity:
        commands.append(
            {
                "type": "api_call",
                "command": f"/system/identity/set name={identity}",
                "description": "Setting system identity",
                "critical": False,
            }
        )

    # Configure NTP for time synchronization
    # This ensures router time is accurate for logs, certificates, and scheduling
    _is_v7 = is_v7_or_later(routeros_version)
    ntp_servers = config.get("ntp_servers", ["time.cloudflare.com", "time.google.com"])
    if isinstance(ntp_servers, list) and len(ntp_servers) > 0:
        if _is_v7:
            # RouterOS v7: uses 'servers=' parameter (comma-separated)
            commands.append(
                {
                    "type": "api_call",
                    "command": f"/system/ntp/client/set enabled=yes servers={','.join(ntp_servers)}",
                    "description": "Configuring NTP time synchronization (v7)",
                    "critical": False,
                }
            )
        else:
            # RouterOS v6: uses 'primary-ntp=' and 'secondary-ntp=' parameters
            primary = ntp_servers[0] if len(ntp_servers) > 0 else "time.cloudflare.com"
            secondary = ntp_servers[1] if len(ntp_servers) > 1 else "time.google.com"
            commands.append(
                {
                    "type": "api_call",
                    "command": f"/system/ntp/client/set enabled=yes primary-ntp={primary} secondary-ntp={secondary}",
                    "description": "Configuring NTP time synchronization (v6)",
                    "critical": False,
                }
            )

    # Set timezone (tenant-configured; default Africa/Nairobi for Kenya — EAT UTC+3).
    # `or` (not just .get default) so an empty-string config value still falls back.
    timezone = config.get("timezone") or "Africa/Nairobi"
    if _is_v7:
        # RouterOS v7: IANA timezone database names
        commands.append(
            {
                "type": "api_call",
                "command": f"/system/clock/set time-zone-name={timezone}",
                "description": f"Setting timezone to {timezone} (v7)",
                "critical": False,
            }
        )
    else:
        # RouterOS v6: Use auto-detect (v6 doesn't support all IANA names reliably)
        commands.append(
            {
                "type": "api_call",
                "command": "/system/clock/set time-zone-autodetect=yes",
                "description": "Enabling timezone auto-detect (v6)",
                "critical": False,
            }
        )

    # =========================================================================
    # CLEAN SLATE — remove any prior codevertex-* config (idempotent reprovision)
    # =========================================================================
    # Clear the PREVIOUS run's service objects first so re-adds never hit
    # "already exists" and a reprovision (e.g. to add ether2) starts from a known
    # state. Every removal is on-error-guarded (a missing object is a no-op) and
    # scoped to codevertex service objects by name/comment. The management-allow
    # firewall rules (comment "codevertex-allow-*") are deliberately NOT removed
    # so management access is never even briefly weakened. Default bridge, WAN
    # and the management IP are never touched. Order: dependents before deps.
    _cleanup_commands = [
        # Match by interface, not name: the hotspot server name varies (e.g.
        # "ISP-Hotspot" from service-config enrichment), but it is always bound to
        # codevertex-bridge. Removing it first also frees the bridge so it can be
        # removed + re-added below without an "interface in use" error.
        ("Clearing previous hotspot server", ':do { /ip/hotspot/remove [find interface=codevertex-bridge] } on-error={}'),
        ("Clearing previous hotspot profile", ":do { /ip/hotspot/profile/remove [find name=codevertex-hsprof] } on-error={}"),
        ("Clearing previous hotspot ip-binding", ':do { /ip/hotspot/ip-binding/remove [find comment~"codevertex-gateway-bypass"] } on-error={}'),
        # PPPoE (service_type=both): remove the server + profile + secrets BEFORE
        # the pool/bridge they depend on, so a re-run does not abort the whole
        # import with "already have ... pppoe" / "in use" on the critical re-adds.
        ("Clearing previous PPPoE server", ':do { /interface/pppoe-server/server/remove [find service-name~"codevertex"] } on-error={}'),
        ("Clearing previous PPP profile", ':do { /ppp/profile/remove [find name~"codevertex"] } on-error={}'),
        ("Clearing previous PPP secrets", ':do { /ppp/secret/remove [find comment~"codevertex"] } on-error={}'),
        ("Clearing previous walled-garden hosts", ':do { /ip/hotspot/walled-garden/remove [find comment~"codevertex-portal"] } on-error={}'),
        ("Clearing previous walled-garden IPs", ':do { /ip/hotspot/walled-garden/ip/remove [find comment~"codevertex-portal"] } on-error={}'),
        ("Clearing previous DHCP server", ":do { /ip/dhcp-server/remove [find name=codevertex-dhcp] } on-error={}"),
        ("Clearing previous DHCP network", ':do { /ip/dhcp-server/network/remove [find comment~"codevertex-dhcp-network"] } on-error={}'),
        ("Clearing previous IP pool", ":do { /ip/pool/remove [find name=codevertex-pool] } on-error={}"),
        ("Clearing previous captive DNS entries", ':do { /ip/dns/static/remove [find comment~"codevertex-captive-portal-detection"] } on-error={}'),
        ("Clearing previous DNS-redirect NAT", ':do { /ip/firewall/nat/remove [find comment~"codevertex-dns-redirect"] } on-error={}'),
        ("Clearing previous masquerade NAT", ':do { /ip/firewall/nat/remove [find comment~"codevertex-masquerade"] } on-error={}'),
        ("Clearing previous DoH-block filter", ':do { /ip/firewall/filter/remove [find comment~"codevertex-block-doh"] } on-error={}'),
        ("Clearing previous anti-sharing rules", ':do { /ip/firewall/mangle/remove [find comment~"codevertex-anti-sharing"] } on-error={}'),
        ("Clearing previous anti-sharing drop", ':do { /ip/firewall/filter/remove [find comment~"codevertex-anti-sharing"] } on-error={}'),
        ("Clearing previous bridge IP", ":do { /ip/address/remove [find interface=codevertex-bridge] } on-error={}"),
        ("Clearing previous bridge", ":do { /interface/bridge/remove [find name=codevertex-bridge] } on-error={}"),
    ]
    for _desc, _cmd in _cleanup_commands:
        commands.append({
            "type": "api_call",
            "command": _cmd,
            "description": _desc,
            "critical": False,
        })

    # =========================================================================
    # CLEAN UP DEFAULT BRIDGE (prevent port conflicts)
    # =========================================================================
    # SAFETY: do NOT strip or disable the default 'bridge'. On many routers the
    # management IP and WiFi live on the default bridge, so disabling it (or
    # yanking all its ports) would lock the operator out. A port can only live
    # in one bridge, so we instead move ONLY the selected customer ports into
    # codevertex-bridge individually (each port is removed from whatever bridge
    # it currently sits in, just before it's added below). Management ports are
    # never touched.

    # Bridge configuration - required for all service types
    commands.append(
        {
            "type": "api_call",
            "command": f"/interface/bridge/add name={bridge_name}",
            "description": f"Ensuring bridge {bridge_name} exists",
            "critical": True,
            "rollback": f"/interface/bridge/remove [find name={bridge_name}]",
        }
    )

    # Add ports to bridge - with WAN interface safeguard
    ports = config.get("bridge_ports", [])
    if not isinstance(ports, list) or not ports:
        ports = [config.get("interface", "ether2")]

    # CRITICAL SAFEGUARD: Filter out WAN interface from bridge ports
    # Adding WAN to bridge will cause loss of management access
    import logging
    _logger = logging.getLogger(__name__)
    ports, wan_was_filtered = filter_wan_from_bridge_ports(ports, wan_interface, _logger)

    if wan_was_filtered:
        # Add a warning command that will be logged but not cause failure
        commands.append(
            {
                "type": "api_call",
                "command": "/system/identity/print",  # Harmless command to attach warning
                "description": f"[WARN] WAN interface '{wan_interface}' was excluded from bridge ports to prevent network lockout",
                "critical": False,
            }
        )

    for port in ports:
        commands.append(
            {
                "type": "api_call",
                "command": f":do {{ /interface/bridge/port/remove [find interface={port}] }} on-error={{}}; /interface/bridge/port/add interface={port} bridge={bridge_name} hw=no",
                "description": f"Adding port {port} to bridge (hw=no: HW-offload bypasses the CPU, so the hotspot can't register clients as hosts → no captive intercept)",
                "critical": True,
                "rollback": f"/interface/bridge/port/remove [find interface={port}]",
            }
        )

    # Assign gateway IP address to bridge
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/address/add address={gateway}/{cidr} interface={bridge_name}",
            "description": f"Assigning gateway IP {gateway}/{cidr} to bridge",
            "critical": True,
            "rollback": f"/ip/address/remove [find address={gateway}/{cidr}]",
        }
    )

    # Create IP pool for DHCP
    ip_range = f"{pool_start}-{pool_end}"
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/pool/add name={pool_name} ranges={ip_range}",
            "description": f"Creating IP pool {pool_name}",
            "critical": True,
            "rollback": f"/ip/pool/remove [find name={pool_name}]",
        }
    )

    # Configure DNS servers
    dns_servers = config.get("dns_servers", ["8.8.8.8", "8.8.4.4"])
    if isinstance(dns_servers, list):
        dns_list = ",".join(dns_servers)
    else:
        dns_list = dns_servers
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/dns/set servers={dns_list} allow-remote-requests=yes",
            "description": "Configuring DNS servers",
            "critical": False,
        }
    )

    # DHCP Server configuration
    dhcp_server_name = config.get("dhcp_server_name", "codevertex-dhcp")
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/dhcp-server/add name={dhcp_server_name} interface={bridge_name} address-pool={pool_name} disabled=no",
            "description": f"Creating DHCP server on {bridge_name}",
            "critical": True,
            "rollback": f"/ip/dhcp-server/remove [find name={dhcp_server_name}]",
        }
    )

    # DHCP Network configuration
    # IMPORTANT: Use gateway IP as DNS server for DHCP clients (NOT external DNS like 8.8.8.8)
    # This ensures clients query the router first, which serves DNS static entries for
    # captive portal detection. The router then forwards non-static queries to upstream DNS.
    # Without this, clients query external DNS directly, bypassing captive portal detection.
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/dhcp-server/network/add address={subnet_address}/{cidr} gateway={gateway} dns-server={gateway} comment=codevertex-dhcp-network",
            "description": "Configuring DHCP network parameters",
            "critical": True,
        }
    )

    # NAT Masquerade for internet access (assumes ether1 is WAN)
    wan_interface = config.get("wan_interface", "ether1")
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/firewall/nat/add chain=srcnat action=masquerade out-interface={wan_interface} comment=codevertex-masquerade",
            "description": f"Enabling NAT masquerade on {wan_interface}",
            "critical": True,
        }
    )

    return commands


def generate_hotspot_commands(config: Dict[str, Any], routeros_version: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate MikroTik hotspot configuration commands.

    Creates hotspot on the bridge interface with external captive portal redirect.
    The hotspot redirects unauthenticated users to the ISP billing frontend
    captive portal (/portal/{org}/buy-packages) instead of MikroTik's built-in login.

    IMPORTANT: This configures an EXTERNAL captive portal workflow:
    1. User connects to hotspot WiFi/ethernet
    2. User opens any HTTP page -> redirected to external captive portal
    3. User purchases package on captive portal
    4. Backend authorizes user via MikroTik API (adds hotspot user)
    5. User gets internet access
    """
    commands: List[Dict[str, Any]] = []
    hotspot_name = config.get("hotspot_name", "codevertex-hotspot")
    # Use bridge interface for hotspot (not single port)
    bridge_name = config.get("bridge_name", "codevertex-bridge")
    pool_name = config.get("pool_name", "codevertex-pool")

    # Calculate gateway from config
    subnet_address = config.get("subnet_address", "172.31.0.0")
    cidr = int(config.get("cidr", 16))
    net_config = calculate_network_config(subnet_address, cidr)
    gateway = config.get("gateway", net_config["gateway"])

    # Hotspot profile settings
    profile_name = config.get("hotspot_profile", "codevertex-hsprof")
    dns_name = config.get("hotspot_dns_name", "hotspot.local")

    # External captive portal URL - this is where users are redirected
    # Format: http(s)://billing-server/portal/{org}/buy-packages
    # The captive portal URL should be configured in organization settings
    captive_portal_url = config.get("captive_portal_url", "")
    org_slug = config.get("organization_slug", "default")

    # If no explicit captive portal URL, construct from billing server
    if not captive_portal_url:
        billing_server = config.get("billing_server_url", "")
        if billing_server:
            # Remove trailing slash and construct portal URL
            # Format: /buy/{orgSlug} (matches frontend routing)
            billing_server = billing_server.rstrip("/")
            captive_portal_url = f"{billing_server}/buy/{org_slug}"

    # CRITICAL: Enable FTP service for template upload
    # MikroTik routers have FTP disabled by default
    # We need FTP to upload custom hotspot templates (login.html, alogin.html)
    commands.append(
        {
            "type": "api_call",
            "command": "/ip/service/set ftp disabled=no",
            "description": "Enabling FTP service for template upload",
            "critical": False,
        }
    )

    # =========================================================================
    # RFC 7710/8910 CAPTIVE PORTAL API SUPPORT (Modern devices: Android 11+, iOS 14+)
    # =========================================================================
    # Modern devices detect captive portals via DHCP Option 114 (RFC 7710/8910).
    # MikroTik sends this option AUTOMATICALLY when BOTH conditions are met:
    #   1. A dns-name is set on the hotspot profile (e.g., "hotspot.local")
    #   2. A valid SSL certificate is assigned to the hotspot profile
    # Without the SSL cert, DHCP Option 114 is NOT sent and modern devices
    # won't show the "Sign in to Wi-Fi network" popup via the modern API path.
    #
    # This is a non-critical step: if certificate creation fails, the hotspot
    # still works via legacy HTTP interception + DNS static entries.
    # =========================================================================
    # Step 1: Create a self-signed CA certificate (needed to sign server cert)
    ca_cert_name = config.get("hotspot_ca_cert_name", "codevertex-ca")
    cert_name = config.get("hotspot_cert_name", "codevertex-hotspot-cert")
    commands.append(
        {
            "type": "api_call",
            "command": f"/certificate/add name={ca_cert_name} common-name=codevertex-ca key-usage=key-cert-sign,crl-sign key-size=2048 days-valid=3650",
            "description": "Creating CA certificate for hotspot SSL",
            "critical": False,
        }
    )
    commands.append(
        {
            "type": "api_call",
            "command": f"/certificate/sign [find name={ca_cert_name}]",
            "description": "Self-signing CA certificate",
            "critical": False,
        }
    )
    # Step 2: Create server certificate and sign with our CA
    commands.append(
        {
            "type": "api_call",
            "command": f"/certificate/add name={cert_name} common-name={dns_name} key-size=2048 days-valid=3650",
            "description": "Creating SSL certificate for hotspot captive portal",
            "critical": False,
        }
    )
    commands.append(
        {
            "type": "api_call",
            "command": f"/certificate/sign [find name={cert_name}] ca={ca_cert_name}",
            "description": "Signing hotspot certificate with CA",
            "critical": False,
        }
    )

    # Create hotspot profile for external captive portal
    # login-by methods — HTTP ONLY (no https):
    #   - http-pap: Plain-text auth over HTTP (our custom login.html + the buy page
    #     POST credentials in clear, so http-pap MUST be present and is listed first)
    #   - http-chap: Challenge-response auth over HTTP (legacy devices that render
    #     MikroTik's built-in JS login form)
    #   - mac-cookie: Server-side MAC-to-credential mapping for auto-re-login
    # IMPORTANT: `https` is intentionally OMITTED. With `https` + a SELF-SIGNED cert,
    # MikroTik redirects every intercepted HTTP probe to https://<dns-name>/login,
    # whose untrusted TLS handshake fails on Android/Chrome — the captive popup never
    # appears (device reports "no internet"), neverssl returns ERR_CONNECTION_CLOSED,
    # and $(link-login-only) resolves to an unreachable https://hotspot.local URL.
    # RFC 7710 DHCP Option 114 needs a *publicly-trusted* cert to help, which a
    # self-signed cert is not — so it only hurts here. Re-enable https + Option 114
    # later only with a real (e.g. Let's Encrypt) certificate.
    # NOTE: html-directory is NOT set here initially. It defaults to MikroTik built-in
    # templates. After custom templates are uploaded via FTP, the service layer sets
    # html-directory=hotspot to use them. This ensures captive portal works even if
    # template upload fails (falls back to built-in login page).
    # use-radius=no: Authenticate locally/via API, not RADIUS
    # http-cookie-lifetime=1d: Browser cookie keeps users logged in for 1 day
    # Note: HTTP proxy/interception is enabled automatically by MikroTik hotspot
    profile_cmd = (
        f"/ip/hotspot/profile/add name={profile_name} "
        f"hotspot-address={gateway} dns-name={dns_name} "
        f"use-radius=no "
        f"login-by=http-pap,http-chap,mac-cookie "
        f"http-cookie-lifetime=1d "
        f"split-user-domain=no"
    )

    # NOTE: MikroTik doesn't have a 'login-url' parameter
    # To redirect to external captive portal, customize the login.html template
    # For now, we use walled garden to allow access to the captive portal
    # The frontend can detect captive portal and show the buy packages page

    commands.append(
        {
            "type": "api_call",
            "command": profile_cmd,
            "description": f"Creating hotspot profile {profile_name}",
            "critical": True,
        }
    )

    # SSL certificate is intentionally NOT assigned to the profile.
    # Assigning a SELF-SIGNED cert turns on RFC 7710 DHCP Option 114 pointing at
    # https://<dns-name>/... — but the untrusted cert makes Android/Chrome fail the
    # captive check ("no internet", no popup) and intercepts post-auth HTTPS with a
    # cert error. The cert objects are still created above so a real (trusted) cert
    # can be assigned later; until then we run an HTTP-only captive portal.
    # Defensive: clear any cert left over from a previous (https) provisioning.
    commands.append(
        {
            "type": "api_call",
            "command": f':do {{ /ip/hotspot/profile/set [find name={profile_name}] ssl-certificate=none }} on-error={{}}',
            "description": "Ensuring hotspot profile has NO ssl-certificate (HTTP-only captive)",
            "critical": False,
        }
    )

    # Create hotspot on bridge interface
    # addresses-per-mac=1: Limit one IP per MAC address to prevent IP sharing
    # idle-timeout=5m: Disconnect after 5 minutes of inactivity (anti-sharing)
    # keepalive-timeout=none: Don't use keepalive (reduces overhead)
    # address-list=none: No specific address list
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/hotspot/add name={hotspot_name} interface={bridge_name} address-pool={pool_name} profile={profile_name} addresses-per-mac=1 idle-timeout=5m keepalive-timeout=none disabled=no",
            "description": f"Creating hotspot {hotspot_name} on {bridge_name}",
            "critical": True,
        }
    )

    # =========================================================================
    # CAPTIVE PORTAL REDIRECT — install + activate the custom login page
    # =========================================================================
    # WITHOUT this the hotspot serves MikroTik's BUILT-IN login FORM (a
    # username/password page), so unauthenticated clients are never redirected to
    # the external buy-package portal and iOS/Android never pop the captive page.
    # The router (NOT a hotspot client) fetches the redirecting login.html /
    # alogin.html from the backend over its WAN, then html-directory=hotspot
    # activates them. Best-effort: if a fetch fails the hotspot still gates
    # traffic, it just falls back to the built-in page.
    login_template_url = config.get("login_template_url")
    alogin_template_url = config.get("alogin_template_url")
    if login_template_url:
        commands.append(
            {
                "type": "api_call",
                "command": f':do {{ /tool/fetch url="{login_template_url}" dst-path=hotspot/login.html check-certificate=no }} on-error={{}}',
                "description": "Installing captive-portal login.html (external-redirect page)",
                "critical": False,
            }
        )
    if alogin_template_url:
        commands.append(
            {
                "type": "api_call",
                "command": f':do {{ /tool/fetch url="{alogin_template_url}" dst-path=hotspot/alogin.html check-certificate=no }} on-error={{}}',
                "description": "Installing captive-portal alogin.html (post-auth page)",
                "critical": False,
            }
        )
    # Activate the custom templates (point the hotspot profile at the /hotspot dir).
    commands.append(
        {
            "type": "api_call",
            "command": f':do {{ /ip/hotspot/profile/set [find name={profile_name}] html-directory=hotspot }} on-error={{}}',
            "description": "Activating captive-portal templates (html-directory=hotspot)",
            "critical": False,
        }
    )

    # CRITICAL: Bypass the gateway IP from hotspot authentication
    # Without this, the router's own management traffic goes through the
    # hotspot, causing connectivity issues and preventing proper HTTP
    # interception for captive portal detection.
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/hotspot/ip-binding/add address={gateway} type=bypassed comment=codevertex-gateway-bypass",
            "description": f"Bypassing gateway {gateway} from hotspot authentication",
            "critical": False,
        }
    )

    # CRITICAL: Configure walled garden for external captive portal
    # Walled garden allows unauthenticated access to specific hosts/IPs
    # This is required so users can reach the captive portal before authentication

    # Default walled garden hosts for the captive portal
    walled_garden_hosts = list(config.get("walled_garden_hosts", []))

    # Auto-add billing server to walled garden if configured
    billing_server = config.get("billing_server_url", "")
    if billing_server:
        # Extract host from URL (e.g., "192.168.100.4" from "http://192.168.100.4:3000")
        import re
        match = re.search(r'https?://([^:/]+)', billing_server)
        if match:
            billing_host = match.group(1)
            if billing_host not in walled_garden_hosts:
                walled_garden_hosts.append(billing_host)

    # Add API server to walled garden (for package purchases)
    api_server = config.get("api_server_url", "")
    if api_server:
        match = re.search(r'https?://([^:/]+)', api_server)
        if match:
            api_host = match.group(1)
            if api_host not in walled_garden_hosts:
                walled_garden_hosts.append(api_host)

    # Add common payment gateways to walled garden (for online payments)
    payment_hosts = [
        "*.paystack.com",
        "*.paystack.co",
        "*.flutterwave.com",
        "*.mpesa.in",
        "*.safaricom.co.ke",
    ]
    walled_garden_hosts.extend(payment_hosts)

    # =========================================================================
    # CAPTIVE PORTAL DETECTION - DNS STATIC ENTRIES
    # =========================================================================
    # Each OS probes specific URLs over HTTP to detect captive portals.
    # If the probe gets the expected response (e.g., HTTP 204), the device
    # thinks it has internet access and WON'T show the captive portal popup.
    #
    # By resolving these probe domains to the hotspot gateway IP, the device's
    # probe request reaches the MikroTik, which intercepts it (since the user
    # is unauthenticated) and returns an HTTP 302 redirect to the login page.
    # The device sees "I didn't get the expected 204 - I'm behind a captive
    # portal" and shows the "Sign in to Wi-Fi" / "Tap to Connect" popup.
    #
    # IMPORTANT: TTL=5m ensures that after authentication, the client's DNS
    # cache expires quickly so it can resolve these domains normally again.
    # Without TTL, MikroTik uses default 1-day TTL which causes post-auth
    # connectivity issues (devices cache the fake DNS for 24 hours).
    #
    # IMPORTANT: Do NOT add these domains to the walled garden! If walled
    # garden allows access to probe domains, the device gets the expected
    # response and concludes it has full internet - popup NEVER appears.
    # =========================================================================

    captive_portal_detection_domains = [
        # --- Android / Google (probes /generate_204, expects HTTP 204) ---
        # Only the DEDICATED captive-probe hostnames are hijacked. Do NOT hijack
        # www.google.com / *.gstatic.com / clients*.google.com — those serve real
        # traffic, so pointing them at the gateway breaks Google for up to the DNS
        # TTL after the client authenticates (and throws a cert error during the
        # pre-auth redirect). connectivitycheck.* are used ONLY for portal probing.
        "connectivitycheck.gstatic.com",
        "connectivitycheck.android.com",

        # --- Apple iOS / macOS (probes /hotspot-detect.html, expects "Success") ---
        "captive.apple.com",
        "www.apple.com",
        "www.appleiphonecell.com",
        "www.airport.us",
        "www.ibook.info",
        "www.itools.info",
        "www.thinkdifferent.us",

        # --- Windows NCSI (probes /connecttest.txt, expects "Microsoft Connect Test") ---
        "www.msftconnecttest.com",
        "www.msftncsi.com",
        "ipv6.msftconnecttest.com",

        # --- Firefox (probes /canonical.html) ---
        "detectportal.firefox.com",

        # --- Linux / GNOME NetworkManager ---
        "nmcheck.gnome.org",

        # --- Amazon Kindle ---
        "spectrum.s3.amazonaws.com",
    ]

    # Add DNS static entries pointing to hotspot gateway with short TTL
    for domain in captive_portal_detection_domains:
        commands.append(
            {
                "type": "api_call",
                "command": f'/ip/dns/static/add name="{domain}" address={gateway} ttl=1m comment=codevertex-captive-portal-detection',
                "description": f"DNS static entry for captive portal detection: {domain}",
                "critical": False,
            }
        )

    # =========================================================================
    # DNS REDIRECT NAT RULES - Force ALL DNS traffic through the router
    # =========================================================================
    # Some devices use hardcoded DNS servers (e.g., 8.8.8.8, 1.1.1.1) or
    # DNS-over-HTTPS, bypassing the router's DNS static entries entirely.
    # These NAT rules redirect ANY DNS traffic on the bridge interface to
    # the router's own DNS server, ensuring captive portal detection domains
    # are always resolved via our static entries.
    #
    # Scoped to bridge interface only to avoid affecting WAN traffic.
    # =========================================================================
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/firewall/nat/add chain=dstnat action=redirect to-ports=53 protocol=udp dst-port=53 in-interface={bridge_name} comment=codevertex-dns-redirect",
            "description": "DNS redirect NAT rule (UDP) to force DNS through router",
            "critical": False,
        }
    )
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/firewall/nat/add chain=dstnat action=redirect to-ports=53 protocol=tcp dst-port=53 in-interface={bridge_name} comment=codevertex-dns-redirect",
            "description": "DNS redirect NAT rule (TCP) to force DNS through router",
            "critical": False,
        }
    )

    # =========================================================================
    # BLOCK DNS-OVER-HTTPS (DoH) FOR UNAUTHENTICATED HOTSPOT USERS
    # =========================================================================
    # Modern browsers (Chrome, Firefox, Edge) and Windows 11 use DNS-over-HTTPS
    # by default, sending DNS queries over port 443 to providers like Google
    # (8.8.8.8), Cloudflare (1.1.1.1), etc. This completely bypasses our DNS
    # redirect NAT rules (which only capture port 53), meaning captive portal
    # detection domains resolve normally and the device never shows the
    # "Sign in to network" popup.
    #
    # Solution: Block HTTPS traffic to known DoH providers on the bridge
    # interface. This forces browsers to fall back to regular DNS (port 53),
    # which gets redirected to the router and serves our static entries.
    # The MikroTik hotspot will remove these blocks once the user authenticates
    # because authenticated traffic bypasses the hotspot firewall rules.
    # =========================================================================
    doh_providers = [
        ("8.8.8.8", "google-dns-1"),
        ("8.8.4.4", "google-dns-2"),
        ("1.1.1.1", "cloudflare-dns-1"),
        ("1.0.0.1", "cloudflare-dns-2"),
        ("9.9.9.9", "quad9-dns"),
        ("149.112.112.112", "quad9-dns-2"),
        ("208.67.222.222", "opendns-1"),
        ("208.67.220.220", "opendns-2"),
    ]
    for ip, comment in doh_providers:
        commands.append(
            {
                "type": "api_call",
                "command": f"/ip/firewall/address-list/add list=codevertex-doh-providers address={ip} comment={comment}",
                "description": f"Adding DoH provider {ip} ({comment}) to address list",
                "critical": False,
            }
        )

    # Block port 443 to DoH providers on the bridge interface.
    # The hotspot's built-in firewall already blocks unauthenticated traffic,
    # but this explicit rule ensures DoH is blocked even if hotspot walled
    # garden rules accidentally allow HTTPS to these IPs.
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/firewall/filter/add chain=forward action=reject reject-with=icmp-network-unreachable dst-address-list=codevertex-doh-providers protocol=tcp dst-port=443 in-interface={bridge_name} comment=codevertex-block-doh",
            "description": "Blocking DNS-over-HTTPS to prevent captive portal bypass",
            "critical": False,
        }
    )

    # Add each walled garden entry
    for host in walled_garden_hosts:
        # Use dst-host for domain patterns, support wildcards
        commands.append(
            {
                "type": "api_call",
                "command": f'/ip/hotspot/walled-garden/add dst-host="{host}" action=allow comment=codevertex-portal',
                "description": f"Allow unauthenticated access to {host}",
                "critical": False,
            }
        )

    # Also add IP-based walled garden entries for local network access
    # This ensures the captive portal server is reachable by IP
    walled_garden_ips = config.get("walled_garden_ips", [])
    if billing_server:
        match = re.search(r'https?://([0-9.]+)', billing_server)
        if match:
            billing_ip = match.group(1)
            if billing_ip not in walled_garden_ips:
                walled_garden_ips.append(billing_ip)

    for ip in walled_garden_ips:
        commands.append(
            {
                "type": "api_call",
                "command": f"/ip/hotspot/walled-garden/ip/add dst-address={ip} action=accept comment=codevertex-portal",
                "description": f"Allow unauthenticated access to IP {ip}",
                "critical": False,
            }
        )

    # Check all naming variations for anti-sharing flag
    enable_anti_sharing = (
        config.get("enable_anti_sharing") or
        config.get("enableAntiSharing") or
        config.get("enable_hotspot_anti_sharing") or
        False
    )
    if enable_anti_sharing:
        # Configure hotspot server idle-timeout
        # Note: session-timeout and shared-users should be set on user profiles or individual users,
        # NOT on the hotspot profile itself. Only idle-timeout can be set on the hotspot server.
        commands.append(
            {
                "type": "api_call",
                "command": f"/ip/hotspot/set {hotspot_name} idle-timeout=5m",
                "description": "Configure hotspot idle timeout for anti-sharing",
                "critical": False,
            }
        )
        # TTL modification rules to detect and prevent connection sharing
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/firewall/mangle/add chain=forward action=change-ttl new-ttl=set:64 passthrough=yes ttl=equal:65 protocol=tcp dst-port=80,443,53 comment=codevertex-anti-sharing",
                "description": "Anti-sharing TTL rule for TCP (HTTP/HTTPS/DNS)",
                "critical": False,
            }
        )
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/firewall/mangle/add chain=forward action=change-ttl new-ttl=set:64 passthrough=yes ttl=equal:65 protocol=udp dst-port=53,67,68 comment=codevertex-anti-sharing",
                "description": "Anti-sharing TTL rule for UDP (DNS/DHCP)",
                "critical": False,
            }
        )
        # Drop packets with suspicious TTL values
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/firewall/filter/add chain=forward action=drop ttl=equal:1 comment=codevertex-anti-sharing",
                "description": "Block suspicious low-TTL packets",
                "critical": False,
            }
        )

    return commands


def generate_pppoe_commands(config: Dict[str, Any], routeros_version: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate MikroTik PPPoE server configuration commands.

    Creates PPPoE server on the bridge interface with proper profile settings.
    """
    commands: List[Dict[str, Any]] = []
    service_name = config.get("service_name", "codevertex-pppoe")
    # Use bridge interface for PPPoE (not single port)
    bridge_name = config.get("bridge_name", "codevertex-bridge")
    profile_name = config.get("ppp_profile_name", "codevertex-pppoe-profile")
    pool_name = config.get("pool_name", "codevertex-pool")

    # Calculate gateway from config
    subnet_address = config.get("subnet_address", "172.31.0.0")
    cidr = int(config.get("cidr", 16))
    net_config = calculate_network_config(subnet_address, cidr)
    local_address = config.get("gateway", net_config["gateway"])

    # Create PPP profile with proper settings
    commands.append(
        {
            "type": "api_call",
            "command": f"/ppp/profile/add name={profile_name} local-address={local_address} remote-address={pool_name} dns-server={local_address}",
            "description": f"Creating PPP profile {profile_name}",
            "critical": True,
        }
    )

    # Enable PPPoE server on bridge interface
    commands.append(
        {
            "type": "api_call",
            "command": f"/interface/pppoe-server/server/add service-name={service_name} interface={bridge_name} default-profile={profile_name} disabled=no",
            "description": f"Enabling PPPoE server {service_name} on {bridge_name}",
            "critical": True,
        }
    )

    return commands


async def execute_command_with_retry(
    db: AsyncSession,
    retry_delays: List[int],
    logger,
    session,
    client,
    connection,
    command_data: Dict[str, Any],
    router_info: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Any]:
    """Execute a command with retry logic using new client pattern.

    Args:
        db: Database session
        retry_delays: List of delays in seconds for retries
        logger: Logger instance
        session: Provisioning session
        client: MikroTik client
        connection: Current router connection
        command_data: Command configuration dict
        router_info: Router connection info for reconnection (ip_address, username, password, port)

    Returns:
        tuple: (success: bool, connection: updated connection object)
    """
    command = ProvisioningCommand(
        session_id=session.id,
        command_type=command_data["type"],
        command=command_data["command"],
        description=command_data.get("description", ""),
        execution_order=command_data.get("order", 0),
        is_critical=command_data.get("critical", True),
        rollback_command=command_data.get("rollback", None),
    )
    db.add(command)
    await db.commit()

    max_retries = command.max_retries
    current_connection = connection

    # Get session_id for streaming logs
    session_id = getattr(session, 'session_id', None)

    for attempt in range(max_retries + 1):
        try:
            command.executed_at = datetime.utcnow()
            command.status = ProvisioningStatus.IN_PROGRESS
            start_time = datetime.utcnow()

            # Stream command execution start
            if session_id:
                await streaming_manager.log_provisioning_step(
                    session_id,
                    "command",
                    f"Executing: {command_data.get('description', command_data['command'][:50])}...",
                    "info"
                )

            if command_data["type"] == "api_call":
                result = await client.execute_command(current_connection, command_data["command"])
            else:
                result = await client.execute_script(current_connection, command_data["command"])
            command.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            command.output = str(result) if result else None
            command.success = True
            command.status = ProvisioningStatus.COMPLETED
            await db.commit()

            # Stream success (using ASCII-safe symbols for Windows console compatibility)
            if session_id:
                await streaming_manager.log_provisioning_step(
                    session_id,
                    "command",
                    f"[OK] Completed: {command_data.get('description', 'Command')}",
                    "success"
                )

            return True, current_connection
        except Exception as e:  # noqa: BLE001
            error_str = str(e).lower()

            # Check for "already exists" errors - treat as success (idempotent)
            # RouterOS returns various error patterns for existing resources:
            # - "failure: already have such item"
            # - "failure: pool with such name exists"
            # - "failure: already have bridge with such name"
            # - "failure: device already added as bridge port"
            is_already_exists_error = (
                ("already" in error_str and ("exists" in error_str or "have" in error_str or "item" in error_str or "added" in error_str))
                or ("with such name exists" in error_str)
                or ("such name already" in error_str)
                or ("already added" in error_str)
            )
            if is_already_exists_error:
                logger.info(f"Resource already exists (treating as success): {command_data['description']}")
                command.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
                command.output = "Resource already exists"
                command.success = True
                command.status = ProvisioningStatus.COMPLETED
                await db.commit()

                # Stream as info (not error since it's expected)
                if session_id:
                    await streaming_manager.log_provisioning_step(
                        session_id,
                        "command",
                        f"[SKIP] Resource already exists: {command_data.get('description', 'Command')}",
                        "info"
                    )

                return True, current_connection

            command.retry_count = attempt + 1
            command.error_message = str(e)
            command.success = False

            # Check for socket/connection errors that require reconnection
            is_socket_error = (
                isinstance(e, OSError) or
                "socket" in error_str or
                "connection" in error_str or
                "10038" in error_str or  # WinError 10038: not a socket
                "10054" in error_str or  # WinError 10054: connection reset
                "10053" in error_str or  # WinError 10053: connection aborted
                "broken pipe" in error_str or
                "timed out" in error_str
            )

            if attempt < max_retries:
                # wait with backoff
                from asyncio import sleep

                delay = retry_delays[min(attempt, len(retry_delays) - 1)]

                # Stream retry warning
                if session_id:
                    error_type = "connection" if is_socket_error else "command"
                    await streaming_manager.log_provisioning_step(
                        session_id,
                        "retry",
                        f"[WARN] {command_data.get('description', 'Command')} failed (attempt {attempt + 1}/{max_retries + 1}): {str(e)[:100]}",
                        "warning"
                    )

                # If socket error and we have router info, try to reconnect
                if is_socket_error and router_info:
                    logger.warning(f"Socket error detected, attempting to reconnect: {e}")

                    # Stream reconnection attempt
                    if session_id:
                        await streaming_manager.log_provisioning_step(
                            session_id,
                            "connection",
                            f"[RETRY] Connection lost. Reconnecting to {router_info['ip_address']}...",
                            "warning"
                        )

                    try:
                        # Disconnect old connection - try multiple times to ensure socket is closed
                        for _ in range(3):
                            try:
                                await client.disconnect(router_info["ip_address"], router_info.get("port", 8728))
                                break
                            except Exception:
                                await sleep(0.5)  # Brief pause between disconnect attempts

                        # Wait before reconnecting - use minimum 3 seconds for socket errors
                        # to allow the router's socket to fully close
                        reconnect_delay = max(delay, 3)
                        await sleep(reconnect_delay)

                        # Create fresh connection (now with connection verification built-in)
                        current_connection = await client.connect(
                            ip_address=router_info["ip_address"],
                            username=router_info["username"],
                            password=router_info["password"],
                            port=router_info.get("port", 8728)
                        )
                        logger.info(f"Successfully reconnected to router {router_info['ip_address']}")

                        # Stream reconnection success
                        if session_id:
                            await streaming_manager.log_provisioning_step(
                                session_id,
                                "connection",
                                f"[OK] Reconnected to {router_info['ip_address']}",
                                "success"
                            )

                    except Exception as reconnect_error:
                        logger.error(f"Failed to reconnect: {reconnect_error}")

                        # Stream reconnection failure
                        if session_id:
                            await streaming_manager.log_provisioning_step(
                                session_id,
                                "connection",
                                f"[FAIL] Reconnection failed: {str(reconnect_error)[:100]}",
                                "error"
                            )

                        await sleep(delay)
                else:
                    await sleep(delay)

                command.status = ProvisioningStatus.PENDING
            else:
                command.status = ProvisioningStatus.FAILED

                # Stream final failure
                if session_id:
                    await streaming_manager.log_provisioning_step(
                        session_id,
                        "error",
                        f"[FAIL] Failed after {max_retries + 1} attempts: {command_data.get('description', 'Command')} - {str(e)[:150]}",
                        "error"
                    )

            await db.commit()
    return False, current_connection


async def cleanup_existing_provisioning(client, connection, logger, session_id: Optional[str] = None) -> None:
    """Clean up any existing codevertex provisioning artifacts before fresh provisioning.

    This makes reprovisioning safe by removing:
    - Codevertex bridge and bridge ports
    - Codevertex IP pools
    - Codevertex DHCP servers
    - Codevertex firewall rules
    - Codevertex hotspot configs
    - Codevertex PPPoE configs

    IMPORTANT: This does NOT remove NAT masquerade or affect WAN connectivity.

    Note: Uses API-based cleanup (list -> filter -> remove by ID) instead of script
    syntax `[find ...]` which doesn't work via the RouterOS API.
    """
    if session_id:
        await streaming_manager.log_provisioning_step(
            session_id,
            "cleanup",
            "Cleaning up existing provisioning artifacts...",
            "info"
        )

    cleaned_items = []

    async def remove_by_filter(resource_path: str, filter_key: str, filter_contains: str, item_name: str):
        """Remove items where filter_key contains filter_contains string."""
        try:
            # Get all items from the resource
            items = await client.execute_command(connection, resource_path, "get")
            if not items:
                return False

            removed_any = False
            for item in items:
                item_id = item.get('id') or item.get('.id')
                if not item_id:
                    continue

                # Check if the filter matches (case-insensitive contains check)
                value = item.get(filter_key, '')
                if value and filter_contains.lower() in str(value).lower():
                    try:
                        await client.execute_command(connection, resource_path, "remove", id=item_id)
                        removed_any = True
                        logger.debug(f"Removed {item_name}: {item.get('name', item_id)}")
                    except Exception as remove_error:
                        logger.debug(f"Failed to remove {item_name} {item_id}: {remove_error}")

            return removed_any
        except Exception as e:
            logger.debug(f"Cleanup {item_name}: {e}")
            return False

    # Cleanup in order of dependencies (remove dependents first)

    # 0a. DNS static entries for captive portal detection (independent, clean early)
    if await remove_by_filter('/ip/dns/static', 'comment', 'codevertex', 'DNS static entries'):
        cleaned_items.append('DNS static entries')

    # 0b. NAT redirect rules for DNS forcing (by comment)
    if await remove_by_filter('/ip/firewall/nat', 'comment', 'codevertex', 'NAT rules'):
        cleaned_items.append('NAT rules')

    # 0c. Walled garden entries (must be removed before hotspot)
    if await remove_by_filter('/ip/hotspot/walled-garden', 'comment', 'codevertex', 'walled garden'):
        cleaned_items.append('walled garden entries')

    # 0d. Walled garden IP entries
    if await remove_by_filter('/ip/hotspot/walled-garden/ip', 'comment', 'codevertex', 'walled garden IP'):
        cleaned_items.append('walled garden IP entries')

    # 1. Firewall rules (by comment)
    if await remove_by_filter('/ip/firewall/filter', 'comment', 'codevertex', 'firewall rules'):
        cleaned_items.append('firewall rules')

    # 2. Mangle rules (by comment)
    if await remove_by_filter('/ip/firewall/mangle', 'comment', 'codevertex', 'mangle rules'):
        cleaned_items.append('mangle rules')

    # 3. Hotspot (by name) - must come before DHCP/pool
    if await remove_by_filter('/ip/hotspot', 'name', 'codevertex', 'hotspot'):
        cleaned_items.append('hotspot')

    # 4. Hotspot profile (by name)
    if await remove_by_filter('/ip/hotspot/profile', 'name', 'codevertex', 'hotspot profile'):
        cleaned_items.append('hotspot profile')

    # 4b. SSL certificates (clean up after hotspot profile that references them)
    if await remove_by_filter('/certificate', 'name', 'codevertex', 'SSL certificates'):
        cleaned_items.append('SSL certificates')

    # 5. PPPoE server (by service-name)
    if await remove_by_filter('/interface/pppoe-server/server', 'service-name', 'codevertex', 'PPPoE server'):
        cleaned_items.append('PPPoE server')

    # 6. PPP profile (by name)
    if await remove_by_filter('/ppp/profile', 'name', 'codevertex', 'PPP profile'):
        cleaned_items.append('PPP profile')

    # 7. DHCP server (by name) - must come before IP pool
    if await remove_by_filter('/ip/dhcp-server', 'name', 'codevertex', 'DHCP server'):
        cleaned_items.append('DHCP server')

    # 8. DHCP network (by comment or gateway)
    if await remove_by_filter('/ip/dhcp-server/network', 'comment', 'codevertex', 'DHCP network'):
        cleaned_items.append('DHCP network')

    # 9. IP pool (by name)
    if await remove_by_filter('/ip/pool', 'name', 'codevertex', 'IP pool'):
        cleaned_items.append('IP pool')

    # 10. Bridge ports (by bridge name) - BEFORE removing bridge
    if await remove_by_filter('/interface/bridge/port', 'bridge', 'codevertex', 'bridge ports'):
        cleaned_items.append('bridge ports')

    # 11. IP addresses on bridge (by interface name)
    if await remove_by_filter('/ip/address', 'interface', 'codevertex', 'bridge IP'):
        cleaned_items.append('bridge IP')

    # 12. Bridge itself (by name) - LAST
    if await remove_by_filter('/interface/bridge', 'name', 'codevertex', 'bridge'):
        cleaned_items.append('bridge')

    if cleaned_items and session_id:
        await streaming_manager.log_provisioning_step(
            session_id,
            "cleanup",
            f"[OK] Cleaned up: {', '.join(cleaned_items)}",
            "success"
        )
    elif session_id:
        await streaming_manager.log_provisioning_step(
            session_id,
            "cleanup",
            "[OK] No existing configuration to clean up",
            "success"
        )


async def backup_router_configuration(db: AsyncSession, session, client, connection, logger) -> None:
    """Create a backup of the current router configuration.

    Note: This is a non-critical step. If backup fails, provisioning continues.
    The export_configuration method may not be available on all client implementations.
    """
    session_id = getattr(session, 'session_id', None)

    try:
        if session_id:
            await streaming_manager.log_provisioning_step(
                session_id,
                "backup",
                "Creating configuration backup...",
                "info"
            )

        # Check if export_configuration method exists
        if not hasattr(client, 'export_configuration'):
            logger.info("Configuration export not available - skipping backup")
            if session_id:
                await streaming_manager.log_provisioning_step(
                    session_id,
                    "backup",
                    "[SKIP] Configuration backup not available (continuing)",
                    "info"
                )
            return

        config_data = await client.export_configuration(connection)
        if config_data:
            from app.models.provisioning import RouterConfiguration
            import hashlib, json

            configuration = RouterConfiguration(
                router_id=session.router_id,
                session_id=session.id,
                configuration_type="backup",
                configuration_name=f"pre-provisioning-{datetime.utcnow().isoformat()}",
                configuration_data=config_data,
                is_backup=True,
                rollback_available=True,
                checksum=hashlib.sha256(json.dumps(config_data, sort_keys=True).encode()).hexdigest(),
            )
            db.add(configuration)
            await db.commit()
            logger.info(f"Created configuration backup for router {session.router_id}")

            if session_id:
                await streaming_manager.log_provisioning_step(
                    session_id,
                    "backup",
                    "[OK] Configuration backup created successfully",
                    "success"
                )
        else:
            if session_id:
                await streaming_manager.log_provisioning_step(
                    session_id,
                    "backup",
                    "[WARN] No configuration data to backup (continuing anyway)",
                    "warning"
                )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to create configuration backup: {e}")

        if session_id:
            await streaming_manager.log_provisioning_step(
                session_id,
                "backup",
                f"[WARN] Backup failed (non-critical): {str(e)[:100]}",
                "warning"
            )


async def apply_security_configuration(client, connection, config: Dict[str, Any], templates: Dict[str, Any], logger, session_id: Optional[str] = None) -> None:
    """Apply security configuration to the router.

    IMPORTANT: This function is designed to be SAFE and avoid management lockout.
    - No DROP-ALL rules are applied automatically
    - Existing codevertex rules are removed first to prevent duplicates
    - All rules have comments for identification
    - WinBox access is preserved for emergency recovery
    """
    try:
        if session_id:
            await streaming_manager.log_provisioning_step(
                session_id,
                "security",
                "Applying security configuration...",
                "info"
            )

        # Step 1: Clean up any existing codevertex firewall rules to prevent duplicates
        # This makes reprovisioning safe and idempotent
        try:
            cleanup_cmd = '/ip/firewall/filter/remove [find where comment~"codevertex"]'
            await client.execute_command(connection, cleanup_cmd)
            logger.info("Cleaned up existing codevertex firewall rules")
        except Exception as cleanup_error:
            # Ignore cleanup errors - rules might not exist
            logger.debug(f"Firewall cleanup (expected if no existing rules): {cleanup_error}")

        # Step 2: Disable default services (non-critical)
        for command in templates["security"]["disable_default_services"]:
            try:
                await client.execute_command(connection, command)
            except Exception as cmd_error:
                error_str = str(cmd_error).lower()
                # Ignore "already" errors
                if "already" not in error_str:
                    if session_id:
                        await streaming_manager.log_provisioning_step(
                            session_id,
                            "security",
                            f"[WARN] Security command warning: {str(cmd_error)[:80]}",
                            "warning"
                        )

        # Step 3: Apply firewall rules (all non-critical to avoid lockout)
        management_ip = config.get("management_ip", "0.0.0.0/0")
        rules_applied = 0
        for rule_template in templates["security"]["create_firewall_rules"]:
            rule = rule_template.format(management_ip=management_ip)
            try:
                await client.execute_command(connection, rule)
                rules_applied += 1
            except Exception as rule_error:
                error_str = str(rule_error).lower()
                # Ignore "already" errors
                if "already" not in error_str:
                    if session_id:
                        await streaming_manager.log_provisioning_step(
                            session_id,
                            "security",
                            f"[WARN] Firewall rule warning: {str(rule_error)[:80]}",
                            "warning"
                        )

        if session_id:
            await streaming_manager.log_provisioning_step(
                session_id,
                "security",
                f"[OK] Security configuration applied ({rules_applied} firewall rules)",
                "success"
            )

    except Exception as e:  # noqa: BLE001
        logger.warning(f"Security configuration partially failed: {e}")

        if session_id:
            await streaming_manager.log_provisioning_step(
                session_id,
                "security",
                f"[WARN] Security configuration partially failed: {str(e)[:100]}",
                "warning"
            )


