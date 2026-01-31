"""Command generation and helpers for Codevertex MikroTik provisioning.

These helpers are imported by ProvisioningService to keep the service file
small and focused on orchestration. Functions here are stateless and accept
explicit parameters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provisioning import ProvisioningCommand, ProvisioningStatus, ServiceType
from .live_streaming import streaming_manager


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
    config: Dict[str, Any], service_type: ServiceType
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
                "command": f"/interface/bridge/port/add interface={port} bridge={bridge_name}",
                "description": f"Adding port {port} to bridge",
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
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/dhcp-server/network/add address={subnet_address}/{cidr} gateway={gateway} dns-server={dns_list}",
            "description": "Configuring DHCP network parameters",
            "critical": True,
        }
    )

    # NAT Masquerade for internet access (assumes ether1 is WAN)
    wan_interface = config.get("wan_interface", "ether1")
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/firewall/nat/add chain=srcnat action=masquerade out-interface={wan_interface}",
            "description": f"Enabling NAT masquerade on {wan_interface}",
            "critical": True,
        }
    )

    return commands


def generate_hotspot_commands(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate MikroTik hotspot configuration commands.

    Creates hotspot on the bridge interface with optional anti-sharing protection.
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

    # Create hotspot profile first
    profile_name = config.get("hotspot_profile", "codevertex-hsprof")
    redirect_url = config.get("redirect_url", "")
    dns_name = config.get("hotspot_dns_name", "codevertex.local")

    # Build hotspot profile command with optional redirect URL
    profile_cmd = f"/ip/hotspot/profile/add name={profile_name} hotspot-address={gateway} dns-name={dns_name} login-by=http-chap"
    if redirect_url:
        profile_cmd += f" login-by=http-chap,http-pap html-directory-override=hotspot http-cookie-lifetime=3d"
        # Note: redirect-url is set separately after profile creation

    commands.append(
        {
            "type": "api_call",
            "command": profile_cmd,
            "description": f"Creating hotspot profile {profile_name}",
            "critical": True,
        }
    )

    # Set redirect URL if provided (done separately to handle existing profiles)
    if redirect_url:
        commands.append(
            {
                "type": "api_call",
                "command": f"/ip/hotspot/profile/set {profile_name} login-by=http-chap html-directory-override=hotspot",
                "description": f"Configure hotspot profile login settings",
                "critical": False,
            }
        )

    # Create hotspot on bridge interface
    commands.append(
        {
            "type": "api_call",
            "command": f"/ip/hotspot/add name={hotspot_name} interface={bridge_name} address-pool={pool_name} profile={profile_name} disabled=no",
            "description": f"Creating hotspot {hotspot_name} on {bridge_name}",
            "critical": True,
        }
    )
    # Check all naming variations for anti-sharing flag
    # Frontend may send: enableAntiSharing, enable_anti_sharing, or enable_hotspot_anti_sharing
    enable_anti_sharing = (
        config.get("enable_anti_sharing") or
        config.get("enableAntiSharing") or
        config.get("enable_hotspot_anti_sharing") or
        False
    )
    if enable_anti_sharing:
        # Configure hotspot profile with session controls
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/hotspot/profile/set default login-by=http-chap session-timeout=1d idle-timeout=5m shared-users=1",
                "description": "Configure hotspot profile for anti-sharing",
                "critical": False,
            }
        )
        # TTL modification rules to detect and prevent connection sharing
        # When TTL is 65, it means the packet has been routed through another device (shared)
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/firewall/mangle/add chain=forward action=change-ttl new-ttl=set:64 passthrough=yes ttl=equal:65 protocol=tcp dst-port=80,443,53",
                "description": "Anti-sharing TTL rule for TCP (HTTP/HTTPS/DNS)",
                "critical": False,
            }
        )
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/firewall/mangle/add chain=forward action=change-ttl new-ttl=set:64 passthrough=yes ttl=equal:65 protocol=udp dst-port=53,67,68",
                "description": "Anti-sharing TTL rule for UDP (DNS/DHCP)",
                "critical": False,
            }
        )
        # Optional: Drop packets with suspicious TTL values (aggressive mode)
        commands.append(
            {
                "type": "api_call",
                "command": "/ip/firewall/filter/add chain=forward action=drop ttl=equal:1 comment=codevertex-anti-sharing",
                "description": "Block suspicious low-TTL packets",
                "critical": False,
            }
        )
    if "walled_garden_hosts" in config:
        for host in config["walled_garden_hosts"]:
            commands.append(
                {
                    "type": "api_call",
                    "command": f"/ip/hotspot/walled-garden/add dst-host={host}",
                    "description": f"Add walled garden host {host}",
                    "critical": False,
                }
            )
    return commands


def generate_pppoe_commands(config: Dict[str, Any]) -> List[Dict[str, Any]]:
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


