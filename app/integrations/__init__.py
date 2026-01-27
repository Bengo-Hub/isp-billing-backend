"""External service integrations with resilience patterns.

This package provides clients for external services with built-in:
- Circuit breakers to prevent cascade failures
- Retry logic with exponential backoff
- Connection pooling where applicable
- Health status reporting
"""

from app.integrations.base import (
    BaseIntegrationClient,
    CircuitBreakerConfig,
    IntegrationHealth,
    IntegrationStatus,
)

__all__ = [
    "BaseIntegrationClient",
    "CircuitBreakerConfig",
    "IntegrationHealth",
    "IntegrationStatus",
]
