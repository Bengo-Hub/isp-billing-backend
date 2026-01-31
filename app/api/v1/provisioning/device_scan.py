"""
Device scanning endpoints for MikroTik provisioning.
Handles scanning of device interfaces, ports, and services.
"""
import asyncio
import logging
import re
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_technician_or_admin
from app.core.config import settings
from app.integrations.mikrotik import get_mikrotik_client
from app.models.router import Router
from app.models.user import User

logger = logging.getLogger(__name__)

# Default subnet from config (with fallback)
DEFAULT_SUBNET = settings.mikrotik_default_subnet
router = APIRouter()


class DeviceScanRequest(BaseModel):
    router_id: int


class ServiceStatus(BaseModel):
    """Service status showing if it's currently active and if it can be configured."""
    name: str
    active: bool  # Currently configured/running
    available: bool  # Can be configured


class NetworkConfiguration(BaseModel):
    """Auto-calculated network configuration based on scanned subnet."""
    # Router IP info
    router_ip: str  # e.g., "192.168.100.7" - the router's IP address
    router_ip_cidr: str  # e.g., "192.168.100.7/24" - router IP with CIDR notation
    # Network info
    network: str  # e.g., "192.168.100.0/24" - network address with CIDR
    network_address: str  # e.g., "192.168.100.0" - network address only
    gateway: str  # e.g., "192.168.100.1"
    broadcast: str  # e.g., "192.168.100.255"
    # DHCP info
    dhcp_start: str  # e.g., "192.168.100.2"
    dhcp_end: str  # e.g., "192.168.100.254"
    dhcp_pool: str  # e.g., "192.168.100.2 - 192.168.100.254"
    # Subnet info
    subnet_mask: str  # e.g., "255.255.255.0"
    cidr: int  # e.g., 24
    total_hosts: int  # e.g., 254 for /24
    # DNS info
    dns_servers: List[str] = []  # e.g., ["8.8.8.8", "8.8.4.4"]
    # Existing DHCP config (if any)
    existing_dhcp_pool: Optional[str] = None
    existing_dhcp_range: Optional[str] = None
    # Legacy field for backward compatibility
    current_subnet: str  # e.g., "192.168.100.7/24" (same as router_ip_cidr)


class SystemInfo(BaseModel):
    """Detailed system information from the router."""
    identity: str = ""
    board_name: str = ""
    model: str = ""
    version: str = ""
    architecture: str = ""
    cpu_count: Optional[int] = None
    cpu_load: Optional[str] = None
    total_memory: Optional[str] = None
    free_memory: Optional[str] = None
    uptime: Optional[str] = None
    time: str = ""
    timezone: str = ""


class DeviceScanResponse(BaseModel):
    """Enhanced device scan response with structured data."""
    interfaces: List[str]
    wan_interface: str  # Detected WAN interface (usually ether1)
    services: List[ServiceStatus]
    network_config: NetworkConfiguration
    system_info: SystemInfo
    # Legacy fields for backward compatibility
    current_subnet: str
    available_services: List[str]


@router.post("/scan", response_model=DeviceScanResponse)
async def scan_device(
    request: DeviceScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Scan a MikroTik device for interfaces, ports, and services.

    Scanned data is persisted to the router's config JSON field to avoid
    re-scanning once provisioning is complete.
    """
    from app.services.router_provisioning import get_router_credentials, store_scanned_config

    logger.info(f"Device scan request for router_id={request.router_id} by user={current_user.username}")

    # Get router from database
    result = await db.execute(select(Router).where(Router.id == request.router_id))
    router_obj = result.scalar_one_or_none()

    if not router_obj:
        raise HTTPException(status_code=404, detail="Router not found")

    # Get credentials from DB (encrypted) with fallback to env settings
    credentials = await get_router_credentials(db, request.router_id)
    if not credentials:
        raise HTTPException(status_code=400, detail="No credentials available for router")

    # Get MikroTik client singleton and connect to router
    client = get_mikrotik_client()

    try:
        # Connect to the router using credentials from DB
        connection = await client.connect(
            ip_address=router_obj.ip_address,
            username=credentials["username"],
            password=credentials["password"],
            port=router_obj.port,
        )

        # Get the API resource accessor from the connection pool
        api = connection.get_api()

        # Scan interfaces
        interfaces = await scan_interfaces(api)

        # Detect WAN interface (usually the one with gateway or ether1)
        wan_interface = await detect_wan_interface(api, interfaces)

        # Scan services
        services = await scan_services_detailed(api)

        # Get current subnet configuration with auto-calculation
        network_config = await get_network_configuration(api)

        # Get system information
        system_info = await get_system_info_detailed(api)

        # Build legacy fields for backward compatibility
        active_services = [s.name for s in services if s.active]
        available_services = [s.name for s in services if s.available and not s.active]

        logger.info(f"Device scan completed for router {request.router_id}: "
                    f"{len(interfaces)} interfaces, {len(services)} services")

        # Persist scanned data to router's config JSON field
        try:
            services_dicts = [{"name": s.name, "active": s.active, "available": s.available} for s in services]
            network_config_dict = network_config.model_dump()
            system_info_dict = system_info.model_dump()

            await store_scanned_config(
                db=db,
                router_id=request.router_id,
                interfaces=interfaces,
                services=services_dicts,
                network_config=network_config_dict,
                system_info=system_info_dict
            )
            logger.info(f"Persisted scanned config for router {request.router_id}")
        except Exception as e:
            # Don't fail the scan if persistence fails
            logger.warning(f"Failed to persist scanned config for router {request.router_id}: {e}")

        return DeviceScanResponse(
            interfaces=interfaces,
            wan_interface=wan_interface,
            services=services,
            network_config=network_config,
            system_info=system_info,
            # Legacy fields
            current_subnet=network_config.current_subnet,
            available_services=available_services
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scan device {request.router_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scan device: {e}")


async def scan_interfaces(api) -> List[str]:
    """Scan for available network interfaces."""
    try:
        interfaces = []
        loop = asyncio.get_event_loop()

        # Get ethernet interfaces
        try:
            ethernet_interfaces = await loop.run_in_executor(
                None,
                lambda: api.get_resource('/interface/ethernet').get()
            )
            for interface in ethernet_interfaces:
                name = interface.get('name', '')
                if name:
                    interfaces.append(name)
        except Exception as e:
            logger.debug(f"Failed to get ethernet interfaces: {e}")

        # Get SFP interfaces
        try:
            sfp_interfaces = await loop.run_in_executor(
                None,
                lambda: api.get_resource('/interface/sfp').get()
            )
            for interface in sfp_interfaces:
                name = interface.get('name', '')
                if name:
                    interfaces.append(name)
        except Exception as e:
            logger.debug(f"No SFP interfaces found: {e}")

        # Get all interfaces as fallback
        if not interfaces:
            try:
                all_interfaces = await loop.run_in_executor(
                    None,
                    lambda: api.get_resource('/interface').get()
                )
                for interface in all_interfaces:
                    name = interface.get('name', '')
                    iface_type = interface.get('type', '')
                    if name and iface_type in ('ether', 'ethernet', 'sfp'):
                        interfaces.append(name)
            except Exception as e:
                logger.debug(f"Failed to get all interfaces: {e}")

        # Sort interfaces naturally (ether1, ether2, ..., ether10)
        def natural_sort_key(s):
            return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

        interfaces.sort(key=natural_sort_key)
        return interfaces

    except Exception as e:
        logger.error(f"Failed to scan interfaces: {e}")
        return []


async def detect_wan_interface(api, interfaces: List[str]) -> str:
    """Detect the WAN interface based on gateway routes."""
    try:
        loop = asyncio.get_event_loop()

        # Check default route to find WAN interface
        try:
            routes = await loop.run_in_executor(
                None,
                lambda: api.get_resource('/ip/route').get()
            )
            for route in routes:
                if route.get('dst-address') == '0.0.0.0/0':
                    gateway_interface = route.get('gateway', '')
                    # If gateway is an IP, find the interface
                    if gateway_interface and gateway_interface in interfaces:
                        return gateway_interface
        except Exception:
            pass

        # Default to ether1 if no gateway found
        if 'ether1' in interfaces:
            return 'ether1'

        return interfaces[0] if interfaces else 'ether1'

    except Exception as e:
        logger.debug(f"Failed to detect WAN interface: {e}")
        return 'ether1'


async def scan_services_detailed(api) -> List[ServiceStatus]:
    """Scan for services with detailed status."""
    services = []
    loop = asyncio.get_event_loop()

    # Check Hotspot
    hotspot_active = False
    try:
        hotspot_servers = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/ip/hotspot').get()
        )
        hotspot_active = len(hotspot_servers) > 0
    except Exception:
        pass

    services.append(ServiceStatus(
        name="hotspot",
        active=hotspot_active,
        available=True  # Hotspot is always available on MikroTik
    ))

    # Check PPPoE Server
    pppoe_active = False
    try:
        pppoe_servers = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/interface/pppoe-server/server').get()
        )
        pppoe_active = len(pppoe_servers) > 0
    except Exception:
        pass

    services.append(ServiceStatus(
        name="pppoe",
        active=pppoe_active,
        available=True  # PPPoE is always available on MikroTik
    ))

    # Check DHCP Server
    dhcp_active = False
    try:
        dhcp_servers = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/ip/dhcp-server').get()
        )
        dhcp_active = len(dhcp_servers) > 0
    except Exception:
        pass

    services.append(ServiceStatus(
        name="dhcp",
        active=dhcp_active,
        available=True
    ))

    return services


async def get_network_configuration(api) -> NetworkConfiguration:
    """Get current network configuration and calculate network parameters."""
    try:
        loop = asyncio.get_event_loop()

        # Get IP addresses
        ip_addresses = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/ip/address').get()
        )

        # Find the best IP address (prefer bridge, then LAN interfaces)
        router_ip_cidr = DEFAULT_SUBNET
        for address in ip_addresses:
            iface = address.get('interface', '')
            if 'bridge' in iface.lower():
                router_ip_cidr = address.get('address', DEFAULT_SUBNET)
                break
            elif iface not in ['ether1']:  # Exclude WAN
                router_ip_cidr = address.get('address', DEFAULT_SUBNET)

        # If no suitable address found, use first available
        if router_ip_cidr == DEFAULT_SUBNET and ip_addresses:
            router_ip_cidr = ip_addresses[0].get('address', DEFAULT_SUBNET)

        # Get DNS servers
        dns_servers = []
        try:
            dns_config = await loop.run_in_executor(
                None,
                lambda: api.get_resource('/ip/dns').get()
            )
            if dns_config:
                servers_str = dns_config[0].get('servers', '')
                if servers_str:
                    dns_servers = [s.strip() for s in servers_str.split(',') if s.strip()]
        except Exception as e:
            logger.debug(f"Failed to get DNS servers: {e}")

        # Get existing DHCP pool configuration
        existing_dhcp_pool = None
        existing_dhcp_range = None
        try:
            dhcp_servers = await loop.run_in_executor(
                None,
                lambda: api.get_resource('/ip/dhcp-server').get()
            )
            if dhcp_servers:
                existing_dhcp_pool = dhcp_servers[0].get('address-pool', '')

            # Get pool range
            if existing_dhcp_pool:
                pools = await loop.run_in_executor(
                    None,
                    lambda: api.get_resource('/ip/pool').get()
                )
                for pool in pools:
                    if pool.get('name') == existing_dhcp_pool:
                        existing_dhcp_range = pool.get('ranges', '')
                        break
        except Exception as e:
            logger.debug(f"Failed to get DHCP config: {e}")

        # Parse and calculate network configuration
        return calculate_network_config(
            router_ip_cidr,
            dns_servers=dns_servers,
            existing_dhcp_pool=existing_dhcp_pool,
            existing_dhcp_range=existing_dhcp_range
        )

    except Exception as e:
        logger.error(f"Failed to get network configuration: {e}")
        return calculate_network_config(DEFAULT_SUBNET)


def calculate_network_config(
    router_ip_cidr: str,
    dns_servers: List[str] = None,
    existing_dhcp_pool: Optional[str] = None,
    existing_dhcp_range: Optional[str] = None
) -> NetworkConfiguration:
    """Calculate network configuration from a router IP with CIDR notation.

    Args:
        router_ip_cidr: Router's IP with CIDR (e.g., "192.168.100.7/24")
        dns_servers: List of DNS server IPs
        existing_dhcp_pool: Name of existing DHCP pool
        existing_dhcp_range: Range of existing DHCP pool
    """
    if dns_servers is None:
        dns_servers = []

    try:
        # Parse router IP and CIDR (e.g., "192.168.100.7/24")
        if '/' in router_ip_cidr:
            router_ip, cidr_str = router_ip_cidr.split('/')
            cidr = int(cidr_str)
        else:
            router_ip = router_ip_cidr
            cidr = 24  # Default to /24

        octets = [int(o) for o in router_ip.split('.')]

        # Calculate subnet mask
        mask_bits = (0xFFFFFFFF << (32 - cidr)) & 0xFFFFFFFF
        subnet_mask = '.'.join([str((mask_bits >> (8 * i)) & 0xFF) for i in range(3, -1, -1)])

        # Calculate network address by applying mask
        ip_int = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
        network_int = ip_int & mask_bits
        network_octets = [
            (network_int >> 24) & 0xFF,
            (network_int >> 16) & 0xFF,
            (network_int >> 8) & 0xFF,
            network_int & 0xFF
        ]
        network_address = '.'.join(str(o) for o in network_octets)

        # Calculate broadcast address
        broadcast_int = network_int | (~mask_bits & 0xFFFFFFFF)
        broadcast_octets = [
            (broadcast_int >> 24) & 0xFF,
            (broadcast_int >> 16) & 0xFF,
            (broadcast_int >> 8) & 0xFF,
            broadcast_int & 0xFF
        ]
        broadcast = '.'.join(str(o) for o in broadcast_octets)

        # Calculate gateway (first usable IP in network)
        gateway_int = network_int + 1
        gateway_octets = [
            (gateway_int >> 24) & 0xFF,
            (gateway_int >> 16) & 0xFF,
            (gateway_int >> 8) & 0xFF,
            gateway_int & 0xFF
        ]
        gateway = '.'.join(str(o) for o in gateway_octets)

        # Calculate DHCP range (second usable to last usable)
        dhcp_start_int = network_int + 2
        dhcp_end_int = broadcast_int - 1
        dhcp_start_octets = [
            (dhcp_start_int >> 24) & 0xFF,
            (dhcp_start_int >> 16) & 0xFF,
            (dhcp_start_int >> 8) & 0xFF,
            dhcp_start_int & 0xFF
        ]
        dhcp_end_octets = [
            (dhcp_end_int >> 24) & 0xFF,
            (dhcp_end_int >> 16) & 0xFF,
            (dhcp_end_int >> 8) & 0xFF,
            dhcp_end_int & 0xFF
        ]
        dhcp_start = '.'.join(str(o) for o in dhcp_start_octets)
        dhcp_end = '.'.join(str(o) for o in dhcp_end_octets)

        # Calculate total usable hosts (excluding network and broadcast)
        total_hosts = (2 ** (32 - cidr)) - 2
        if total_hosts < 0:
            total_hosts = 0

        return NetworkConfiguration(
            # Router IP info
            router_ip=router_ip,
            router_ip_cidr=router_ip_cidr,
            # Network info
            network=f"{network_address}/{cidr}",
            network_address=network_address,
            gateway=gateway,
            broadcast=broadcast,
            # DHCP info
            dhcp_start=dhcp_start,
            dhcp_end=dhcp_end,
            dhcp_pool=f"{dhcp_start} - {dhcp_end}",
            # Subnet info
            subnet_mask=subnet_mask,
            cidr=cidr,
            total_hosts=total_hosts,
            # DNS info
            dns_servers=dns_servers,
            # Existing DHCP config
            existing_dhcp_pool=existing_dhcp_pool,
            existing_dhcp_range=existing_dhcp_range,
            # Legacy field
            current_subnet=router_ip_cidr
        )

    except Exception as e:
        logger.error(f"Failed to calculate network config from {router_ip_cidr}: {e}")
        return NetworkConfiguration(
            router_ip="192.168.88.1",
            router_ip_cidr=router_ip_cidr,
            network="192.168.88.0/24",
            network_address="192.168.88.0",
            gateway="192.168.88.1",
            broadcast="192.168.88.255",
            dhcp_start="192.168.88.2",
            dhcp_end="192.168.88.254",
            dhcp_pool="192.168.88.2 - 192.168.88.254",
            subnet_mask="255.255.255.0",
            cidr=24,
            total_hosts=254,
            dns_servers=[],
            existing_dhcp_pool=None,
            existing_dhcp_range=None,
            current_subnet=router_ip_cidr
        )


async def get_system_info_detailed(api) -> SystemInfo:
    """Get detailed system information from the router."""
    system_info = SystemInfo()
    loop = asyncio.get_event_loop()

    # Get system identity
    try:
        identity = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/system/identity').get()
        )
        if identity:
            system_info.identity = identity[0].get('name', '')
    except Exception as e:
        logger.debug(f"Failed to get identity: {e}")

    # Get system resource (detailed info)
    try:
        resource = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/system/resource').get()
        )
        if resource:
            r = resource[0]
            system_info.board_name = r.get('board-name', '')
            system_info.model = r.get('board-name', 'MikroTik')
            system_info.version = r.get('version', '')
            system_info.architecture = r.get('architecture-name', '')
            system_info.uptime = r.get('uptime', '')
            system_info.cpu_load = r.get('cpu-load', '')
            system_info.total_memory = r.get('total-memory', '')
            system_info.free_memory = r.get('free-memory', '')

            # Parse CPU count
            cpu_count = r.get('cpu-count')
            if cpu_count:
                try:
                    system_info.cpu_count = int(cpu_count)
                except ValueError:
                    pass
    except Exception as e:
        logger.debug(f"Failed to get resource: {e}")

    # Get system clock
    try:
        clock = await loop.run_in_executor(
            None,
            lambda: api.get_resource('/system/clock').get()
        )
        if clock:
            system_info.time = clock[0].get('time', '')
            system_info.timezone = clock[0].get('time-zone-name', '')
    except Exception as e:
        logger.debug(f"Failed to get clock: {e}")

    return system_info
