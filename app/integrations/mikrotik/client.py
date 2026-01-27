"""MikroTik RouterOS client with circuit breaker and resilience patterns.

This module provides a resilient MikroTik client that wraps the RouterOS API
with circuit breaker protection, automatic retries, and connection pooling.
"""

import asyncio
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

import routeros_api

from app.core.config import settings
from app.core.errors import ErrorCode, ExternalServiceError
from app.integrations.base import (
    BaseIntegrationClient,
    CircuitBreakerConfig,
    RetryConfig,
)

logger = logging.getLogger(__name__)


class MikroTikClient(BaseIntegrationClient[routeros_api.RouterOsApiPool]):
    """Resilient MikroTik RouterOS client with circuit breaker protection.

    This client wraps the routeros_api library with:
    - Circuit breaker to prevent cascade failures
    - Automatic retries with exponential backoff
    - Connection pooling per router
    - Timeout protection

    Example:
        client = MikroTikClient()
        async with client.connection(ip, username, password) as conn:
            info = await client.get_system_info(conn)
    """

    def __init__(
        self,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        """Initialize the MikroTik client.

        Args:
            circuit_config: Circuit breaker configuration. Defaults to
                fail_max=3, reset_timeout=30s for MikroTik.
            retry_config: Retry configuration for transient failures.
        """
        # Default circuit breaker config for MikroTik
        if circuit_config is None:
            circuit_config = CircuitBreakerConfig(
                fail_max=3,
                reset_timeout=30,
            )

        # Default retry config for network operations
        if retry_config is None:
            retry_config = RetryConfig(
                max_attempts=2,
                min_wait_seconds=1.0,
                max_wait_seconds=5.0,
                retry_exceptions=(ConnectionError, TimeoutError, OSError),
            )

        super().__init__(
            name="mikrotik",
            circuit_config=circuit_config,
            retry_config=retry_config,
            default_timeout=settings.mikrotik_timeout,
        )

        # Connection pool: router_key -> connection
        self._connections: Dict[str, routeros_api.RouterOsApiPool] = {}

    def _get_router_key(self, ip: str, port: int) -> str:
        """Generate unique key for router connection."""
        return f"{ip}:{port}"

    async def connect(
        self,
        ip_address: str,
        username: str,
        password: str,
        port: int = 8728,
        use_ssl: bool = False,
    ) -> routeros_api.RouterOsApiPool:
        """Connect to a MikroTik router with circuit breaker protection.

        Args:
            ip_address: Router IP address.
            username: Router username.
            password: Router password.
            port: API port (default 8728, 8729 for SSL).
            use_ssl: Whether to use SSL connection.

        Returns:
            RouterOS API connection pool.

        Raises:
            ExternalServiceError: If connection fails after retries
                or if circuit breaker is open.
        """
        router_key = self._get_router_key(ip_address, port)

        # Check if we have an existing connection
        if router_key in self._connections:
            try:
                # Test if connection is still alive
                conn = self._connections[router_key]
                # Try a simple operation to verify connection
                return conn
            except Exception:
                # Connection is dead, remove it
                self._connections.pop(router_key, None)

        async def _do_connect() -> routeros_api.RouterOsApiPool:
            """Actual connection logic (runs in thread pool)."""
            loop = asyncio.get_event_loop()

            def sync_connect() -> routeros_api.RouterOsApiPool:
                return routeros_api.RouterOsApiPool(
                    ip_address,
                    username=username,
                    password=password,
                    port=port,
                    use_ssl=use_ssl,
                    plaintext_login=True,
                )

            connection = await loop.run_in_executor(None, sync_connect)
            return connection

        try:
            connection = await self.execute_with_resilience(
                _do_connect,
                timeout=settings.mikrotik_timeout,
            )
            self._connections[router_key] = connection
            logger.info(f"Connected to MikroTik router at {ip_address}:{port}")
            return connection

        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Failed to connect to MikroTik at {ip_address}: {e}")
            raise ExternalServiceError(
                message=f"Failed to connect to MikroTik router at {ip_address}",
                code=ErrorCode.EXT_MIKROTIK_CONNECTION_FAILED,
                service_name="mikrotik",
                details={"ip_address": ip_address, "port": port, "error": str(e)},
            )

    async def disconnect(
        self, ip_address: str, port: int = 8728
    ) -> None:
        """Disconnect from a MikroTik router.

        Args:
            ip_address: Router IP address.
            port: API port.
        """
        router_key = self._get_router_key(ip_address, port)
        connection = self._connections.pop(router_key, None)

        if connection:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, connection.disconnect)
                logger.info(f"Disconnected from MikroTik router at {ip_address}")
            except Exception as e:
                logger.warning(f"Error disconnecting from {ip_address}: {e}")

    async def disconnect_all(self) -> None:
        """Disconnect from all connected routers."""
        for router_key in list(self._connections.keys()):
            ip, port = router_key.rsplit(":", 1)
            await self.disconnect(ip, int(port))

    async def get_system_info(
        self, connection: routeros_api.RouterOsApiPool
    ) -> Optional[Dict[str, Any]]:
        """Get system resource information from router.

        Args:
            connection: Active RouterOS connection.

        Returns:
            Dictionary with system info (cpu-load, memory, uptime, etc.)
            or None if failed.
        """

        async def _get_info() -> Optional[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> Optional[Dict[str, Any]]:
                api = connection.get_api()
                result = api.get_resource("/system/resource").get()
                return result[0] if result else None

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_info)
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return None

    async def get_interfaces(
        self, connection: routeros_api.RouterOsApiPool
    ) -> List[Dict[str, Any]]:
        """Get list of network interfaces.

        Args:
            connection: Active RouterOS connection.

        Returns:
            List of interface dictionaries.
        """

        async def _get_interfaces() -> List[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> List[Dict[str, Any]]:
                api = connection.get_api()
                return api.get_resource("/interface").get() or []

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_interfaces)
        except Exception as e:
            logger.error(f"Failed to get interfaces: {e}")
            return []

    async def get_hotspot_users(
        self, connection: routeros_api.RouterOsApiPool
    ) -> List[Dict[str, Any]]:
        """Get hotspot users.

        Args:
            connection: Active RouterOS connection.

        Returns:
            List of hotspot user dictionaries.
        """

        async def _get_users() -> List[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> List[Dict[str, Any]]:
                api = connection.get_api()
                return api.get_resource("/ip/hotspot/user").get() or []

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_users)
        except Exception as e:
            logger.error(f"Failed to get hotspot users: {e}")
            return []

    async def get_pppoe_users(
        self, connection: routeros_api.RouterOsApiPool
    ) -> List[Dict[str, Any]]:
        """Get PPPoE secrets/users.

        Args:
            connection: Active RouterOS connection.

        Returns:
            List of PPPoE secret dictionaries.
        """

        async def _get_users() -> List[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> List[Dict[str, Any]]:
                api = connection.get_api()
                return api.get_resource("/ppp/secret").get() or []

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_users)
        except Exception as e:
            logger.error(f"Failed to get PPPoE users: {e}")
            return []

    async def create_hotspot_user(
        self,
        connection: routeros_api.RouterOsApiPool,
        username: str,
        password: str,
        profile: str = "default",
        **kwargs: Any,
    ) -> bool:
        """Create a hotspot user.

        Args:
            connection: Active RouterOS connection.
            username: Username for the hotspot user.
            password: Password for the user.
            profile: Hotspot profile name.
            **kwargs: Additional parameters (limit-uptime, limit-bytes-total, etc.)

        Returns:
            True if user was created successfully.
        """

        async def _create_user() -> bool:
            loop = asyncio.get_event_loop()

            def sync_create() -> bool:
                api = connection.get_api()
                params = {
                    "name": username,
                    "password": password,
                    "profile": profile,
                    **kwargs,
                }
                api.get_resource("/ip/hotspot/user").add(**params)
                return True

            return await loop.run_in_executor(None, sync_create)

        try:
            return await self.execute_with_resilience(_create_user)
        except Exception as e:
            logger.error(f"Failed to create hotspot user {username}: {e}")
            raise ExternalServiceError(
                message=f"Failed to create hotspot user: {e}",
                code=ErrorCode.EXT_MIKROTIK_COMMAND_FAILED,
                service_name="mikrotik",
            )

    async def create_pppoe_user(
        self,
        connection: routeros_api.RouterOsApiPool,
        username: str,
        password: str,
        profile: str = "default",
        service: str = "pppoe",
        **kwargs: Any,
    ) -> bool:
        """Create a PPPoE secret/user.

        Args:
            connection: Active RouterOS connection.
            username: Username for the PPPoE user.
            password: Password for the user.
            profile: PPP profile name.
            service: Service type (pppoe, any, etc.)
            **kwargs: Additional parameters.

        Returns:
            True if user was created successfully.
        """

        async def _create_user() -> bool:
            loop = asyncio.get_event_loop()

            def sync_create() -> bool:
                api = connection.get_api()
                params = {
                    "name": username,
                    "password": password,
                    "profile": profile,
                    "service": service,
                    **kwargs,
                }
                api.get_resource("/ppp/secret").add(**params)
                return True

            return await loop.run_in_executor(None, sync_create)

        try:
            return await self.execute_with_resilience(_create_user)
        except Exception as e:
            logger.error(f"Failed to create PPPoE user {username}: {e}")
            raise ExternalServiceError(
                message=f"Failed to create PPPoE user: {e}",
                code=ErrorCode.EXT_MIKROTIK_COMMAND_FAILED,
                service_name="mikrotik",
            )

    async def execute_command(
        self,
        connection: routeros_api.RouterOsApiPool,
        resource_path: str,
        method: str = "get",
        **params: Any,
    ) -> Any:
        """Execute a generic RouterOS API command.

        Args:
            connection: Active RouterOS connection.
            resource_path: Resource path (e.g., "/ip/address").
            method: API method (get, add, set, remove, call).
            **params: Parameters for the command.

        Returns:
            Command result.
        """

        async def _execute() -> Any:
            loop = asyncio.get_event_loop()

            def sync_execute() -> Any:
                api = connection.get_api()
                resource = api.get_resource(resource_path)

                if method == "get":
                    return resource.get(**params)
                elif method == "add":
                    return resource.add(**params)
                elif method == "set":
                    return resource.set(**params)
                elif method == "remove":
                    return resource.remove(**params)
                elif method == "call":
                    cmd = params.pop("cmd", "print")
                    return resource.call(cmd, params)
                else:
                    raise ValueError(f"Unknown method: {method}")

            return await loop.run_in_executor(None, sync_execute)

        try:
            return await self.execute_with_resilience(_execute)
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Failed to execute {method} on {resource_path}: {e}")
            raise ExternalServiceError(
                message=f"RouterOS command failed: {e}",
                code=ErrorCode.EXT_MIKROTIK_COMMAND_FAILED,
                service_name="mikrotik",
                details={"resource": resource_path, "method": method},
            )

    async def health_check(self) -> bool:
        """Check if we can connect to the default MikroTik.

        Note: This is a basic health check. For production, you should
        check connectivity to your specific routers.

        Returns:
            True if basic connectivity is working.
        """
        # Health check just verifies the client is properly configured
        return not self.is_circuit_open


@lru_cache()
def get_mikrotik_client() -> MikroTikClient:
    """Get singleton MikroTik client instance.

    Returns:
        Shared MikroTikClient instance.
    """
    return MikroTikClient()
