"""Routers module for MikroTik router management.

This module provides:
- RouterService: Core CRUD operations for routers
- MikroTikOperations: MikroTik-specific API operations
- DeviceOperations: Router device management
"""

from .service import RouterService
from .mikrotik import MikroTikOperations
from .devices import DeviceOperations

__all__ = [
    "RouterService",
    "MikroTikOperations",
    "DeviceOperations",
]
