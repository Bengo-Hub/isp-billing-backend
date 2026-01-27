"""Analytics module for reports and advanced analytics.

This module provides:
- ReportsService: Report generation
- AdvancedAnalyticsService: Advanced analytics operations (requires sklearn)
"""

from .service import ReportsService

__all__ = [
    "ReportsService",
    "AdvancedAnalyticsService",
]


def __getattr__(name: str):
    """Lazy import for optional dependencies."""
    if name == "AdvancedAnalyticsService":
        from .advanced import AdvancedAnalyticsService
        return AdvancedAnalyticsService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
