"""MikroTik RouterOS integration with circuit breaker support."""

from app.integrations.mikrotik.client import MikroTikClient, get_mikrotik_client

# Backward compatibility alias
MikroTikService = MikroTikClient
MikroTikAPI = MikroTikClient

__all__ = ["MikroTikClient", "MikroTikService", "MikroTikAPI", "get_mikrotik_client"]
