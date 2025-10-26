"""
Network calculation endpoints for provisioning.
Handles IP address calculations and network configuration.
"""
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from ipaddress import IPv4Network
from app.models.user import User
from app.api.deps import require_technician_or_admin

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/calc")
async def calculate_network(
    subnet_address: str = Query("172.31.0.0"),
    cidr: int = Query(16, ge=8, le=30),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Calculate gateway and DHCP pool suggestion for UI auto-calculation block."""
    try:
        # Validate and calculate network parameters
        net = IPv4Network(f"{subnet_address}/{cidr}", strict=False)
        hosts = list(net.hosts())
        
        # Calculate gateway (usually first usable IP)
        gateway = str(hosts[1] if len(hosts) > 1 else hosts[0])
        
        # Calculate DHCP pool (reserve first few IPs for infrastructure)
        pool_start = str(hosts[10] if len(hosts) > 10 else hosts[0])
        pool_end = str(list(net.hosts())[-1])
        
        # Calculate total hosts
        total_hosts = len(list(net.hosts()))
        
        return {
            "subnet_address": subnet_address,
            "cidr": cidr,
            "network": str(net.network_address) + f"/{cidr}",
            "gateway": gateway,
            "dhcp_pool_start": pool_start,
            "dhcp_pool_end": pool_end,
            "dhcp_pool": f"{pool_start} - {pool_end}",
            "network_mask": str(net.netmask),
            "total_hosts": total_hosts,
        }
    
    except Exception as e:
        logger.error(f"Failed to calculate network parameters: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid network parameters: {e}")


@router.get("/validate")
async def validate_network_config(
    subnet_address: str = Query(...),
    cidr: int = Query(...),
    gateway: str = Query(...),
    current_user: User = Depends(require_technician_or_admin()),
):
    """Validate network configuration parameters."""
    try:
        # Validate network
        net = IPv4Network(f"{subnet_address}/{cidr}", strict=False)
        
        # Check if gateway is within the network
        from ipaddress import IPv4Address
        gateway_ip = IPv4Address(gateway)
        is_gateway_valid = gateway_ip in net
        
        return {
            "valid": is_gateway_valid,
            "network": str(net),
            "gateway_in_network": is_gateway_valid,
            "available_hosts": len(list(net.hosts())),
        }
    
    except Exception as e:
        logger.error(f"Failed to validate network configuration: {e}")
        return {"valid": False, "error": str(e)}
