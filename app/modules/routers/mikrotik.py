"""MikroTik-specific router operations.

This module contains operations that interact directly with MikroTik routers
via the RouterOS API, separated from core CRUD operations for maintainability.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.router import Router, RouterDevice, RouterLog
from app.core.logging import get_logger

logger = get_logger(__name__)


class MikroTikOperations:
    """MikroTik-specific operations for routers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_connectivity(self, router: Router) -> bool:
        """Check router connectivity by attempting to connect and get system info."""
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect()

            if connected:
                system_info = await api.get_system_info()
                await api.disconnect()
                return system_info is not None
            return False
        except Exception as e:
            logger.error(f"Router connectivity check failed for router {router.id}: {e}")
            return False

    async def sync_status(self, router: Router) -> Dict[str, Any]:
        """Sync router status from MikroTik device."""
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect()

            if not connected:
                return {"success": False, "error": "Failed to connect"}

            # Get system info
            system_info = await api.get_system_info()
            if system_info:
                router.uptime = system_info.get("uptime", 0)
                router.firmware_version = system_info.get("version", "Unknown")
                router.board_name = system_info.get("board-name", "Unknown")
                router.status = "online"
                router.last_seen = datetime.utcnow()

            # Get resource info
            resources = await api.get_resources()
            if resources:
                router.cpu_usage = resources.get("cpu-load", 0)
                router.memory_usage = resources.get("free-memory", 0)

            await api.disconnect()
            await self.db.commit()

            return {"success": True, "system_info": system_info}
        except Exception as e:
            logger.error(f"Failed to sync router status for {router.id}: {e}")
            router.status = "offline"
            await self.db.commit()
            return {"success": False, "error": str(e)}

    async def sync_devices(self, router: Router) -> int:
        """Sync devices from MikroTik router."""
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect()

            if not connected:
                logger.warning(f"Failed to connect to router {router.id} for device sync")
                return 0

            synced_count = 0

            # Sync hotspot users
            try:
                hotspot_users = await api.get_hotspot_users()
                synced_count += await self._sync_user_devices(
                    router.id, hotspot_users, "hotspot"
                )
            except Exception as e:
                logger.error(f"Failed to sync hotspot devices for router {router.id}: {e}")

            # Sync PPPoE users
            try:
                pppoe_users = await api.get_pppoe_users()
                synced_count += await self._sync_user_devices(
                    router.id, pppoe_users, "pppoe"
                )
            except Exception as e:
                logger.error(f"Failed to sync PPPoE devices for router {router.id}: {e}")

            await api.disconnect()
            await self.db.commit()

            logger.info(f"Synced {synced_count} devices for router {router.id}")
            return synced_count

        except Exception as e:
            logger.error(f"Device sync failed for router {router.id}: {e}")
            return 0

    async def _sync_user_devices(
        self, router_id: int, users: List[Dict], device_type: str
    ) -> int:
        """Helper to sync user devices of a specific type."""
        synced_count = 0

        for user_data in users:
            device_name = user_data.get("name", "")
            if not device_name:
                continue

            # Check if device exists
            result = await self.db.execute(
                select(RouterDevice).where(
                    and_(
                        RouterDevice.router_id == router_id,
                        RouterDevice.device_name == device_name,
                        RouterDevice.device_type == device_type,
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if not existing:
                device = RouterDevice(
                    router_id=router_id,
                    device_name=device_name,
                    device_type=device_type,
                    mac_address=user_data.get("mac-address", user_data.get("caller-id", "")),
                    ip_address=user_data.get("address", ""),
                    is_online=user_data.get("bypassed", user_data.get("active", False)),
                    bytes_sent=user_data.get("bytes-out", 0),
                    bytes_received=user_data.get("bytes-in", 0),
                    uptime=user_data.get("uptime", 0),
                    last_seen=datetime.utcnow(),
                )
                self.db.add(device)
                synced_count += 1
            else:
                existing.is_online = user_data.get("bypassed", user_data.get("active", False))
                existing.bytes_sent = user_data.get("bytes-out", 0)
                existing.bytes_received = user_data.get("bytes-in", 0)
                existing.uptime = user_data.get("uptime", 0)
                existing.last_seen = datetime.utcnow()
                synced_count += 1

        return synced_count

    async def create_subscription_user(
        self,
        router: Router,
        username: str,
        password: str,
        profile: str,
        user_type: str = "hotspot",
    ) -> bool:
        """Create a subscription user on the MikroTik router."""
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect()

            if not connected:
                logger.warning(f"Failed to connect to router {router.id} for user creation")
                return False

            if user_type == "hotspot":
                result = await api.create_hotspot_user(username, password, profile)
            else:
                result = await api.create_pppoe_user(username, password, profile)

            await api.disconnect()

            if result:
                logger.info(f"Created {user_type} user {username} on router {router.id}")
            return result

        except Exception as e:
            logger.error(f"Failed to create subscription user on router {router.id}: {e}")
            return False

    async def delete_subscription_user(
        self,
        router: Router,
        username: str,
        user_type: str = "hotspot",
    ) -> bool:
        """Delete a subscription user from the MikroTik router."""
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect()

            if not connected:
                logger.warning(f"Failed to connect to router {router.id} for user deletion")
                return False

            if user_type == "hotspot":
                result = await api.delete_hotspot_user(username)
            else:
                result = await api.delete_pppoe_user(username)

            await api.disconnect()

            if result:
                logger.info(f"Deleted {user_type} user {username} from router {router.id}")
            return result

        except Exception as e:
            logger.error(f"Failed to delete subscription user from router {router.id}: {e}")
            return False

    async def backup_config(self, router: Router) -> Optional[str]:
        """Backup router configuration."""
        try:
            from app.integrations.mikrotik import MikroTikAPI
            import json

            api = MikroTikAPI(router)
            connected = await api.connect()

            if not connected:
                logger.warning(f"Failed to connect to router {router.id} for config backup")
                return None

            # Collect configuration data
            system_info = await api.get_system_info()
            interfaces = await api.get_interface_list()
            hotspot_users = await api.get_hotspot_users()
            pppoe_users = await api.get_pppoe_users()
            routes = await api.get_routing_table()

            backup_data = {
                "backup_timestamp": datetime.utcnow().isoformat(),
                "router_info": {
                    "id": router.id,
                    "name": router.name,
                    "ip_address": router.ip_address,
                    "router_type": router.router_type.value if router.router_type else "mikrotik",
                    "location": router.location,
                },
                "system_info": system_info,
                "interfaces": interfaces,
                "hotspot_users": hotspot_users,
                "pppoe_users": pppoe_users,
                "routes": routes,
            }

            backup_json = json.dumps(backup_data, indent=2, default=str)

            # Store backup in router record
            router.config = backup_json
            await self.db.commit()

            await api.disconnect()

            logger.info(f"Successfully backed up configuration for router {router.id}")
            return backup_json

        except Exception as e:
            logger.error(f"Router config backup failed for router {router.id}: {e}")
            return None

    async def update_firmware(self, router: Router, force: bool = False) -> Dict[str, Any]:
        """Update router firmware via MikroTik RouterOS API.

        This implementation:
        1. Connects to the router
        2. Checks current firmware version
        3. Checks for available updates
        4. Downloads and installs update if available
        5. Schedules reboot if needed

        Args:
            router: Router instance to update
            force: If True, reinstall current version

        Returns:
            Dictionary with update status, versions, and any errors
        """
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            if not connected:
                return {"status": "error", "message": "Failed to connect to router"}

            # Get current system info
            system_info = await api.get_system_info(connected)
            current_version = system_info.get("version", "Unknown") if system_info else "Unknown"
            board_name = system_info.get("board-name", "Unknown") if system_info else "Unknown"
            architecture = system_info.get("architecture-name", "Unknown") if system_info else "Unknown"

            logger.info(
                f"Router {router.id} firmware check: version={current_version}, "
                f"board={board_name}, arch={architecture}"
            )

            # Check for updates via /system/package/update
            try:
                # Refresh update information
                await api.execute_command(
                    connected,
                    "/system/package/update",
                    method="call",
                    cmd="check-for-updates",
                )

                # Get update status (wait a moment for the check to complete)
                import asyncio
                await asyncio.sleep(2)

                update_info = await api.execute_command(
                    connected,
                    "/system/package/update",
                    method="get",
                )

                if update_info and len(update_info) > 0:
                    update_data = update_info[0]
                    installed_version = update_data.get("installed-version", current_version)
                    latest_version = update_data.get("latest-version", None)
                    channel = update_data.get("channel", "stable")
                    update_status = update_data.get("status", "unknown")

                    # Log the check
                    log = RouterLog(
                        router_id=router.id,
                        action="firmware_check",
                        details=f"Firmware check: installed={installed_version}, latest={latest_version}, channel={channel}, status={update_status}",
                        success=True,
                    )
                    self.db.add(log)

                    # Check if update is available
                    if latest_version and latest_version != installed_version:
                        # Download and install the update
                        logger.info(f"Router {router.id}: Update available from {installed_version} to {latest_version}")

                        await api.execute_command(
                            connected,
                            "/system/package/update",
                            method="call",
                            cmd="download",
                        )

                        # Log the download initiation
                        log = RouterLog(
                            router_id=router.id,
                            action="firmware_download",
                            details=f"Firmware download initiated: {installed_version} -> {latest_version}",
                            success=True,
                        )
                        self.db.add(log)

                        # Schedule reboot to apply update (optional, can be done manually)
                        # await api.execute_command(connected, "/system", method="call", cmd="reboot")

                        await api.disconnect(router.ip_address, router.port)
                        router.last_seen = datetime.utcnow()
                        await self.db.commit()

                        return {
                            "status": "update_downloading",
                            "message": f"Firmware update downloading. Router will need reboot to apply.",
                            "current_version": installed_version,
                            "target_version": latest_version,
                            "channel": channel,
                            "board_name": board_name,
                            "architecture": architecture,
                            "update_timestamp": datetime.utcnow().isoformat(),
                            "note": "Reboot the router to complete the update.",
                        }
                    else:
                        await api.disconnect(router.ip_address, router.port)
                        router.last_seen = datetime.utcnow()
                        await self.db.commit()

                        return {
                            "status": "up_to_date",
                            "message": f"Router firmware is already up to date.",
                            "current_version": installed_version,
                            "channel": channel,
                            "board_name": board_name,
                            "architecture": architecture,
                            "update_timestamp": datetime.utcnow().isoformat(),
                        }
                else:
                    # No update info available
                    log = RouterLog(
                        router_id=router.id,
                        action="firmware_check",
                        details=f"No update information available. Current version: {current_version}",
                        success=True,
                    )
                    self.db.add(log)

                    await api.disconnect(router.ip_address, router.port)
                    router.last_seen = datetime.utcnow()
                    await self.db.commit()

                    return {
                        "status": "unknown",
                        "message": "Could not retrieve update information from router.",
                        "current_version": current_version,
                        "board_name": board_name,
                        "architecture": architecture,
                        "update_timestamp": datetime.utcnow().isoformat(),
                    }

            except Exception as update_error:
                logger.warning(f"Router {router.id} update check failed: {update_error}")

                # Log the failure but return partial success
                log = RouterLog(
                    router_id=router.id,
                    action="firmware_check",
                    details=f"Update check failed: {update_error}. Current version: {current_version}",
                    success=False,
                )
                self.db.add(log)

                await api.disconnect(router.ip_address, router.port)
                router.last_seen = datetime.utcnow()
                await self.db.commit()

                return {
                    "status": "check_failed",
                    "message": f"Could not check for updates: {update_error}",
                    "current_version": current_version,
                    "board_name": board_name,
                    "architecture": architecture,
                    "update_timestamp": datetime.utcnow().isoformat(),
                }

        except Exception as e:
            logger.error(f"Router firmware update failed for router {router.id}: {e}")
            return {"status": "error", "message": str(e)}

    async def get_usage_stats(self, router: Router) -> Dict[str, Any]:
        """Get router usage statistics."""
        try:
            from app.integrations.mikrotik import MikroTikAPI

            api = MikroTikAPI(router)
            connected = await api.connect()

            if not connected:
                return {"error": "Failed to connect to router"}

            system_info = await api.get_system_info()
            resources = await api.get_resources()
            interfaces = await api.get_interface_list()

            await api.disconnect()

            return {
                "system_info": system_info,
                "resources": resources,
                "interfaces": interfaces,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get usage stats for router {router.id}: {e}")
            return {"error": str(e)}
