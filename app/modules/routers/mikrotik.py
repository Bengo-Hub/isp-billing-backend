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
from app.integrations.mikrotik import get_mikrotik_client

logger = get_logger(__name__)


class MikroTikOperations:
    """MikroTik-specific operations for routers."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = get_mikrotik_client()

    async def _connect(self, router: Router):
        """Helper to connect to router."""
        return await self.client.connect(
            ip_address=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port
        )

    async def check_connectivity(self, router: Router) -> bool:
        """Check router connectivity by attempting to connect and get system info."""
        try:
            connection = await self._connect(router)
            if connection:
                system_info = await self.client.get_system_info(connection)
                await self.client.disconnect(router.ip_address, router.port)
                return system_info is not None
            return False
        except Exception as e:
            logger.error(f"Router connectivity check failed for router {router.id}: {e}")
            return False

    async def sync_status(self, router: Router) -> Dict[str, Any]:
        """Sync router status from MikroTik device."""
        try:
            connection = await self._connect(router)
            if not connection:
                return {"success": False, "error": "Failed to connect"}

            # Get system info
            system_info = await self.client.get_system_info(connection)
            if system_info:
                router.uptime = system_info.get("uptime", 0)
                router.firmware_version = system_info.get("version", "Unknown")
                router.board_name = system_info.get("board-name", "Unknown")
                router.status = "online"
                router.last_seen = datetime.utcnow()

            await self.client.disconnect(router.ip_address, router.port)
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
            connection = await self._connect(router)
            if not connection:
                logger.warning(f"Failed to connect to router {router.id} for device sync")
                return 0

            synced_count = 0

            # Sync hotspot users
            try:
                hotspot_users = await self.client.get_hotspot_users(connection)
                synced_count += await self._sync_user_devices(
                    router.id, hotspot_users, "hotspot"
                )
            except Exception as e:
                logger.error(f"Failed to sync hotspot devices for router {router.id}: {e}")

            # Sync PPPoE users
            try:
                pppoe_users = await self.client.get_pppoe_users(connection)
                synced_count += await self._sync_user_devices(
                    router.id, pppoe_users, "pppoe"
                )
            except Exception as e:
                logger.error(f"Failed to sync PPPoE devices for router {router.id}: {e}")

            await self.client.disconnect(router.ip_address, router.port)
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
            connection = await self._connect(router)
            if not connection:
                logger.warning(f"Failed to connect to router {router.id} for user creation")
                return False

            if user_type == "hotspot":
                result = await self.client.create_hotspot_user(connection, username, password, profile)
            else:
                result = await self.client.create_pppoe_user(connection, username, password, profile)

            await self.client.disconnect(router.ip_address, router.port)

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
            connection = await self._connect(router)
            if not connection:
                logger.warning(f"Failed to connect to router {router.id} for user deletion")
                return False

            # Use disable_user method to soft-delete
            result = await self.client.disable_user(connection, username, user_type)

            await self.client.disconnect(router.ip_address, router.port)

            if result:
                logger.info(f"Deleted {user_type} user {username} from router {router.id}")
            return result

        except Exception as e:
            logger.error(f"Failed to delete subscription user from router {router.id}: {e}")
            return False

    async def backup_config(self, router: Router) -> Optional[str]:
        """Backup router configuration."""
        try:
            import json

            connection = await self._connect(router)
            if not connection:
                logger.warning(f"Failed to connect to router {router.id} for config backup")
                return None

            # Collect configuration data
            system_info = await self.client.get_system_info(connection)
            interfaces = await self.client.get_interfaces(connection)
            hotspot_users = await self.client.get_hotspot_users(connection)
            pppoe_users = await self.client.get_pppoe_users(connection)

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
            }

            backup_json = json.dumps(backup_data, indent=2, default=str)

            # Store backup in router record
            router.config = backup_json
            await self.db.commit()

            await self.client.disconnect(router.ip_address, router.port)

            logger.info(f"Successfully backed up configuration for router {router.id}")
            return backup_json

        except Exception as e:
            logger.error(f"Router config backup failed for router {router.id}: {e}")
            return None

    async def update_firmware(self, router: Router, force: bool = False) -> Dict[str, Any]:
        """Update router firmware via MikroTik RouterOS API."""
        try:
            connection = await self._connect(router)
            if not connection:
                return {"status": "error", "message": "Failed to connect to router"}

            # Get current system info
            system_info = await self.client.get_system_info(connection)
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
                await self.client.execute_command(
                    connection,
                    "/system/package/update",
                    method="call",
                    cmd="check-for-updates",
                )

                # Get update status (wait a moment for the check to complete)
                await asyncio.sleep(2)

                update_info = await self.client.execute_command(
                    connection,
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
                        logger.info(f"Router {router.id}: Update available from {installed_version} to {latest_version}")

                        await self.client.execute_command(
                            connection,
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

                        await self.client.disconnect(router.ip_address, router.port)
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
                        await self.client.disconnect(router.ip_address, router.port)
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

                    await self.client.disconnect(router.ip_address, router.port)
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

                log = RouterLog(
                    router_id=router.id,
                    action="firmware_check",
                    details=f"Update check failed: {update_error}. Current version: {current_version}",
                    success=False,
                )
                self.db.add(log)

                await self.client.disconnect(router.ip_address, router.port)
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
            connection = await self._connect(router)
            if not connection:
                return {"error": "Failed to connect to router"}

            system_info = await self.client.get_system_info(connection)
            interfaces = await self.client.get_interfaces(connection)

            await self.client.disconnect(router.ip_address, router.port)

            return {
                "system_info": system_info,
                "interfaces": interfaces,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get usage stats for router {router.id}: {e}")
            return {"error": str(e)}
