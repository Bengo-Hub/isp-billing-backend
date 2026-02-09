"""MikroTik RouterOS client with circuit breaker and resilience patterns.

This module provides a resilient MikroTik client that wraps the RouterOS API
with circuit breaker protection, automatic retries, and connection pooling.
"""

import asyncio
import logging
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import routeros_api

if TYPE_CHECKING:
    from app.models.router import Router

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
        # Include OSError for socket errors (WinError 10038, etc.) and increase max attempts
        if retry_config is None:
            retry_config = RetryConfig(
                max_attempts=3,
                min_wait_seconds=1.0,
                max_wait_seconds=10.0,
                retry_exceptions=(ConnectionError, TimeoutError, OSError, IOError),
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

        # Always create a fresh connection to avoid stale connection issues
        # The RouterOsApiPool uses lazy connection, so we can't reliably test
        # if an existing connection is still valid without executing a command
        if router_key in self._connections:
            # Remove any existing connection to ensure fresh credentials are used
            try:
                old_conn = self._connections.pop(router_key, None)
                if old_conn:
                    old_conn.disconnect()
            except Exception:
                pass  # Ignore errors when cleaning up old connection

        async def _do_connect() -> routeros_api.RouterOsApiPool:
            """Actual connection logic (runs in thread pool)."""
            loop = asyncio.get_event_loop()

            def sync_connect() -> routeros_api.RouterOsApiPool:
                pool = routeros_api.RouterOsApiPool(
                    ip_address,
                    username=username,
                    password=password,
                    port=port,
                    use_ssl=use_ssl,
                    plaintext_login=True,
                )
                # IMPORTANT: Force immediate connection test to detect stale sockets
                # RouterOsApiPool uses lazy connection, so we need to trigger it now
                # This ensures we fail fast if the connection is bad
                try:
                    api = pool.get_api()
                    # Execute a simple command to verify connection is working
                    api.get_resource("/system/identity").get()
                except Exception as e:
                    # Close the pool and re-raise
                    try:
                        pool.disconnect()
                    except Exception:
                        pass
                    raise e
                return pool

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

    async def get_active_connections(
        self, connection: routeros_api.RouterOsApiPool
    ) -> List[Dict[str, Any]]:
        """Get active hotspot and PPPoE connections.

        Args:
            connection: Active RouterOS connection.

        Returns:
            List of active connection dictionaries with 'type' field.
        """

        async def _get_connections() -> List[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> List[Dict[str, Any]]:
                api = connection.get_api()
                connections = []

                # Get hotspot active connections
                try:
                    hotspot_active = api.get_resource("/ip/hotspot/active").get() or []
                    for conn in hotspot_active:
                        conn["type"] = "hotspot"
                        connections.append(conn)
                except Exception as e:
                    logger.debug(f"No hotspot active connections: {e}")

                # Get PPPoE active connections
                try:
                    pppoe_active = api.get_resource("/ppp/active").get() or []
                    for conn in pppoe_active:
                        conn["type"] = "pppoe"
                        connections.append(conn)
                except Exception as e:
                    logger.debug(f"No PPPoE active connections: {e}")

                return connections

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_connections)
        except Exception as e:
            logger.error(f"Failed to get active connections: {e}")
            return []

    async def disable_user(
        self,
        connection: routeros_api.RouterOsApiPool,
        username: str,
        user_type: str = "hotspot",
    ) -> bool:
        """Disable a hotspot or PPPoE user.

        Args:
            connection: Active RouterOS connection.
            username: Username to disable.
            user_type: User type ('hotspot' or 'pppoe').

        Returns:
            True if user was disabled successfully.
        """

        async def _disable_user() -> bool:
            loop = asyncio.get_event_loop()

            def sync_disable() -> bool:
                api = connection.get_api()
                resource_path = "/ip/hotspot/user" if user_type == "hotspot" else "/ppp/secret"
                resource = api.get_resource(resource_path)

                # Find user by name and disable
                users = resource.get(name=username)
                if users:
                    user_id = users[0].get("id")
                    if user_id:
                        resource.set(id=user_id, disabled="yes")
                        return True
                return False

            return await loop.run_in_executor(None, sync_disable)

        try:
            return await self.execute_with_resilience(_disable_user)
        except Exception as e:
            logger.error(f"Failed to disable {user_type} user {username}: {e}")
            return False

    async def get_hotspot_servers(
        self, connection: routeros_api.RouterOsApiPool
    ) -> List[Dict[str, Any]]:
        """Get hotspot servers.

        Args:
            connection: Active RouterOS connection.

        Returns:
            List of hotspot server dictionaries.
        """

        async def _get_servers() -> List[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> List[Dict[str, Any]]:
                api = connection.get_api()
                return api.get_resource("/ip/hotspot").get() or []

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_servers)
        except Exception as e:
            logger.error(f"Failed to get hotspot servers: {e}")
            return []

    async def get_hotspot_profiles(
        self, connection: routeros_api.RouterOsApiPool
    ) -> List[Dict[str, Any]]:
        """Get hotspot profiles.

        Args:
            connection: Active RouterOS connection.

        Returns:
            List of hotspot profile dictionaries.
        """

        async def _get_profiles() -> List[Dict[str, Any]]:
            loop = asyncio.get_event_loop()

            def sync_get() -> List[Dict[str, Any]]:
                api = connection.get_api()
                return api.get_resource("/ip/hotspot/profile").get() or []

            return await loop.run_in_executor(None, sync_get)

        try:
            return await self.execute_with_resilience(_get_profiles)
        except Exception as e:
            logger.error(f"Failed to get hotspot profiles: {e}")
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

    def _parse_cli_command(self, command: str) -> tuple:
        """Parse a CLI-style command into resource_path, method, and params.

        Handles commands like:
            /interface/bridge/add name=codevertex-bridge
            /ip/address/add address=192.168.1.1/24 interface=ether1
            /system/identity/set name=MyRouter
            /ip/service/set telnet disabled=yes  (item identifier without =)
            /ip/hotspot/profile/set default login-by=http-chap

        Returns:
            tuple: (resource_path, method, params_dict)
        """
        import re

        # Split command into path and parameters
        parts = command.strip().split(' ', 1)
        path_with_method = parts[0]
        param_string = parts[1] if len(parts) > 1 else ""

        # Extract method from the end of the path
        # Common methods: add, set, remove, print, get, enable, disable
        method_keywords = ['add', 'set', 'remove', 'print', 'get', 'enable', 'disable', 'reset', 'sign']
        method = "get"  # default
        resource_path = path_with_method

        # Check if the last segment is a method keyword
        path_segments = path_with_method.rstrip('/').split('/')
        if path_segments and path_segments[-1] in method_keywords:
            method = path_segments[-1]
            resource_path = '/'.join(path_segments[:-1])

        # Parse parameters from the param string
        # Note: We keep hyphenated keys (address-pool) as-is since routeros-api
        # accepts them via **dict unpacking even though Python keywords can't have hyphens
        params = {}
        item_identifier = None

        if param_string:
            # For 'set' commands, check if first argument is an item identifier (no '=')
            # e.g., "/ip/service/set telnet disabled=yes" - 'telnet' is the item identifier
            if method == 'set':
                first_space = param_string.find(' ')
                if first_space > 0:
                    first_part = param_string[:first_space]
                    rest_of_params = param_string[first_space + 1:]
                    # If first part doesn't contain '=', it's an item identifier
                    if '=' not in first_part:
                        item_identifier = first_part
                        param_string = rest_of_params
                elif '=' not in param_string:
                    # The whole param_string is just an item identifier with no properties
                    item_identifier = param_string
                    param_string = ""

            # Match key=value pairs, handling quoted values
            pattern = r'(\S+?)=(?:"([^"]+)"|\'([^\']+)\'|(\S+))'
            matches = re.findall(pattern, param_string)
            for match in matches:
                key = match[0]  # Keep original key (with hyphens if any)
                value = match[1] or match[2] or match[3]  # Pick the matched group
                params[key] = value

        # Store item identifier for set operations
        if item_identifier:
            params['_item_identifier'] = item_identifier

        return resource_path, method, params

    async def execute_command(
        self,
        connection: routeros_api.RouterOsApiPool,
        command_or_path: str,
        method: str = None,
        **params: Any,
    ) -> Any:
        """Execute a generic RouterOS API command.

        Supports two calling conventions:
        1. CLI-style command string: execute_command(conn, "/interface/bridge/add name=test")
        2. Separate path and method: execute_command(conn, "/interface/bridge", "add", name="test")

        Args:
            connection: Active RouterOS connection.
            command_or_path: Full CLI command string OR resource path.
            method: API method (get, add, set, remove, call). Auto-detected if None.
            **params: Parameters for the command (used if method is specified).

        Returns:
            Command result.
        """
        # Detect if this is a CLI-style command (contains space or method keyword at end)
        if method is None and (' ' in command_or_path or any(
            command_or_path.rstrip('/').endswith(f'/{m}') for m in ['add', 'set', 'remove', 'print', 'enable', 'disable']
        )):
            # Parse CLI-style command
            resource_path, parsed_method, parsed_params = self._parse_cli_command(command_or_path)
            method = parsed_method
            params = parsed_params
        else:
            # Traditional calling convention
            resource_path = command_or_path
            method = method or "get"

        async def _execute() -> Any:
            loop = asyncio.get_event_loop()

            def sync_execute() -> Any:
                api = connection.get_api()
                resource = api.get_resource(resource_path)

                # Handle item identifier for set operations
                # e.g., "/ip/service/set telnet disabled=yes" where 'telnet' is the item
                item_identifier = params.pop('_item_identifier', None)

                if method == "get" or method == "print":
                    return resource.get(**params)
                elif method == "add":
                    return resource.add(**params)
                elif method == "set":
                    if item_identifier:
                        # Find item by name first, then set properties
                        items = resource.get(name=item_identifier)
                        if items:
                            item_id = items[0].get('id')
                            if item_id:
                                return resource.set(id=item_id, **params)
                        # If item not found by 'name', try by 'service' (for /ip/service)
                        items = resource.get()
                        for item in items:
                            if item.get('name') == item_identifier or item.get('service') == item_identifier:
                                item_id = item.get('id')
                                if item_id:
                                    return resource.set(id=item_id, **params)
                        raise ValueError(f"Item '{item_identifier}' not found")
                    return resource.set(**params)
                elif method == "remove":
                    if item_identifier:
                        # Find item by name first
                        items = resource.get(name=item_identifier)
                        if items:
                            item_id = items[0].get('id')
                            if item_id:
                                return resource.remove(id=item_id)
                    return resource.remove(**params)
                elif method == "enable":
                    # Enable is typically: set .id=* disabled=no
                    return resource.set(disabled="no", **params)
                elif method == "disable":
                    # Disable is typically: set .id=* disabled=yes
                    return resource.set(disabled="yes", **params)
                elif method == "sign":
                    # Action command: /certificate/sign number=cert-name
                    # Uses resource.call() which sends the correct API command word
                    return resource.call('sign', params)
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
                details={"resource": resource_path, "method": method, "params": params},
            )

    async def sync_router_status(self, router: "Router") -> bool:
        """Sync router status by connecting and getting system info.

        Args:
            router: Router model instance to sync.

        Returns:
            True if status was successfully synced.
        """
        from app.models.router import RouterStatus

        connection = None
        try:
            # Connect to router
            connection = await self.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            # Get system info to verify connection and get uptime
            system_info = await self.get_system_info(connection)

            if system_info:
                # Update router status
                router.status = RouterStatus.ONLINE
                router.last_seen = datetime.utcnow()

                # Parse uptime from system info (format: "1w2d3h4m5s" or similar)
                uptime_str = system_info.get("uptime", "0s")
                router.uptime = self._parse_uptime(uptime_str)

                # RouterOS version (e.g., "7.18.2 (stable)")
                router.routeros_version = system_info.get("version")

                # Board/Model name (e.g., "RB951Ui-2HnD")
                router.board_name = system_info.get("board-name")

                # Architecture (e.g., "mipsbe")
                router.architecture = system_info.get("architecture-name")

                # CPU count
                cpu_count = system_info.get("cpu-count")
                if cpu_count is not None:
                    router.cpu_count = int(cpu_count)

                # CPU frequency (e.g., "600MHz" -> 600)
                router.cpu_frequency = self._parse_frequency(
                    system_info.get("cpu-frequency", "")
                )

                # CPU load (e.g., "6%" -> 6)
                router.cpu_load = self._parse_percentage(
                    system_info.get("cpu-load", "")
                )

                # Memory - Total (e.g., "128.0MiB" -> bytes)
                router.total_memory = self._parse_size(
                    system_info.get("total-memory", "")
                )

                # Memory - Free (e.g., "81.1MiB" -> bytes)
                router.free_memory = self._parse_size(
                    system_info.get("free-memory", "")
                )

                # HDD/Storage - Total (e.g., "128.0MiB" -> bytes)
                router.total_hdd_space = self._parse_size(
                    system_info.get("total-hdd-space", "")
                )

                # HDD/Storage - Free (e.g., "109.3MiB" -> bytes)
                router.free_hdd_space = self._parse_size(
                    system_info.get("free-hdd-space", "")
                )

                logger.info(
                    f"Router {router.name} ({router.ip_address}) synced: "
                    f"version={router.routeros_version}, model={router.board_name}, "
                    f"uptime={router.uptime}s, cpu={router.cpu_load}%, "
                    f"memory={router.free_memory}/{router.total_memory} bytes"
                )
                return True
            else:
                router.status = RouterStatus.OFFLINE
                logger.warning(
                    f"Router {router.name} ({router.ip_address}) - "
                    f"could not get system info"
                )
                return False

        except Exception as e:
            from app.models.router import RouterStatus
            router.status = RouterStatus.OFFLINE
            logger.error(
                f"Failed to sync router {router.name} ({router.ip_address}): {e}"
            )
            return False

        finally:
            # Always disconnect to avoid connection leaks
            if connection:
                await self.disconnect(router.ip_address, router.port)

    def _parse_uptime(self, uptime_str: str) -> int:
        """Parse MikroTik uptime string to seconds.

        Args:
            uptime_str: Uptime string (e.g., "1w2d3h4m5s").

        Returns:
            Uptime in seconds.
        """
        import re

        total_seconds = 0

        # Match weeks, days, hours, minutes, seconds
        patterns = [
            (r"(\d+)w", 7 * 24 * 60 * 60),  # weeks
            (r"(\d+)d", 24 * 60 * 60),       # days
            (r"(\d+)h", 60 * 60),            # hours
            (r"(\d+)m", 60),                  # minutes
            (r"(\d+)s", 1),                   # seconds
        ]

        for pattern, multiplier in patterns:
            match = re.search(pattern, uptime_str)
            if match:
                total_seconds += int(match.group(1)) * multiplier

        return total_seconds

    def _parse_size(self, size_str: str) -> int:
        """Parse MikroTik size string to bytes.

        Args:
            size_str: Size string (e.g., "128.0MiB", "1.5GiB").

        Returns:
            Size in bytes.
        """
        import re

        if not size_str:
            return 0

        # Extract number and unit
        match = re.match(r'([\d.]+)\s*([KMGT]i?B?)?', str(size_str), re.IGNORECASE)
        if not match:
            return 0

        value = float(match.group(1))
        unit = (match.group(2) or '').upper()

        # Convert to bytes based on unit
        multipliers = {
            '': 1,
            'B': 1,
            'KIB': 1024,
            'KB': 1024,
            'K': 1024,
            'MIB': 1024 ** 2,
            'MB': 1024 ** 2,
            'M': 1024 ** 2,
            'GIB': 1024 ** 3,
            'GB': 1024 ** 3,
            'G': 1024 ** 3,
            'TIB': 1024 ** 4,
            'TB': 1024 ** 4,
            'T': 1024 ** 4,
        }

        return int(value * multipliers.get(unit, 1))

    def _parse_frequency(self, freq_str: str) -> int:
        """Parse MikroTik frequency string to MHz.

        Args:
            freq_str: Frequency string (e.g., "600MHz", "1.2GHz").

        Returns:
            Frequency in MHz.
        """
        import re

        if not freq_str:
            return 0

        match = re.match(r'([\d.]+)\s*([GM])?Hz', str(freq_str), re.IGNORECASE)
        if not match:
            return 0

        value = float(match.group(1))
        unit = (match.group(2) or '').upper()

        if unit == 'G':
            return int(value * 1000)  # GHz to MHz
        return int(value)  # Already MHz

    def _parse_percentage(self, pct_str: str) -> int:
        """Parse MikroTik percentage string.

        Args:
            pct_str: Percentage string (e.g., "6%", "100%").

        Returns:
            Percentage as integer.
        """
        import re

        if not pct_str:
            return 0

        match = re.match(r'(\d+)', str(pct_str))
        if match:
            return int(match.group(1))
        return 0

    async def create_subscription_user(
        self,
        router: "Router",
        subscription: Any,
    ) -> bool:
        """Create a user on the router for a subscription.

        Args:
            router: Router model instance.
            subscription: Subscription model instance with username, password, subscription_type.

        Returns:
            True if user was created successfully.
        """
        from app.models.subscription import SubscriptionType

        try:
            # Connect to router
            connection = await self.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            # Create user based on subscription type
            if subscription.subscription_type == SubscriptionType.HOTSPOT:
                success = await self.create_hotspot_user(
                    connection=connection,
                    username=subscription.username,
                    password=subscription.password,
                    profile="default",
                )
            elif subscription.subscription_type == SubscriptionType.PPPOE:
                success = await self.create_pppoe_user(
                    connection=connection,
                    username=subscription.username,
                    password=subscription.password,
                    profile="default",
                )
            else:
                logger.error(f"Unknown subscription type: {subscription.subscription_type}")
                return False

            if success:
                logger.info(
                    f"Created {subscription.subscription_type.value} user "
                    f"{subscription.username} on router {router.name}"
                )
            return success

        except Exception as e:
            logger.error(
                f"Failed to create user {subscription.username} on router "
                f"{router.name}: {e}"
            )
            return False

    async def delete_subscription_user(
        self,
        router: "Router",
        subscription: Any,
    ) -> bool:
        """Delete a user from the router for a subscription.

        Args:
            router: Router model instance.
            subscription: Subscription model instance with username, subscription_type.

        Returns:
            True if user was deleted successfully.
        """
        from app.models.subscription import SubscriptionType

        try:
            # Connect to router
            connection = await self.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            # Determine resource path based on subscription type
            if subscription.subscription_type == SubscriptionType.HOTSPOT:
                resource_path = "/ip/hotspot/user"
            elif subscription.subscription_type == SubscriptionType.PPPOE:
                resource_path = "/ppp/secret"
            else:
                logger.error(f"Unknown subscription type: {subscription.subscription_type}")
                return False

            # Find and remove the user
            users = await self.execute_command(
                connection=connection,
                resource_path=resource_path,
                method="get",
            )

            user_to_delete = None
            for user in users:
                if user.get("name") == subscription.username:
                    user_to_delete = user
                    break

            if user_to_delete:
                await self.execute_command(
                    connection=connection,
                    resource_path=resource_path,
                    method="remove",
                    id=user_to_delete.get("id") or user_to_delete.get(".id"),
                )
                logger.info(
                    f"Deleted {subscription.subscription_type.value} user "
                    f"{subscription.username} from router {router.name}"
                )
                return True
            else:
                logger.warning(
                    f"User {subscription.username} not found on router {router.name}"
                )
                return True  # Return True as user doesn't exist (desired state)

        except Exception as e:
            logger.error(
                f"Failed to delete user {subscription.username} from router "
                f"{router.name}: {e}"
            )
            return False

    async def verify_bootstrap_script(
        self,
        router: "Router",
        expected_identity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify the bootstrap script exists on the router and matches expected identity.

        Args:
            router: Router model instance.
            expected_identity: Expected router identity in the script (defaults to router.name).

        Returns:
            Dict with verification results:
                - script_exists: bool
                - script_content: str or None
                - identity_matches: bool
                - identity_in_script: str or None
        """
        expected_identity = expected_identity or router.name

        try:
            # Connect to router
            connection = await self.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            # Get file list and find codevertex.rsc
            files = await self.execute_command(
                connection=connection,
                resource_path="/file",
                method="get",
            )

            script_file = None
            for f in files:
                if f.get("name") == "codevertex.rsc":
                    script_file = f
                    break

            if not script_file:
                logger.warning(f"Bootstrap script not found on router {router.name}")
                return {
                    "script_exists": False,
                    "script_content": None,
                    "identity_matches": False,
                    "identity_in_script": None,
                }

            # Get script contents
            script_content = script_file.get("contents", "")

            # Parse identity from script content
            # Look for: /system/identity/set name=MikroTik1
            import re
            identity_match = re.search(
                r'/system/identity/set\s+name=([^\s\n]+)',
                script_content
            )
            identity_in_script = identity_match.group(1) if identity_match else None

            identity_matches = identity_in_script == expected_identity

            logger.info(
                f"Bootstrap script verified on {router.name}: "
                f"identity_matches={identity_matches}"
            )

            return {
                "script_exists": True,
                "script_content": script_content,
                "identity_matches": identity_matches,
                "identity_in_script": identity_in_script,
            }

        except Exception as e:
            logger.error(f"Failed to verify bootstrap script on {router.name}: {e}")
            return {
                "script_exists": False,
                "script_content": None,
                "identity_matches": False,
                "identity_in_script": None,
                "error": str(e),
            }

    async def cleanup_provisioning(
        self,
        router: "Router",
        remove_script: bool = True,
        remove_configurations: bool = False,
    ) -> Dict[str, Any]:
        """Clean up provisioning artifacts from the router.

        This should be called before deleting a router to remove:
        - codevertex.rsc script file
        - Optionally: hotspot, pppoe, bridge configurations created by Codevertex

        Args:
            router: Router model instance.
            remove_script: Whether to remove codevertex.rsc file.
            remove_configurations: Whether to remove Codevertex-created configurations.

        Returns:
            Dict with cleanup results.
        """
        results = {
            "script_removed": False,
            "configurations_removed": False,
            "errors": [],
        }

        try:
            # Connect to router
            connection = await self.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            # Remove bootstrap script
            if remove_script:
                try:
                    # Find and remove codevertex.rsc
                    files = await self.execute_command(
                        connection=connection,
                        resource_path="/file",
                        method="get",
                    )
                    for f in files:
                        if f.get("name") == "codevertex.rsc":
                            await self.execute_command(
                                connection=connection,
                                resource_path="/file",
                                method="remove",
                                id=f.get("id") or f.get(".id"),
                            )
                            results["script_removed"] = True
                            logger.info(f"Removed codevertex.rsc from router {router.name}")
                            break
                except Exception as e:
                    results["errors"].append(f"Failed to remove script: {e}")
                    logger.warning(f"Failed to remove script from {router.name}: {e}")

            # Remove Codevertex configurations
            if remove_configurations:
                try:
                    # Remove hotspot with codevertex prefix
                    hotspots = await self.execute_command(
                        connection=connection,
                        resource_path="/ip/hotspot",
                        method="get",
                    )
                    for hs in hotspots:
                        if hs.get("name", "").startswith("codevertex"):
                            await self.execute_command(
                                connection=connection,
                                resource_path="/ip/hotspot",
                                method="remove",
                                id=hs.get("id") or hs.get(".id"),
                            )

                    # Remove PPPoE server with codevertex prefix
                    pppoe_servers = await self.execute_command(
                        connection=connection,
                        resource_path="/interface/pppoe-server/server",
                        method="get",
                    )
                    for srv in pppoe_servers:
                        if srv.get("service-name", "").startswith("codevertex"):
                            await self.execute_command(
                                connection=connection,
                                resource_path="/interface/pppoe-server/server",
                                method="remove",
                                id=srv.get("id") or srv.get(".id"),
                            )

                    # Remove bridge with codevertex prefix
                    bridges = await self.execute_command(
                        connection=connection,
                        resource_path="/interface/bridge",
                        method="get",
                    )
                    for br in bridges:
                        if br.get("name", "").startswith("codevertex"):
                            await self.execute_command(
                                connection=connection,
                                resource_path="/interface/bridge",
                                method="remove",
                                id=br.get("id") or br.get(".id"),
                            )

                    # Remove IP pool with codevertex prefix
                    pools = await self.execute_command(
                        connection=connection,
                        resource_path="/ip/pool",
                        method="get",
                    )
                    for pool in pools:
                        if pool.get("name", "").startswith("codevertex"):
                            await self.execute_command(
                                connection=connection,
                                resource_path="/ip/pool",
                                method="remove",
                                id=pool.get("id") or pool.get(".id"),
                            )

                    results["configurations_removed"] = True
                    logger.info(f"Removed Codevertex configurations from router {router.name}")
                except Exception as e:
                    results["errors"].append(f"Failed to remove configurations: {e}")
                    logger.warning(f"Failed to remove configurations from {router.name}: {e}")

            return results

        except Exception as e:
            logger.error(f"Failed to cleanup provisioning on {router.name}: {e}")
            results["errors"].append(f"Connection failed: {e}")
            return results

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
