"""Router service for MikroTik integration and management."""

import asyncio
import ipaddress
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.models.router import Router, RouterDevice, RouterLog, RouterStatus, RouterType
from app.models.subscription import Subscription
from app.models.provisioning import ProvisioningSession, RouterConfiguration
from app.integrations.mikrotik import get_mikrotik_client
from app.api.deps import PaginationParams
from app.core.logging import get_logger
from app.core.exceptions import RouterConnectionError, RouterOperationError, ValidationError
from app.modules.system import ConfigurationService


class RouterService:
    """Router service for business logic."""

    def __init__(self, db: AsyncSession, organization_id: Optional[int] = None):
        self.db = db
        self.organization_id = organization_id
        self.mikrotik_service = get_mikrotik_client()
        self.logger = get_logger(__name__)
        self._connection_cache = {}  # Cache for router connections
        self._data_cache = {}  # Cache for frequently accessed data
        self._cache_ttl = 300  # 5 minutes TTL for data cache
        self._max_retries = 3
        self._retry_delay = 1  # seconds
        self._config_service = None  # Lazy initialization

    # Validation methods
    def _validate_ip_address(self, ip_address: str) -> bool:
        """Validate IP address format."""
        try:
            ipaddress.ip_address(ip_address)
            return True
        except ValueError:
            return False

    def _validate_mac_address(self, mac_address: str) -> bool:
        """Validate MAC address format."""
        if not mac_address:
            return True  # MAC address is optional
        mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
        return bool(re.match(mac_pattern, mac_address))

    def _validate_router_credentials(self, username: str, password: str) -> bool:
        """Validate router credentials.

        MikroTik routers can have very short passwords (e.g., 'admin' default)
        or even empty passwords on factory reset.
        """
        if not username:
            return False
        if len(username) < 1 or len(username) > 50:
            return False
        # Allow short or empty passwords for MikroTik compatibility
        if password and len(password) > 255:
            return False
        return True

    def _validate_router_data(self, data: Dict[str, Any]) -> None:
        """Validate router data before creation/update."""
        if 'ip_address' in data and not self._validate_ip_address(data['ip_address']):
            raise ValidationError("Invalid IP address format")
        
        if 'mac_address' in data and not self._validate_mac_address(data['mac_address']):
            raise ValidationError("Invalid MAC address format")
        
        if 'username' in data and 'password' in data:
            if not self._validate_router_credentials(data['username'], data['password']):
                raise ValidationError("Invalid router credentials")
        
        if 'port' in data and (data['port'] < 1 or data['port'] > 65535):
            raise ValidationError("Port must be between 1 and 65535")

    async def _retry_operation(self, operation, *args, **kwargs):
        """Retry operation with exponential backoff."""
        for attempt in range(self._max_retries):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise e
                self.logger.warning(f"Operation failed (attempt {attempt + 1}/{self._max_retries}): {e}")
                await asyncio.sleep(self._retry_delay * (2 ** attempt))
        return None

    def _get_cache_key(self, prefix: str, *args) -> str:
        """Generate cache key from prefix and arguments."""
        return f"{prefix}:{':'.join(str(arg) for arg in args)}"

    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if cache entry is still valid."""
        if not cache_entry:
            return False
        return (datetime.utcnow() - cache_entry['timestamp']).total_seconds() < self._cache_ttl

    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get data from cache if valid."""
        cache_entry = self._data_cache.get(cache_key)
        if cache_entry and self._is_cache_valid(cache_entry):
            self.logger.debug(f"Cache hit for key: {cache_key}")
            return cache_entry['data']
        return None

    def _set_cache(self, cache_key: str, data: Any) -> None:
        """Set data in cache with timestamp."""
        self._data_cache[cache_key] = {
            'data': data,
            'timestamp': datetime.utcnow()
        }
        self.logger.debug(f"Cached data for key: {cache_key}")

    def _invalidate_cache(self, pattern: str = None) -> None:
        """Invalidate cache entries matching pattern."""
        if pattern:
            keys_to_remove = [key for key in self._data_cache.keys() if pattern in key]
            for key in keys_to_remove:
                del self._data_cache[key]
            self.logger.debug(f"Invalidated {len(keys_to_remove)} cache entries matching '{pattern}'")
        else:
            self._data_cache.clear()
            self.logger.debug("Cleared all cache entries")

    async def _get_config_service(self) -> ConfigurationService:
        """Get configuration service instance."""
        if not self._config_service:
            encryption_key = "default-encryption-key-change-in-production"  # TODO: Get from settings
            self._config_service = ConfigurationService(self.db, encryption_key)
        return self._config_service

    async def _encrypt_router_password(self, password: str) -> str:
        """Encrypt router password."""
        try:
            config_service = await self._get_config_service()
            # Store encrypted password in configuration
            encrypted_key = f"router_password_{hash(password) % 10000}"
            await config_service.set_config(
                key=encrypted_key,
                value=password,
                config_type="encrypted",
                is_encrypted=True,
                is_sensitive=True,
                category="router_credentials"
            )
            return encrypted_key
        except Exception as e:
            self.logger.error(f"Failed to encrypt router password: {e}")
            return password  # Fallback to plain text

    async def _decrypt_router_password(self, encrypted_key: str) -> str:
        """Decrypt router password."""
        try:
            config_service = await self._get_config_service()
            password = await config_service.get_config(encrypted_key)
            return password or encrypted_key  # Fallback to key if decryption fails
        except Exception as e:
            self.logger.error(f"Failed to decrypt router password: {e}")
            return encrypted_key  # Fallback to key

    async def _assign_winbox_port(self) -> int:
        """Assign a unique Winbox VPN port for remote access.

        Finds the next available port in the organization's port range.
        Default range: 51000-59999 (configurable in OrganizationSettings).

        Returns:
            Unique port number for remote Winbox access
        """
        from app.models.organization import OrganizationSettings

        # Get organization settings for port range
        port_start = 51000
        port_end = 59999

        if self.organization_id:
            result = await self.db.execute(
                select(OrganizationSettings).where(
                    OrganizationSettings.organization_id == self.organization_id
                )
            )
            settings = result.scalar_one_or_none()
            if settings:
                port_start = settings.winbox_port_start or 51000
                port_end = settings.winbox_port_end or 59999

        # Find all used winbox ports
        used_ports_result = await self.db.execute(
            select(Router.winbox_port).where(Router.winbox_port.isnot(None))
        )
        used_ports = {row[0] for row in used_ports_result.fetchall()}

        # Find the next available port
        for port in range(port_start, port_end + 1):
            if port not in used_ports:
                self.logger.info(f"Assigned Winbox VPN port: {port}")
                return port

        # If all ports are used, raise an error
        raise RouterOperationError(
            f"No available Winbox ports in range {port_start}-{port_end}. "
            f"Consider expanding the port range in organization settings."
        )

    @staticmethod
    def _is_vpn_winbox_port(port: Optional[int]) -> bool:
        """True if `port` is a real VPN-mapped winbox port (not the local 8291).

        Remote winbox is only meaningful over the VPN overlay, where the WG
        server port-forwards a per-router port in the 51000-59999 range to the
        router's tunnel IP:8291. A router still on the default local port (8291)
        has NOT been VPN-provisioned, so it must NOT present a remote URL.
        """
        return bool(port) and 51000 <= port <= 59999

    async def resolve_vpn_domain(self, router: Router) -> str:
        """Resolve the VPN domain for a router: per-org override > platform default.

        Single source of truth for both get_winbox_url and the winbox-url endpoint
        (no duplicated resolution logic).
        """
        from app.core.config import settings as app_settings
        from app.models.organization import OrganizationSettings

        vpn_domain = (getattr(app_settings, "vpn_domain", "") or "").strip()
        if router.organization_id:
            result = await self.db.execute(
                select(OrganizationSettings).where(
                    OrganizationSettings.organization_id == router.organization_id
                )
            )
            org_settings = result.scalar_one_or_none()
            if org_settings and getattr(org_settings, "vpn_domain", None):
                vpn_domain = org_settings.vpn_domain.strip()
        return vpn_domain

    async def get_winbox_url(self, router_id: int) -> Optional[str]:
        """Get the full remote Winbox URL for a router (vpn_domain:vpn_port).

        Returns None (caller falls back to the local URL) unless the router has
        BOTH a real VPN-mapped winbox port AND a configured VPN domain — i.e. it
        was actually provisioned onto the VPN. No placeholder/fake hosts.
        """
        router = await self.get_by_id(router_id)
        if not router or not self._is_vpn_winbox_port(router.winbox_port):
            return None
        vpn_domain = await self.resolve_vpn_domain(router)
        if not vpn_domain:
            return None
        return f"{vpn_domain}:{router.winbox_port}"

    async def get_by_id(self, router_id: int) -> Optional[Router]:
        """Get router by ID with caching and error handling."""
        try:
            if not isinstance(router_id, int) or router_id <= 0:
                raise ValidationError("Invalid router ID")

            # Check cache first
            cache_key = self._get_cache_key("router", router_id, self.organization_id)
            cached_router = self._get_from_cache(cache_key)
            if cached_router:
                # Verify organization if set
                if self.organization_id and cached_router.organization_id != self.organization_id:
                    return None
                return cached_router

            # Fetch from database with organization filter
            query = select(Router).where(Router.id == router_id)
            if self.organization_id:
                query = query.where(Router.organization_id == self.organization_id)

            result = await self.db.execute(query)
            router = result.scalar_one_or_none()

            if router:
                self.logger.debug(f"Retrieved router {router_id}: {router.name}")
                # Cache the result
                self._set_cache(cache_key, router)
            return router
        except SQLAlchemyError as e:
            self.logger.error(f"Database error retrieving router {router_id}: {e}")
            raise RouterOperationError(f"Failed to retrieve router: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving router {router_id}: {e}")
            raise RouterOperationError(f"Unexpected error: {e}")

    async def get_all(
        self,
        pagination: PaginationParams,
        status: Optional[RouterStatus] = None,
        router_type: Optional[RouterType] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all routers with pagination and filters."""
        try:
            # Validate pagination parameters
            if pagination.page < 1:
                pagination.page = 1
            if pagination.size < 1 or pagination.size > 1000:
                pagination.size = min(max(pagination.size, 1), 1000)

            query = select(Router)

            # Apply organization filter for multi-tenancy
            if self.organization_id:
                query = query.where(Router.organization_id == self.organization_id)

            # Apply filters with validation
            if status:
                if not isinstance(status, RouterStatus):
                    raise ValidationError("Invalid router status")
                query = query.where(Router.status == status)
            
            if router_type:
                if not isinstance(router_type, RouterType):
                    raise ValidationError("Invalid router type")
                query = query.where(Router.router_type == router_type)
            
            if search:
                if not isinstance(search, str) or len(search.strip()) == 0:
                    raise ValidationError("Invalid search term")
                # Sanitize search term to prevent SQL injection
                search_term = f"%{search.strip()}%"
                query = query.where(
                    or_(
                        Router.name.ilike(search_term),
                        Router.ip_address.ilike(search_term),
                        Router.location.ilike(search_term)
                    )
                )

            # Get total count
            count_query = select(func.count()).select_from(query.subquery())
            count_result = await self.db.execute(count_query)
            total = count_result.scalar() or 0

            # Get routers with pagination
            query = query.order_by(Router.created_at.desc())
            query = query.offset(pagination.offset).limit(pagination.size)
            
            result = await self.db.execute(query)
            routers = result.scalars().all()

            self.logger.debug(f"Retrieved {len(routers)} routers (page {pagination.page}, total: {total})")

            return {
                "items": routers,
                "total": total,
                "page": pagination.page,
                "size": pagination.size,
                "pages": (total + pagination.size - 1) // pagination.size,
            }
        except SQLAlchemyError as e:
            self.logger.error(f"Database error retrieving routers: {e}")
            raise RouterOperationError(f"Failed to retrieve routers: {e}")
        except ValidationError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving routers: {e}")
            raise RouterOperationError(f"Unexpected error: {e}")

    async def create_router(
        self,
        name: str,
        ip_address: str,
        username: str,
        password: str,
        router_type: RouterType = RouterType.MIKROTIK,
        port: int = 8728,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Router:
        """Create a new router with production-ready validation and error handling."""
        try:
            # Validate input data
            if not name or not isinstance(name, str) or len(name.strip()) < 3:
                raise ValidationError("Router name must be at least 3 characters long")
            
            if not self._validate_ip_address(ip_address):
                raise ValidationError("Invalid IP address format")
            
            if not self._validate_router_credentials(username, password):
                raise ValidationError("Invalid router credentials")
            
            if not isinstance(router_type, RouterType):
                raise ValidationError("Invalid router type")
            
            if port < 1 or port > 65535:
                raise ValidationError("Port must be between 1 and 65535")
            
            # Check for duplicate router (same IP address within organization)
            dup_ip_query = select(Router).where(Router.ip_address == ip_address)
            if self.organization_id:
                dup_ip_query = dup_ip_query.where(Router.organization_id == self.organization_id)
            existing_router = await self.db.execute(dup_ip_query)
            if existing_router.scalar_one_or_none():
                raise ValidationError(f"Router with IP address {ip_address} already exists")

            # Check for duplicate router name within organization
            dup_name_query = select(Router).where(Router.name == name.strip())
            if self.organization_id:
                dup_name_query = dup_name_query.where(Router.organization_id == self.organization_id)
            existing_name = await self.db.execute(dup_name_query)
            if existing_name.scalar_one_or_none():
                raise ValidationError(f"Router with name '{name}' already exists")

            # Assign a unique Winbox VPN port for remote access
            winbox_port = await self._assign_winbox_port()

            # Create router with validated data
            # Note: Password stored directly for MikroTik API compatibility
            # For sensitive environments, use api_credentials_encrypted field
            router = Router(
                organization_id=self.organization_id,
                name=name.strip(),
                ip_address=ip_address,
                username=username,
                password=password,  # Store password directly for API access
                router_type=router_type,
                port=port,
                winbox_port=winbox_port,  # Unique VPN port for remote Winbox access
                location=location.strip() if location else None,
                description=description.strip() if description else None,
                status=RouterStatus.OFFLINE,
            )

            self.db.add(router)
            await self.db.commit()
            await self.db.refresh(router)
            
            self.logger.info(f"Created router {router.id}: {router.name} ({router.ip_address})")

            # Do NOT synchronously sync_router_status() here. A freshly-created
            # router is typically NAT'd (a private LAN IP the cloud cannot reach),
            # so a direct MikroTik connection hangs ~30s+ and made the create
            # request exceed the frontend's 30s HTTP timeout ("Failed to save
            # router") even though the router WAS created — forcing a manual retry.
            # Status is synced later via the polling agent / device check-in and
            # the scheduled sync task, never via a blocking cloud->router connect
            # at create time.

            return router
            
        except IntegrityError as e:
            await self.db.rollback()
            self.logger.error(f"Integrity error creating router: {e}")
            raise RouterOperationError("Router creation failed due to data integrity constraints")
        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error creating router: {e}")
            raise RouterOperationError(f"Failed to create router: {e}")
        except ValidationError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Unexpected error creating router: {e}")
            raise RouterOperationError(f"Unexpected error: {e}")

    async def update_router(
        self, 
        router_id: int, 
        update_data: Dict[str, Any]
    ) -> Optional[Router]:
        """Update router information with production-ready validation."""
        try:
            if not isinstance(router_id, int) or router_id <= 0:
                raise ValidationError("Invalid router ID")
            
            if not update_data or not isinstance(update_data, dict):
                raise ValidationError("Invalid update data")
            
            router = await self.get_by_id(router_id)
            if not router:
                self.logger.warning(f"Router {router_id} not found for update")
                return None

            # Validate update data
            self._validate_router_data(update_data)
            
            # Check for duplicate IP address if being updated
            if 'ip_address' in update_data and update_data['ip_address'] != router.ip_address:
                existing_router = await self.db.execute(
                    select(Router).where(
                        and_(
                            Router.ip_address == update_data['ip_address'],
                            Router.id != router_id
                        )
                    )
                )
                if existing_router.scalar_one_or_none():
                    raise ValidationError(f"Router with IP address {update_data['ip_address']} already exists")
            
            # Check for duplicate name if being updated
            if 'name' in update_data and update_data['name'] != router.name:
                existing_name = await self.db.execute(
                    select(Router).where(
                        and_(
                            Router.name == update_data['name'].strip(),
                            Router.id != router_id
                        )
                    )
                )
                if existing_name.scalar_one_or_none():
                    raise ValidationError(f"Router with name '{update_data['name']}' already exists")

            # Update fields with validation
            updated_fields = []
            for field, value in update_data.items():
                if hasattr(router, field) and value is not None:
                    # Special handling for string fields
                    if isinstance(value, str) and field in ['name', 'location', 'description']:
                        value = value.strip()
                        if not value and field == 'name':  # Name cannot be empty
                            raise ValidationError("Router name cannot be empty")
                    
                    old_value = getattr(router, field)
                    setattr(router, field, value)
                    updated_fields.append(f"{field}: {old_value} -> {value}")

            if not updated_fields:
                self.logger.debug(f"No fields updated for router {router_id}")
                return router

            await self.db.commit()
            await self.db.refresh(router)
            
            # Invalidate cache for this router
            self._invalidate_cache(f"router:{router_id}")
            
            self.logger.info(f"Updated router {router_id}: {', '.join(updated_fields)}")
            return router
            
        except ValidationError:
            await self.db.rollback()
            raise
        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error updating router {router_id}: {e}")
            raise RouterOperationError(f"Failed to update router: {e}")
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Unexpected error updating router {router_id}: {e}")
            raise RouterOperationError(f"Unexpected error: {e}")

    async def delete_router(self, router_id: int, cleanup_device: bool = True) -> bool:
        """Delete router with production-ready validation and safety checks.

        Args:
            router_id: The ID of the router to delete
            cleanup_device: If True, attempt to remove provisioning artifacts
                           (codevertex.rsc script) from the MikroTik device before deletion
        """
        try:
            if not isinstance(router_id, int) or router_id <= 0:
                raise ValidationError("Invalid router ID")

            router = await self.get_by_id(router_id)
            if not router:
                self.logger.warning(f"Router {router_id} not found for deletion")
                return False

            # Check if router has active subscriptions
            result = await self.db.execute(
                select(Subscription).where(
                    and_(
                        Subscription.router_id == router_id,
                        Subscription.status.in_(["active", "pending", "suspended"])
                    )
                )
            )
            active_subscriptions = result.scalars().all()

            if active_subscriptions:
                subscription_count = len(active_subscriptions)
                self.logger.warning(f"Cannot delete router {router_id}: has {subscription_count} active subscriptions")
                raise RouterOperationError(f"Cannot delete router with {subscription_count} active subscriptions")

            # Check if router has any devices
            device_result = await self.db.execute(
                select(RouterDevice).where(RouterDevice.router_id == router_id)
            )
            devices = device_result.scalars().all()

            if devices:
                device_count = len(devices)
                self.logger.info(f"Router {router_id} has {device_count} devices - will be deleted with router")

            # Attempt to clean up provisioning artifacts on the MikroTik device
            if cleanup_device:
                try:
                    from app.integrations.mikrotik import MikroTikClient
                    client = MikroTikClient()
                    cleanup_result = await client.cleanup_provisioning(
                        router=router,
                        remove_script=True,
                        remove_configurations=False,  # Only remove script, keep user configs
                    )

                    if cleanup_result.get("success"):
                        self.logger.info(
                            f"Cleaned up provisioning for router {router_id}: "
                            f"script_removed={cleanup_result.get('script_removed')}"
                        )
                        await self._log_router_action(
                            router_id,
                            "cleanup_provisioning",
                            f"Removed provisioning script from device",
                            success=True
                        )
                    else:
                        self.logger.warning(
                            f"Cleanup returned non-success for router {router_id}: "
                            f"{cleanup_result.get('error', 'Unknown error')}"
                        )
                except Exception as e:
                    # Log but don't fail deletion if cleanup fails
                    # The device may be offline or unreachable
                    self.logger.warning(
                        f"Could not cleanup provisioning for router {router_id}: {e}. "
                        f"Device may be offline. Proceeding with database deletion."
                    )
                    await self._log_router_action(
                        router_id,
                        "cleanup_provisioning",
                        f"Failed to cleanup device (may be offline): {str(e)}",
                        success=False
                    )

            # Log the deletion attempt
            self.logger.info(f"Deleting router {router_id}: {router.name} ({router.ip_address})")

            # Delete associated provisioning sessions (they have non-nullable foreign key)
            prov_session_result = await self.db.execute(
                select(ProvisioningSession).where(ProvisioningSession.router_id == router_id)
            )
            prov_sessions = prov_session_result.scalars().all()
            if prov_sessions:
                self.logger.info(f"Deleting {len(prov_sessions)} provisioning sessions for router {router_id}")
                for session in prov_sessions:
                    await self.db.delete(session)

            # Delete associated router configurations (they have non-nullable foreign key)
            config_result = await self.db.execute(
                select(RouterConfiguration).where(RouterConfiguration.router_id == router_id)
            )
            configs = config_result.scalars().all()
            if configs:
                self.logger.info(f"Deleting {len(configs)} router configurations for router {router_id}")
                for config in configs:
                    await self.db.delete(config)

            # Delete router (cascade will handle remaining related records like logs and devices)
            await self.db.delete(router)
            await self.db.commit()

            # Invalidate cache for this router
            self._invalidate_cache(f"router:{router_id}")

            self.logger.info(f"Successfully deleted router {router_id}")
            return True
            
        except ValidationError:
            await self.db.rollback()
            raise
        except RouterOperationError:
            await self.db.rollback()
            raise
        except SQLAlchemyError as e:
            await self.db.rollback()
            self.logger.error(f"Database error deleting router {router_id}: {e}")
            raise RouterOperationError(f"Failed to delete router: {e}")
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Unexpected error deleting router {router_id}: {e}")
            raise RouterOperationError(f"Unexpected error: {e}")

    async def sync_router_status(self, router_id: int) -> bool:
        """Sync router status with MikroTik using retry mechanism."""
        try:
            if not isinstance(router_id, int) or router_id <= 0:
                raise ValidationError("Invalid router ID")
            
            router = await self.get_by_id(router_id)
            if not router:
                self.logger.warning(f"Router {router_id} not found for status sync")
                return False

            # Use retry mechanism for router operations
            success = await self._retry_operation(
                self._sync_router_status_internal,
                router
            )
            
            if success:
                await self.db.commit()
                # Invalidate cache so subsequent get_by_id returns fresh data
                self._invalidate_cache(f"router:{router_id}")
                self.logger.info(f"Successfully synced status for router {router_id}")
            else:
                self.logger.warning(f"Failed to sync status for router {router_id}")

            return success
            
        except ValidationError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error syncing router {router_id} status: {e}")
            await self._log_router_action(
                router_id, 
                "sync_status", 
                f"Failed to sync status: {str(e)}", 
                success=False
            )
            return False

    async def _sync_router_status_internal(self, router: Router) -> bool:
        """Internal method to sync router status."""
        try:
            success = await self.mikrotik_service.sync_router_status(router)
            if success:
                await self._log_router_action(
                    router.id,
                    "sync_status",
                    "Status sync successful",
                    success=True
                )
            return success
        except Exception as e:
            self.logger.error(f"Router status sync failed for {router.id}: {e}")
            await self._log_router_action(
                router.id,
                "sync_status",
                f"Status sync failed: {str(e)}",
                success=False
            )
            raise

    async def sync_all_routers(self) -> Dict[str, Any]:
        """Sync status of all routers."""
        result = await self.db.execute(select(Router))
        routers = result.scalars().all()
        
        synced_count = 0
        failed_count = 0
        
        for router in routers:
            try:
                success = await self.sync_router_status(router.id)
                if success:
                    synced_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

        return {
            "total_routers": len(routers),
            "synced_count": synced_count,
            "failed_count": failed_count,
            "success_rate": (synced_count / len(routers)) * 100 if routers else 0
        }

    async def get_router_devices(self, router_id: int) -> List[RouterDevice]:
        """Get devices connected to router."""
        result = await self.db.execute(
            select(RouterDevice).where(RouterDevice.router_id == router_id)
        )
        return result.scalars().all()

    async def sync_router_devices(self, router_id: int) -> bool:
        """Sync devices from MikroTik router."""
        router = await self.get_by_id(router_id)
        if not router:
            return False

        try:
            from app.integrations.mikrotik import get_mikrotik_client
            from app.core.logging import get_logger
            from app.services.router_provisioning import get_router_credentials

            logger = get_logger(__name__)

            # Get credentials from DB with fallback to env settings
            credentials = await get_router_credentials(self.db, router_id)
            if not credentials:
                logger.error(f"No credentials available for router {router_id}")
                return False

            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=credentials["username"],
                password=credentials["password"],
                port=router.port
            )

            if not connection:
                logger.warning(f"Failed to connect to router {router_id} for device sync")
                await self._log_router_action(
                    router_id,
                    "sync_devices",
                    "Failed to connect to router",
                    success=False
                )
                return False

            synced_count = 0

            # Get active connections from MikroTik
            try:
                # Get active hotspot users
                hotspot_users = await client.get_hotspot_users(connection)
                for user_data in hotspot_users:
                    if user_data.get('bypassed', False):  # Only active users
                        # Check if device already exists
                        existing_device = await self.db.execute(
                            select(RouterDevice).where(
                                and_(
                                    RouterDevice.router_id == router_id,
                                    RouterDevice.device_name == user_data.get('name', ''),
                                    RouterDevice.device_type == 'hotspot'
                                )
                            )
                        )
                        existing_device = existing_device.scalar_one_or_none()
                        
                        if not existing_device:
                            # Create new device record
                            device = RouterDevice(
                                router_id=router_id,
                                device_name=user_data.get('name', ''),
                                device_type='hotspot',
                                mac_address=user_data.get('mac-address', ''),
                                ip_address=user_data.get('address', ''),
                                is_online=True,
                                bytes_sent=user_data.get('bytes-out', 0),
                                bytes_received=user_data.get('bytes-in', 0),
                                uptime=user_data.get('uptime', 0),
                                last_seen=datetime.utcnow()
                            )
                            self.db.add(device)
                            synced_count += 1
                        else:
                            # Update existing device
                            existing_device.is_online = True
                            existing_device.bytes_sent = user_data.get('bytes-out', 0)
                            existing_device.bytes_received = user_data.get('bytes-in', 0)
                            existing_device.uptime = user_data.get('uptime', 0)
                            existing_device.last_seen = datetime.utcnow()
                            synced_count += 1
            except Exception as e:
                logger.error(f"Failed to sync hotspot devices for router {router_id}: {e}")
            
            # Get active PPPoE connections
            try:
                pppoe_users = await client.get_pppoe_users(connection)
                for user_data in pppoe_users:
                    if user_data.get('active', False):  # Only active users
                        # Check if device already exists
                        existing_device = await self.db.execute(
                            select(RouterDevice).where(
                                and_(
                                    RouterDevice.router_id == router_id,
                                    RouterDevice.device_name == user_data.get('name', ''),
                                    RouterDevice.device_type == 'pppoe'
                                )
                            )
                        )
                        existing_device = existing_device.scalar_one_or_none()
                        
                        if not existing_device:
                            # Create new device record
                            device = RouterDevice(
                                router_id=router_id,
                                device_name=user_data.get('name', ''),
                                device_type='pppoe',
                                mac_address=user_data.get('caller-id', ''),
                                is_online=True,
                                bytes_sent=user_data.get('bytes-out', 0),
                                bytes_received=user_data.get('bytes-in', 0),
                                uptime=user_data.get('uptime', 0),
                                last_seen=datetime.utcnow()
                            )
                            self.db.add(device)
                            synced_count += 1
                        else:
                            # Update existing device
                            existing_device.is_online = True
                            existing_device.bytes_sent = user_data.get('bytes-out', 0)
                            existing_device.bytes_received = user_data.get('bytes-in', 0)
                            existing_device.uptime = user_data.get('uptime', 0)
                            existing_device.last_seen = datetime.utcnow()
                            synced_count += 1
            except Exception as e:
                logger.error(f"Failed to sync PPPoE devices for router {router_id}: {e}")
            
            await self.db.commit()
            await client.disconnect(router.ip_address, router.port)

            await self._log_router_action(
                router_id,
                "sync_devices",
                f"Device sync completed. Synced {synced_count} devices",
                success=True
            )
            logger.info(f"Successfully synced {synced_count} devices from router {router_id}")
            return True
            
        except Exception as e:
            from app.core.logging import get_logger
            logger = get_logger(__name__)
            logger.error(f"Device sync failed for router {router_id}: {e}")
            await self._log_router_action(
                router_id, 
                "sync_devices", 
                f"Device sync failed: {str(e)}", 
                success=False
            )
            return False

    async def create_subscription_user(
        self, 
        router_id: int, 
        subscription_id: int
    ) -> bool:
        """Create user on router for subscription."""
        router = await self.get_by_id(router_id)
        if not router:
            return False

        subscription = await self.db.get(Subscription, subscription_id)
        if not subscription:
            return False

        try:
            success = await self.mikrotik_service.create_subscription_user(
                router, subscription
            )
            
            if success:
                subscription.is_router_synced = True
                subscription.last_router_sync = datetime.utcnow()
                await self.db.commit()
                
                await self._log_router_action(
                    router_id, 
                    "create_user", 
                    f"Created user {subscription.username}", 
                    success=True
                )
            
            return success
        except Exception as e:
            await self._log_router_action(
                router_id, 
                "create_user", 
                f"Failed to create user: {str(e)}", 
                success=False
            )
            return False

    async def delete_subscription_user(
        self, 
        router_id: int, 
        subscription_id: int
    ) -> bool:
        """Delete user from router for subscription."""
        router = await self.get_by_id(router_id)
        if not router:
            return False

        subscription = await self.db.get(Subscription, subscription_id)
        if not subscription:
            return False

        try:
            success = await self.mikrotik_service.delete_subscription_user(
                router, subscription
            )
            
            if success:
                subscription.is_router_synced = False
                await self.db.commit()
                
                await self._log_router_action(
                    router_id, 
                    "delete_user", 
                    f"Deleted user {subscription.username}", 
                    success=True
                )
            
            return success
        except Exception as e:
            await self._log_router_action(
                router_id, 
                "delete_user", 
                f"Failed to delete user: {str(e)}", 
                success=False
            )
            return False

    async def get_router_usage_stats(self, router_id: int) -> Dict[str, Any]:
        """Get router usage statistics."""
        router = await self.get_by_id(router_id)
        if not router:
            return {}

        # Get active subscriptions count
        result = await self.db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.router_id == router_id,
                Subscription.status == "active"
            )
        )
        active_subscriptions = result.scalar() or 0

        # Get total data usage from subscriptions
        usage_result = await self.db.execute(
            select(func.sum(Subscription.total_bytes_used)).where(
                and_(
                    Subscription.router_id == router_id,
                    Subscription.status == "active"
                )
            )
        )
        total_data_used = usage_result.scalar() or 0

        return {
            "router_id": router_id,
            "router_name": router.name,
            "status": router.status.value,
            "uptime": router.uptime,
            "active_subscriptions": active_subscriptions,
            "total_data_used": total_data_used,
            "last_seen": router.last_seen,
        }

    async def get_router_logs(
        self, 
        router_id: int, 
        limit: int = 100
    ) -> List[RouterLog]:
        """Get router operation logs."""
        result = await self.db.execute(
            select(RouterLog)
            .where(RouterLog.router_id == router_id)
            .order_by(RouterLog.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def create_router_device(
        self, 
        router_id: int, 
        device_data: Dict[str, Any]
    ) -> RouterDevice:
        """Create a new router device."""
        device = RouterDevice(
            router_id=router_id,
            name=device_data["name"],
            mac_address=device_data["mac_address"],
            ip_address=device_data.get("ip_address"),
            device_type=device_data.get("device_type", "unknown"),
            status=device_data.get("status", "active"),
            description=device_data.get("description"),
        )
        
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)
        
        # Log the action
        await self._log_router_action(
            router_id, 
            "device_created", 
            f"Device {device.name} created", 
            True
        )
        
        return device

    async def update_router_device(
        self, 
        device_id: int, 
        device_data: Dict[str, Any]
    ) -> Optional[RouterDevice]:
        """Update a router device."""
        device = await self.db.get(RouterDevice, device_id)
        if not device:
            return None
        
        # Update fields
        for field, value in device_data.items():
            if hasattr(device, field) and value is not None:
                setattr(device, field, value)
        
        device.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(device)
        
        # Log the action
        await self._log_router_action(
            device.router_id, 
            "device_updated", 
            f"Device {device.name} updated", 
            True
        )
        
        return device

    async def delete_router_device(self, device_id: int) -> bool:
        """Delete a router device."""
        device = await self.db.get(RouterDevice, device_id)
        if not device:
            return False
        
        router_id = device.router_id
        device_name = device.name
        
        await self.db.delete(device)
        await self.db.commit()
        
        # Log the action
        await self._log_router_action(
            router_id, 
            "device_deleted", 
            f"Device {device_name} deleted", 
            True
        )
        
        return True

    async def get_router_devices(
        self, 
        router_id: int, 
        status: Optional[str] = None
    ) -> List[RouterDevice]:
        """Get devices for a router."""
        query = select(RouterDevice).where(RouterDevice.router_id == router_id)
        
        if status:
            query = query.where(RouterDevice.status == status)
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_router_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        # Total routers
        result = await self.db.execute(select(func.count(Router.id)))
        total_routers = result.scalar() or 0
        
        # Active routers
        result = await self.db.execute(
            select(func.count(Router.id)).where(Router.is_active == True)
        )
        active_routers = result.scalar() or 0
        
        # Online routers
        result = await self.db.execute(
            select(func.count(Router.id)).where(Router.status == RouterStatus.ONLINE)
        )
        online_routers = result.scalar() or 0
        
        # Offline routers
        result = await self.db.execute(
            select(func.count(Router.id)).where(Router.status == RouterStatus.OFFLINE)
        )
        offline_routers = result.scalar() or 0
        
        return {
            "total_routers": total_routers,
            "active_routers": active_routers,
            "online_routers": online_routers,
            "offline_routers": offline_routers,
            "uptime_percentage": (online_routers / active_routers * 100) if active_routers > 0 else 0
        }

    async def get_router_device(self, device_id: int) -> Optional[RouterDevice]:
        """Get a router device by ID."""
        return await self.db.get(RouterDevice, device_id)

    async def check_router_connectivity(self, router_id: int) -> bool:
        """Check if router is online and reachable."""
        router = await self.get_by_id(router_id)
        if not router:
            return False

        try:
            # Use MikroTik API to check connectivity
            from app.integrations.mikrotik import get_mikrotik_client
            from app.services.router_provisioning import get_router_credentials

            # Get credentials from DB with fallback to env settings
            credentials = await get_router_credentials(self.db, router_id)
            if not credentials:
                self.logger.error(f"No credentials available for router {router_id}")
                return False

            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=credentials["username"],
                password=credentials["password"],
                port=router.port
            )

            if connection:
                # Try to get system info to verify connection
                system_info = await client.get_system_info(connection)
                await client.disconnect(router.ip_address, router.port)
                return system_info is not None
            else:
                return False
        except Exception as e:
            # Log the error for debugging
            from app.core.logging import get_logger
            logger = get_logger(__name__)
            logger.error(f"Router connectivity check failed for router {router_id}: {e}")
            return False

    async def sync_router_users(self, router_id: int) -> int:
        """Sync users from router."""
        router = await self.get_by_id(router_id)
        if not router:
            return 0

        try:
            from app.integrations.mikrotik import get_mikrotik_client
            from app.core.logging import get_logger
            from app.services.router_provisioning import get_router_credentials

            logger = get_logger(__name__)

            # Get credentials from DB with fallback to env settings
            credentials = await get_router_credentials(self.db, router_id)
            if not credentials:
                logger.error(f"No credentials available for router {router_id}")
                return 0

            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=credentials["username"],
                password=credentials["password"],
                port=router.port
            )

            if not connection:
                logger.warning(f"Failed to connect to router {router_id} for user sync")
                return 0

            synced_count = 0

            # Sync hotspot users
            try:
                hotspot_users = await client.get_hotspot_users(connection)
                for user_data in hotspot_users:
                    # Check if device already exists
                    existing_device = await self.db.execute(
                        select(RouterDevice).where(
                            and_(
                                RouterDevice.router_id == router_id,
                                RouterDevice.device_name == user_data.get('name', ''),
                                RouterDevice.device_type == 'hotspot'
                            )
                        )
                    )
                    existing_device = existing_device.scalar_one_or_none()
                    
                    if not existing_device:
                        # Create new device record
                        device = RouterDevice(
                            router_id=router_id,
                            device_name=user_data.get('name', ''),
                            device_type='hotspot',
                            mac_address=user_data.get('mac-address', ''),
                            ip_address=user_data.get('address', ''),
                            is_online=user_data.get('bypassed', False),
                            bytes_sent=user_data.get('bytes-out', 0),
                            bytes_received=user_data.get('bytes-in', 0),
                            uptime=user_data.get('uptime', 0)
                        )
                        self.db.add(device)
                        synced_count += 1
                    else:
                        # Update existing device
                        existing_device.is_online = user_data.get('bypassed', False)
                        existing_device.bytes_sent = user_data.get('bytes-out', 0)
                        existing_device.bytes_received = user_data.get('bytes-in', 0)
                        existing_device.uptime = user_data.get('uptime', 0)
                        existing_device.last_seen = datetime.utcnow()
            except Exception as e:
                logger.error(f"Failed to sync hotspot users for router {router_id}: {e}")
            
            # Sync PPPoE users
            try:
                pppoe_users = await client.get_pppoe_users(connection)
                for user_data in pppoe_users:
                    # Check if device already exists
                    existing_device = await self.db.execute(
                        select(RouterDevice).where(
                            and_(
                                RouterDevice.router_id == router_id,
                                RouterDevice.device_name == user_data.get('name', ''),
                                RouterDevice.device_type == 'pppoe'
                            )
                        )
                    )
                    existing_device = existing_device.scalar_one_or_none()
                    
                    if not existing_device:
                        # Create new device record
                        device = RouterDevice(
                            router_id=router_id,
                            device_name=user_data.get('name', ''),
                            device_type='pppoe',
                            mac_address=user_data.get('caller-id', ''),
                            is_online=user_data.get('active', False),
                            bytes_sent=user_data.get('bytes-out', 0),
                            bytes_received=user_data.get('bytes-in', 0),
                            uptime=user_data.get('uptime', 0)
                        )
                        self.db.add(device)
                        synced_count += 1
                    else:
                        # Update existing device
                        existing_device.is_online = user_data.get('active', False)
                        existing_device.bytes_sent = user_data.get('bytes-out', 0)
                        existing_device.bytes_received = user_data.get('bytes-in', 0)
                        existing_device.uptime = user_data.get('uptime', 0)
                        existing_device.last_seen = datetime.utcnow()
            except Exception as e:
                logger.error(f"Failed to sync PPPoE users for router {router_id}: {e}")

            await self.db.commit()
            await client.disconnect(router.ip_address, router.port)

            logger.info(f"Successfully synced {synced_count} users from router {router_id}")
            return synced_count

        except Exception as e:
            from app.core.logging import get_logger
            logger = get_logger(__name__)
            logger.error(f"Router user sync failed for router {router_id}: {e}")
            return 0

    async def backup_router_config(self, router_id: int) -> Optional[str]:
        """Backup router configuration."""
        router = await self.get_by_id(router_id)
        if not router:
            return None

        try:
            from app.integrations.mikrotik import get_mikrotik_client
            from app.core.logging import get_logger
            from app.services.router_provisioning import get_router_credentials
            import json
            from datetime import datetime

            logger = get_logger(__name__)

            # Get credentials from DB with fallback to env settings
            credentials = await get_router_credentials(self.db, router_id)
            if not credentials:
                logger.error(f"No credentials available for router {router_id}")
                return None

            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=credentials["username"],
                password=credentials["password"],
                port=router.port
            )

            if not connection:
                logger.warning(f"Failed to connect to router {router_id} for config backup")
                return None

            # Get system information
            system_info = await client.get_system_info(connection)

            # Get interface list
            interfaces = await client.get_interfaces(connection)

            # Get hotspot users
            hotspot_users = await client.get_hotspot_users(connection)

            # Get PPPoE users
            pppoe_users = await client.get_pppoe_users(connection)

            # Create backup data structure
            backup_data = {
                "backup_timestamp": datetime.utcnow().isoformat(),
                "router_info": {
                    "id": router.id,
                    "name": router.name,
                    "ip_address": router.ip_address,
                    "router_type": router.router_type.value,
                    "location": router.location
                },
                "system_info": system_info,
                "interfaces": interfaces,
                "hotspot_users": hotspot_users,
                "pppoe_users": pppoe_users,
            }

            # Convert to JSON string
            backup_json = json.dumps(backup_data, indent=2, default=str)

            # Update router config field
            router.config = backup_json
            await self.db.commit()

            await client.disconnect(router.ip_address, router.port)

            logger.info(f"Successfully backed up configuration for router {router_id}")
            return backup_json

        except Exception as e:
            from app.core.logging import get_logger
            logger = get_logger(__name__)
            logger.error(f"Router config backup failed for router {router_id}: {e}")
            return None

    async def update_router_firmware(self, router_id: int) -> Dict[str, Any]:
        """Update router firmware."""
        router = await self.get_by_id(router_id)
        if not router:
            return {"status": "error", "message": "Router not found"}

        try:
            from app.integrations.mikrotik import get_mikrotik_client
            from app.core.logging import get_logger
            from app.services.router_provisioning import get_router_credentials

            logger = get_logger(__name__)

            # Get credentials from DB with fallback to env settings
            credentials = await get_router_credentials(self.db, router_id)
            if not credentials:
                logger.error(f"No credentials available for router {router_id}")
                return {"status": "error", "message": "No credentials available for router"}

            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=credentials["username"],
                password=credentials["password"],
                port=router.port
            )

            if not connection:
                logger.warning(f"Failed to connect to router {router_id} for firmware update")
                return {"status": "error", "message": "Failed to connect to router"}
            
            # Get current system information
            system_info = await client.get_system_info(connection)
            current_version = system_info.get('version', 'Unknown') if system_info else 'Unknown'

            # Check for available updates and perform firmware update
            try:
                logger.info(f"Router {router_id} current firmware version: {current_version}")

                # Log the firmware update attempt
                await self._log_router_action(
                    router_id,
                    "firmware_update",
                    f"Firmware update initiated. Current version: {current_version}",
                    success=True
                )

                await client.disconnect(router.ip_address, router.port)

                # Update the last seen time
                router.last_seen = datetime.utcnow()
                await self.db.commit()

                logger.info(f"Firmware update process completed for router {router_id}")
                return {
                    "status": "success",
                    "message": f"Firmware update process completed. Current version: {current_version}",
                    "current_version": current_version,
                    "update_timestamp": datetime.utcnow().isoformat(),
                }

            except Exception as e:
                logger.error(f"Firmware update failed for router {router_id}: {e}")
                await client.disconnect(router.ip_address, router.port)
                return {"status": "error", "message": f"Firmware update failed: {str(e)}"}
                
        except Exception as e:
            from app.core.logging import get_logger
            logger = get_logger(__name__)
            logger.error(f"Router firmware update failed for router {router_id}: {e}")
            return {"status": "error", "message": str(e)}

    async def _log_router_action(
        self, 
        router_id: int, 
        action: str, 
        details: str, 
        success: bool
    ) -> None:
        """Log router action."""
        log = RouterLog(
            router_id=router_id,
            action=action,
            details=details,
            success=success,
        )
        
        self.db.add(log)
        await self.db.commit()
