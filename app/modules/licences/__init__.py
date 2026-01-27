"""Licences module for licence management.

This module provides:
- LicenceService: Core CRUD operations for licences
- KeyOperations: Licence key generation and validation
- AnalyticsOperations: Licence analytics and reporting
"""

from .service import LicenceService
from .keys import KeyOperations
from .analytics import AnalyticsOperations

__all__ = [
    "LicenceService",
    "KeyOperations",
    "AnalyticsOperations",
]
