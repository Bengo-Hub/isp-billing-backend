"""Verification helpers for Codevertex MikroTik provisioning."""

from __future__ import annotations

from typing import Any, Dict

from app.core.exceptions import ConfigurationError
from app.models.provisioning import ServiceType


async def verify_basic_configuration(client, connection, config: Dict[str, Any]) -> None:
    """Verify base configuration was applied correctly on the device.

    - Identity is set (if provided)
    - IP pool exists (if provided)
    """
    if "identity" in config:
        identity = await client.get_system_identity(connection)
        if identity != config["identity"]:
            raise ConfigurationError(
                f"System identity not set correctly. Expected: {config['identity']}, Got: {identity}"
            )

    if "pool_name" in config:
        pools = await client.get_ip_pools(connection)
        pool_names = [pool.get("name") for pool in pools]
        if config["pool_name"] not in pool_names:
            raise ConfigurationError(f"IP pool {config['pool_name']} not created")


async def verify_service_configuration(client, connection, service_type: ServiceType, config: Dict[str, Any]) -> None:
    """Verify service configuration for Hotspot or PPPoE."""
    if service_type == ServiceType.HOTSPOT:
        hotspots = await client.get_hotspot_servers(connection)
        hotspot_names = [hs.get("name") for hs in hotspots]
        expected_name = config.get("hotspot_name", "ISP-Hotspot")
        if expected_name not in hotspot_names:
            raise ConfigurationError(f"Hotspot {expected_name} not created")
    elif service_type == ServiceType.PPPOE_SERVER:
        pppoe_servers = await client.get_pppoe_servers(connection)
        if not pppoe_servers:
            raise ConfigurationError("PPPoE server not configured")


