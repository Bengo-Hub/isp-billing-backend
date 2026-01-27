"""System module for configuration, initialization, and utilities.

This module provides:
- ConfigurationService: System configuration management
- initialization_service: System initialization singleton
- DataIntegrityService: Data integrity operations
- UIService: UI configuration service
"""

from .configuration import ConfigurationService
from .initialization import initialization_service, InitializationService
from .data_integrity import DataIntegrityService
from .ui import UIService

__all__ = [
    "ConfigurationService",
    "initialization_service",
    "InitializationService",
    "DataIntegrityService",
    "UIService",
]
