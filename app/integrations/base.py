"""Base integration client with circuit breaker and retry patterns.

This module provides a base class for external service clients that includes:
- Circuit breaker pattern to prevent cascade failures
- Automatic retry with exponential backoff
- Health status reporting
- Configurable timeouts and thresholds
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

import pybreaker
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.errors import APIError, ErrorCode, ExternalServiceError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class IntegrationStatus(str, Enum):
    """Integration health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class IntegrationHealth:
    """Health status for an integration."""

    name: str
    status: IntegrationStatus
    circuit_state: str
    fail_count: int
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    response_time_ms: Optional[float] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "circuit_state": self.circuit_state,
            "fail_count": self.fail_count,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "response_time_ms": self.response_time_ms,
            "message": self.message,
        }


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Attributes:
        fail_max: Number of failures before opening the circuit.
        reset_timeout: Seconds before attempting to close an open circuit.
        exclude_exceptions: Exception types that should not trigger the breaker.
        expected_exception: Exception type to catch and count.
    """

    fail_max: int = 5
    reset_timeout: int = 60
    exclude_exceptions: tuple = field(default_factory=tuple)
    expected_exception: type = Exception


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of retry attempts.
        min_wait_seconds: Minimum wait time between retries.
        max_wait_seconds: Maximum wait time between retries.
        retry_exceptions: Exception types that should trigger a retry.
    """

    max_attempts: int = 3
    min_wait_seconds: float = 1.0
    max_wait_seconds: float = 10.0
    retry_exceptions: tuple = (ConnectionError, TimeoutError)


class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """Listener for circuit breaker state changes."""

    def __init__(self, name: str):
        self.name = name
        self.last_failure: Optional[datetime] = None
        self.last_success: Optional[datetime] = None

    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: str, new_state: str) -> None:
        """Called when circuit breaker state changes."""
        logger.warning(
            f"Circuit breaker '{self.name}' state changed: {old_state} -> {new_state}"
        )

    def failure(self, cb: pybreaker.CircuitBreaker, exc: Exception) -> None:
        """Called when a failure is recorded."""
        self.last_failure = datetime.now(timezone.utc)
        logger.error(f"Circuit breaker '{self.name}' recorded failure: {exc}")

    def success(self, cb: pybreaker.CircuitBreaker) -> None:
        """Called when a success is recorded."""
        self.last_success = datetime.now(timezone.utc)


class BaseIntegrationClient(ABC, Generic[T]):
    """Base class for external API clients with resilience patterns.

    This class provides circuit breaker and retry functionality for
    external service integrations. Subclasses should implement the
    specific API methods while leveraging these resilience patterns.

    Example:
        class MikroTikClient(BaseIntegrationClient[RouterOSAPI]):
            async def connect(self, ip: str, username: str, password: str) -> bool:
                return await self.execute_with_resilience(
                    self._do_connect, ip, username, password
                )

            async def _do_connect(self, ip: str, username: str, password: str) -> bool:
                # Actual connection logic
                pass
    """

    def __init__(
        self,
        name: str,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        default_timeout: float = 30.0,
    ):
        """Initialize the integration client.

        Args:
            name: Unique name for this integration (used in logging/metrics).
            circuit_config: Circuit breaker configuration.
            retry_config: Retry configuration.
            default_timeout: Default timeout for operations in seconds.
        """
        self.name = name
        self.circuit_config = circuit_config or CircuitBreakerConfig()
        self.retry_config = retry_config or RetryConfig()
        self.default_timeout = default_timeout

        # Create circuit breaker listener
        self._listener = CircuitBreakerListener(name)

        # Create circuit breaker
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=self.circuit_config.fail_max,
            reset_timeout=self.circuit_config.reset_timeout,
            exclude=self.circuit_config.exclude_exceptions,
            listeners=[self._listener],
            name=f"{name}_circuit_breaker",
        )

        logger.info(f"Initialized integration client: {name}")

    @property
    def circuit_state(self) -> str:
        """Get current circuit breaker state."""
        return str(self._breaker.current_state)

    @property
    def is_circuit_open(self) -> bool:
        """Check if circuit breaker is open (blocking calls)."""
        return self._breaker.current_state == "open"

    async def execute_with_resilience(
        self,
        operation: Callable[..., T],
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> T:
        """Execute an operation with circuit breaker and retry protection.

        This method wraps the given operation with:
        1. Circuit breaker protection
        2. Retry logic with exponential backoff
        3. Timeout protection

        Args:
            operation: The async function to execute.
            *args: Positional arguments for the operation.
            timeout: Operation timeout in seconds (overrides default).
            **kwargs: Keyword arguments for the operation.

        Returns:
            The result of the operation.

        Raises:
            ExternalServiceError: If the operation fails after all retries
                or if the circuit breaker is open.
        """
        timeout = timeout or self.default_timeout
        start_time = time.time()

        # Check if circuit is open before attempting
        if self.is_circuit_open:
            raise ExternalServiceError(
                message=f"Service {self.name} is temporarily unavailable (circuit open)",
                code=ErrorCode.SYS_CIRCUIT_OPEN,
                service_name=self.name,
            )

        try:
            # Create retry context
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.retry_config.max_attempts),
                wait=wait_exponential(
                    multiplier=1,
                    min=self.retry_config.min_wait_seconds,
                    max=self.retry_config.max_wait_seconds,
                ),
                retry=retry_if_exception_type(self.retry_config.retry_exceptions),
                reraise=True,
            ):
                with attempt:
                    # Execute with circuit breaker
                    result = await self._execute_with_circuit_breaker(
                        operation, *args, timeout=timeout, **kwargs
                    )
                    return result

        except pybreaker.CircuitBreakerError:
            elapsed = (time.time() - start_time) * 1000
            logger.error(
                f"Circuit breaker open for {self.name} after {elapsed:.2f}ms"
            )
            raise ExternalServiceError(
                message=f"Service {self.name} is temporarily unavailable",
                code=ErrorCode.SYS_CIRCUIT_OPEN,
                service_name=self.name,
            )

        except RetryError as e:
            elapsed = (time.time() - start_time) * 1000
            logger.error(
                f"All retries exhausted for {self.name} after {elapsed:.2f}ms: {e}"
            )
            raise ExternalServiceError(
                message=f"Service {self.name} failed after {self.retry_config.max_attempts} attempts",
                code=ErrorCode.EXT_SERVICE_UNAVAILABLE,
                service_name=self.name,
                details={"attempts": self.retry_config.max_attempts},
            )

        except asyncio.TimeoutError:
            elapsed = (time.time() - start_time) * 1000
            logger.error(f"Timeout for {self.name} after {elapsed:.2f}ms")
            raise ExternalServiceError(
                message=f"Service {self.name} timed out after {timeout}s",
                code=ErrorCode.EXT_SERVICE_UNAVAILABLE,
                service_name=self.name,
                details={"timeout_seconds": timeout},
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            logger.error(f"Unexpected error for {self.name} after {elapsed:.2f}ms: {e}")
            raise

        # This should not be reached, but satisfy type checker
        raise ExternalServiceError(
            message=f"Unexpected state in {self.name}",
            code=ErrorCode.SYS_INTERNAL_ERROR,
            service_name=self.name,
        )

    async def _execute_with_circuit_breaker(
        self,
        operation: Callable[..., T],
        *args: Any,
        timeout: float,
        **kwargs: Any,
    ) -> T:
        """Execute operation with circuit breaker and timeout.

        Args:
            operation: The async function to execute.
            *args: Positional arguments.
            timeout: Timeout in seconds.
            **kwargs: Keyword arguments.

        Returns:
            Result of the operation.
        """
        # Check circuit state first
        if self._breaker.current_state == "open":
            raise pybreaker.CircuitBreakerError(self._breaker)

        # Execute the async operation with timeout
        # We track success/failure manually since pybreaker is sync-only
        try:
            result = await asyncio.wait_for(
                operation(*args, **kwargs), timeout=timeout
            )
            # Record success
            self._listener.last_success = datetime.now(timezone.utc)
            return result
        except Exception as e:
            # Record failure
            self._listener.last_failure = datetime.now(timezone.utc)
            logger.debug(f"Circuit breaker '{self.name}' recorded failure: {type(e).__name__}: {e}")
            raise

    def get_health(self) -> IntegrationHealth:
        """Get current health status of the integration.

        Returns:
            IntegrationHealth with current status and metrics.
        """
        circuit_state = self.circuit_state
        fail_count = self._breaker.fail_counter

        # Determine status based on circuit state and failure count
        if circuit_state == "open":
            status = IntegrationStatus.UNHEALTHY
            message = "Circuit breaker is open - service unavailable"
        elif circuit_state == "half-open":
            status = IntegrationStatus.DEGRADED
            message = "Circuit breaker is half-open - testing recovery"
        elif fail_count > 0:
            status = IntegrationStatus.DEGRADED
            message = f"Service has {fail_count} recent failures"
        else:
            status = IntegrationStatus.HEALTHY
            message = "Service is operating normally"

        return IntegrationHealth(
            name=self.name,
            status=status,
            circuit_state=circuit_state,
            fail_count=fail_count,
            last_failure=self._listener.last_failure,
            last_success=self._listener.last_success,
            message=message,
        )

    def reset_circuit(self) -> None:
        """Manually reset the circuit breaker to closed state.

        Use this after fixing the underlying issue with the external service.
        """
        self._breaker.close()
        logger.info(f"Circuit breaker for {self.name} manually reset to closed")

    @abstractmethod
    async def health_check(self) -> bool:
        """Perform a health check on the external service.

        Subclasses should implement this to verify connectivity
        to the external service.

        Returns:
            True if the service is healthy, False otherwise.
        """
        pass
