"""MikroTik RouterOS API integration."""

import asyncio
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import routeros_api
from app.core.config import settings
from app.core.logging import get_logger
from app.models.router import Router, RouterDevice, RouterLog
from app.models.subscription import Subscription, SubscriptionType

logger = get_logger(__name__)


class MikroTikAPI:
    """MikroTik RouterOS API client."""

    def __init__(self, router: Router):
        self.router = router
        self.connection = None
        self.api = None

    async def connect(self) -> bool:
        """Connect to MikroTik router."""
        try:
            # Run in thread pool since routeros_api is synchronous
            loop = asyncio.get_event_loop()
            self.connection = await loop.run_in_executor(
                None,
                self._connect_sync
            )
            return self.connection is not None
        except Exception as e:
            logger.error(f"Failed to connect to router {self.router.id}: {e}")
            return False

    def _connect_sync(self) -> Optional[routeros_api.RouterOsApiPool]:
        """Synchronous connection method."""
        try:
            connection = routeros_api.RouterOsApiPool(
                self.router.ip_address,
                username=self.router.username,
                password=self.router.password,
                port=self.router.port,
                use_ssl=False,
                timeout=settings.mikrotik_timeout
            )
            return connection
        except Exception as e:
            logger.error(f"RouterOS API connection failed: {e}")
            return None

    async def disconnect(self) -> None:
        """Disconnect from router."""
        if self.connection:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.connection.disconnect)
            except Exception as e:
                logger.error(f"Error disconnecting from router {self.router.id}: {e}")
            finally:
                self.connection = None

    async def get_system_info(self) -> Optional[Dict[str, Any]]:
        """Get system information from router."""
        if not self.connection:
            return None

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/system/resource').get()
            )
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Failed to get system info from router {self.router.id}: {e}")
            return None

    async def get_interface_list(self) -> List[Dict[str, Any]]:
        """Get list of interfaces."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/interface').get()
            )
            return result or []
        except Exception as e:
            logger.error(f"Failed to get interfaces from router {self.router.id}: {e}")
            return []

    async def get_hotspot_users(self) -> List[Dict[str, Any]]:
        """Get hotspot users."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/hotspot/user').get()
            )
            return result or []
        except Exception as e:
            logger.error(f"Failed to get hotspot users from router {self.router.id}: {e}")
            return []

    async def get_pppoe_users(self) -> List[Dict[str, Any]]:
        """Get PPPoE users."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ppp/secret').get()
            )
            return result or []
        except Exception as e:
            logger.error(f"Failed to get PPPoE users from router {self.router.id}: {e}")
            return []

    async def get_routing_table(self) -> List[Dict[str, Any]]:
        """Get routing table."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/route').get()
            )
            return result or []
        except Exception as e:
            logger.error(f"Failed to get routing table from router {self.router.id}: {e}")
            return []

    async def create_hotspot_user(
        self, 
        username: str, 
        password: str, 
        profile: str = "default",
        limit_uptime: str = "0",
        limit_bytes: str = "0"
    ) -> bool:
        """Create hotspot user."""
        if not self.connection:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/hotspot/user').add(
                    name=username,
                    password=password,
                    profile=profile,
                    limit_uptime=limit_uptime,
                    limit_bytes=limit_bytes
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create hotspot user {username}: {e}")
            return False

    async def create_pppoe_user(
        self, 
        username: str, 
        password: str, 
        profile: str = "default",
        service: str = "pppoe"
    ) -> bool:
        """Create PPPoE user."""
        if not self.connection:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ppp/secret').add(
                    name=username,
                    password=password,
                    profile=profile,
                    service=service
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create PPPoE user {username}: {e}")
            return False

    async def delete_hotspot_user(self, username: str) -> bool:
        """Delete hotspot user."""
        if not self.connection:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/hotspot/user').remove(
                    id=username
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete hotspot user {username}: {e}")
            return False

    async def delete_pppoe_user(self, username: str) -> bool:
        """Delete PPPoE user."""
        if not self.connection:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ppp/secret').remove(
                    id=username
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete PPPoE user {username}: {e}")
            return False

    async def enable_user(self, username: str, user_type: str) -> bool:
        """Enable user (hotspot or PPPoE)."""
        if not self.connection:
            return False

        try:
            resource_path = '/ip/hotspot/user' if user_type == 'hotspot' else '/ppp/secret'
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource(resource_path).set(
                    id=username,
                    disabled='no'
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to enable {user_type} user {username}: {e}")
            return False

    async def disable_user(self, username: str, user_type: str) -> bool:
        """Disable user (hotspot or PPPoE)."""
        if not self.connection:
            return False

        try:
            resource_path = '/ip/hotspot/user' if user_type == 'hotspot' else '/ppp/secret'
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource(resource_path).set(
                    id=username,
                    disabled='yes'
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to disable {user_type} user {username}: {e}")
            return False

    async def get_active_connections(self) -> List[Dict[str, Any]]:
        """Get active connections."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            # Get both hotspot and PPPoE active connections
            hotspot_result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/hotspot/active').get()
            )
            pppoe_result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ppp/active').get()
            )
            
            connections = []
            if hotspot_result:
                for conn in hotspot_result:
                    conn['type'] = 'hotspot'
                    connections.append(conn)
            if pppoe_result:
                for conn in pppoe_result:
                    conn['type'] = 'pppoe'
                    connections.append(conn)
            
            return connections
        except Exception as e:
            logger.error(f"Failed to get active connections from router {self.router.id}: {e}")
            return []

    async def get_user_usage(self, username: str, user_type: str) -> Optional[Dict[str, Any]]:
        """Get user usage statistics."""
        if not self.connection:
            return None

        try:
            loop = asyncio.get_event_loop()
            if user_type == 'hotspot':
                result = await loop.run_in_executor(
                    None,
                    lambda: self.connection.get_resource('/ip/hotspot/user').get(
                        name=username
                    )
                )
            else:  # PPPoE
                result = await loop.run_in_executor(
                    None,
                    lambda: self.connection.get_resource('/ppp/secret').get(
                        name=username
                    )
                )
            
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Failed to get usage for {user_type} user {username}: {e}")
            return None

    async def update_user_profile(
        self, 
        username: str, 
        user_type: str, 
        profile: str
    ) -> bool:
        """Update user profile."""
        if not self.connection:
            return False

        try:
            resource_path = '/ip/hotspot/user' if user_type == 'hotspot' else '/ppp/secret'
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource(resource_path).set(
                    id=username,
                    profile=profile
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update {user_type} user profile {username}: {e}")
            return False

    async def get_router_uptime(self) -> Optional[int]:
        """Get router uptime in seconds."""
        system_info = await self.get_system_info()
        if system_info and 'uptime' in system_info:
            return int(system_info['uptime'])
        return None

    async def get_router_load(self) -> Optional[Tuple[float, float, float]]:
        """Get router load averages (1min, 5min, 15min)."""
        system_info = await self.get_system_info()
        if system_info and 'cpu-load' in system_info:
            load_str = system_info['cpu-load']
            try:
                loads = [float(x) for x in load_str.split(',')]
                return tuple(loads[:3])  # Return first 3 values
            except (ValueError, IndexError):
                pass
        return None

    async def get_routeros_version(self) -> Optional[Dict[str, Any]]:
        """Get RouterOS version information."""
        if not self.connection:
            return None

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/system/package').call('print', {'where': 'name=system'})
            )
            
            if result:
                version_info = result[0] if isinstance(result, list) and result else result
                return {
                    'version': version_info.get('version', ''),
                    'build_time': version_info.get('build-time', ''),
                    'disabled': version_info.get('disabled', False)
                }
            
            return None
        except Exception as e:
            logger.error(f"Failed to get RouterOS version: {e}")
            return None

    async def execute_command(self, command: str) -> Optional[Any]:
        """Execute a RouterOS command."""
        if not self.connection:
            return None

        try:
            loop = asyncio.get_event_loop()
            
            # Parse command to extract resource and method
            parts = command.strip().split()
            if not parts:
                return None
                
            resource_path = parts[0]
            method = 'print'  # Default method
            params = {}
            
            # Simple command parsing - can be enhanced
            if len(parts) > 1:
                if '=' in command:
                    # This is a set command with parameters
                    method = 'set' if '/set' in command else 'add' if '/add' in command else 'print'
                    # Extract parameters
                    for part in parts[1:]:
                        if '=' in part:
                            key, value = part.split('=', 1)
                            params[key] = value
                elif 'print' in command:
                    method = 'print'
                elif 'add' in command:
                    method = 'add'
                elif 'set' in command:
                    method = 'set'
                elif 'remove' in command:
                    method = 'remove'
            
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource(resource_path).call(method, params)
            )
            
            return result
        except Exception as e:
            logger.error(f"Failed to execute command '{command}': {e}")
            raise

    async def execute_script(self, script: str) -> Optional[Any]:
        """Execute a RouterOS script."""
        if not self.connection:
            return None

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/system/script').call('run', {'source': script})
            )
            return result
        except Exception as e:
            logger.error(f"Failed to execute script: {e}")
            raise

    async def export_configuration(self) -> Optional[Dict[str, Any]]:
        """Export current router configuration."""
        if not self.connection:
            return None

        try:
            config_data = {}
            
            # Export various configuration sections
            sections = [
                '/system/identity',
                '/interface',
                '/ip/address',
                '/ip/pool',
                '/ip/hotspot',
                '/ppp/profile',
                '/ppp/secret',
                '/interface/pppoe-server/server',
                '/ip/firewall/filter',
                '/system/ntp/client'
            ]
            
            loop = asyncio.get_event_loop()
            
            for section in sections:
                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda s=section: self.connection.get_resource(s).call('print')
                    )
                    config_data[section.replace('/', '_')] = result
                except Exception as e:
                    logger.warning(f"Failed to export section {section}: {e}")
                    config_data[section.replace('/', '_')] = []
            
            return config_data
        except Exception as e:
            logger.error(f"Failed to export configuration: {e}")
            return None

    async def get_system_identity(self) -> Optional[str]:
        """Get system identity."""
        if not self.connection:
            return None

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/system/identity').call('print')
            )
            
            if result and isinstance(result, list) and result:
                return result[0].get('name', '')
            
            return None
        except Exception as e:
            logger.error(f"Failed to get system identity: {e}")
            return None

    async def get_ip_pools(self) -> List[Dict[str, Any]]:
        """Get IP pools."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/pool').call('print')
            )
            
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get IP pools: {e}")
            return []

    async def get_hotspots(self) -> List[Dict[str, Any]]:
        """Get hotspots."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/ip/hotspot').call('print')
            )
            
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get hotspots: {e}")
            return []

    async def get_pppoe_servers(self) -> List[Dict[str, Any]]:
        """Get PPPoE servers."""
        if not self.connection:
            return []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.connection.get_resource('/interface/pppoe-server/server').call('print')
            )
            
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get PPPoE servers: {e}")
            return []


class MikroTikService:
    """High-level MikroTik service for business logic."""

    def __init__(self):
        self.logger = get_logger(__name__)

    async def sync_router_status(self, router: Router) -> bool:
        """Sync router status and update database."""
        api = MikroTikAPI(router)
        
        try:
            connected = await api.connect()
            if not connected:
                router.status = RouterStatus.OFFLINE
                return False

            # Get system info
            system_info = await api.get_system_info()
            if system_info:
                router.status = RouterStatus.ONLINE
                router.uptime = int(system_info.get('uptime', 0))
                router.last_seen = datetime.utcnow()
            else:
                router.status = RouterStatus.ERROR

            return True
        except Exception as e:
            self.logger.error(f"Failed to sync router {router.id}: {e}")
            router.status = RouterStatus.ERROR
            return False
        finally:
            await api.disconnect()

    async def create_subscription_user(
        self, 
        router: Router, 
        subscription: Subscription
    ) -> bool:
        """Create user on router for subscription."""
        api = MikroTikAPI(router)
        
        try:
            connected = await api.connect()
            if not connected:
                return False

            if subscription.subscription_type == SubscriptionType.HOTSPOT:
                success = await api.create_hotspot_user(
                    username=subscription.username,
                    password=subscription.password,
                    profile="default"  # This should be based on the plan
                )
            else:  # PPPoE
                success = await api.create_pppoe_user(
                    username=subscription.username,
                    password=subscription.password,
                    profile="default"  # This should be based on the plan
                )

            return success
        except Exception as e:
            self.logger.error(f"Failed to create user for subscription {subscription.id}: {e}")
            return False
        finally:
            await api.disconnect()

    async def delete_subscription_user(
        self, 
        router: Router, 
        subscription: Subscription
    ) -> bool:
        """Delete user from router for subscription."""
        api = MikroTikAPI(router)
        
        try:
            connected = await api.connect()
            if not connected:
                return False

            if subscription.subscription_type == SubscriptionType.HOTSPOT:
                success = await api.delete_hotspot_user(subscription.username)
            else:  # PPPoE
                success = await api.delete_pppoe_user(subscription.username)

            return success
        except Exception as e:
            self.logger.error(f"Failed to delete user for subscription {subscription.id}: {e}")
            return False
        finally:
            await api.disconnect()

    async def get_subscription_usage(
        self, 
        router: Router, 
        subscription: Subscription
    ) -> Optional[Dict[str, Any]]:
        """Get usage statistics for subscription."""
        api = MikroTikAPI(router)
        
        try:
            connected = await api.connect()
            if not connected:
                return None

            user_type = 'hotspot' if subscription.subscription_type == SubscriptionType.HOTSPOT else 'pppoe'
            usage = await api.get_user_usage(subscription.username, user_type)
            
            return usage
        except Exception as e:
            self.logger.error(f"Failed to get usage for subscription {subscription.id}: {e}")
            return None
        finally:
            await api.disconnect()
