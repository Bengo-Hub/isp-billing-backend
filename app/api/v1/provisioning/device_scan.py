"""
Device scanning endpoints for MikroTik provisioning.
Handles scanning of device interfaces, ports, and services.
"""
import logging
from typing import Dict, List, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.models.user import User
from app.api.deps import require_technician_or_admin
from app.integrations.mikrotik import MikroTikService

logger = logging.getLogger(__name__)
router = APIRouter()


class DeviceScanRequest(BaseModel):
    router_id: int


class DeviceScanResponse(BaseModel):
    interfaces: List[str]
    services: List[str]
    current_subnet: str
    available_services: List[str]
    system_info: Dict[str, Any]


@router.post("/scan", response_model=DeviceScanResponse)
async def scan_device(
    request: DeviceScanRequest,
    current_user: User = Depends(require_technician_or_admin()),
):
    """Scan a MikroTik device for interfaces, ports, and services."""
    try:
        mikrotik_service = MikroTikService()
        
        # Get router information
        router = await mikrotik_service.get_router_by_id(request.router_id)
        if not router:
            raise HTTPException(status_code=404, detail="Router not found")
        
        # Connect to the router
        api = mikrotik_service.get_api_connection(router)
        if not api:
            raise HTTPException(status_code=400, detail="Unable to connect to router")
        
        # Scan interfaces
        interfaces = await scan_interfaces(api)
        
        # Scan services
        services = await scan_services(api)
        
        # Get current subnet configuration
        current_subnet = await get_current_subnet(api)
        
        # Get system information
        system_info = await get_system_info(api)
        
        # Determine available services
        available_services = determine_available_services(api, interfaces, services)
        
        return DeviceScanResponse(
            interfaces=interfaces,
            services=services,
            current_subnet=current_subnet,
            available_services=available_services,
            system_info=system_info
        )
    
    except Exception as e:
        logger.error(f"Failed to scan device: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scan device: {e}")


async def scan_interfaces(api) -> List[str]:
    """Scan for available network interfaces."""
    try:
        # Get interface list from RouterOS
        interfaces = []
        
        # Get ethernet interfaces
        ethernet_interfaces = api.get_resource('/interface/ethernet').get()
        for interface in ethernet_interfaces:
            interfaces.append(interface.get('name', ''))
        
        # Get SFP interfaces
        sfp_interfaces = api.get_resource('/interface/sfp').get()
        for interface in sfp_interfaces:
            interfaces.append(interface.get('name', ''))
        
        # Filter out empty names and sort
        interfaces = [iface for iface in interfaces if iface]
        interfaces.sort()
        
        return interfaces
    
    except Exception as e:
        logger.error(f"Failed to scan interfaces: {e}")
        return []


async def scan_services(api) -> List[str]:
    """Scan for available services on the router."""
    try:
        services = []
        
        # Check for hotspot service
        try:
            hotspot_profiles = api.get_resource('/ip/hotspot/profile').get()
            if hotspot_profiles:
                services.append('hotspot')
        except:
            pass
        
        # Check for PPPoE service
        try:
            pppoe_servers = api.get_resource('/interface/pppoe-server/server').get()
            if pppoe_servers:
                services.append('pppoe')
        except:
            pass
        
        # Check for DHCP service
        try:
            dhcp_servers = api.get_resource('/ip/dhcp-server').get()
            if dhcp_servers:
                services.append('dhcp')
        except:
            pass
        
        return services
    
    except Exception as e:
        logger.error(f"Failed to scan services: {e}")
        return []


async def get_current_subnet(api) -> str:
    """Get the current subnet configuration."""
    try:
        # Get IP addresses
        ip_addresses = api.get_resource('/ip/address').get()
        
        for address in ip_addresses:
            if address.get('interface') == 'bridge' or 'bridge' in address.get('interface', ''):
                return address.get('address', '192.168.88.0/24')
        
        # Default subnet if none found
        return '192.168.88.0/24'
    
    except Exception as e:
        logger.error(f"Failed to get current subnet: {e}")
        return '192.168.88.0/24'


async def get_system_info(api) -> Dict[str, Any]:
    """Get system information from the router."""
    try:
        system_info = {}
        
        # Get system identity
        identity = api.get_resource('/system/identity').get()
        if identity:
            system_info['identity'] = identity[0].get('name', '')
        
        # Get system resource
        resource = api.get_resource('/system/resource').get()
        if resource:
            system_info['board_name'] = resource[0].get('board-name', '')
            system_info['version'] = resource[0].get('version', '')
            system_info['architecture'] = resource[0].get('architecture-name', '')
        
        # Get system clock
        clock = api.get_resource('/system/clock').get()
        if clock:
            system_info['time'] = clock[0].get('time', '')
            system_info['timezone'] = clock[0].get('time-zone-name', '')
        
        return system_info
    
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        return {}


def determine_available_services(api, interfaces: List[str], current_services: List[str]) -> List[str]:
    """Determine which services can be configured on this router."""
    available_services = []
    
    # Hotspot is generally available on most MikroTik devices
    if 'hotspot' not in current_services:
        available_services.append('hotspot')
    
    # PPPoE is available on most MikroTik devices
    if 'pppoe' not in current_services:
        available_services.append('pppoe')
    
    return available_services
