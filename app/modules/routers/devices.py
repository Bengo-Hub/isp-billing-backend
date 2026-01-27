"""Router device management operations.

This module handles CRUD operations for router devices,
separated from the main router service for maintainability.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.models.router import RouterDevice
from app.core.logging import get_logger
from app.core.exceptions import ValidationError, RouterOperationError

logger = get_logger(__name__)


class DeviceOperations:
    """Device management operations for routers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_device(self, device_id: int) -> Optional[RouterDevice]:
        """Get a single device by ID."""
        try:
            result = await self.db.execute(
                select(RouterDevice).where(RouterDevice.id == device_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Database error getting device {device_id}: {e}")
            return None

    async def get_devices_by_router(
        self,
        router_id: int,
        device_type: Optional[str] = None,
        is_online: Optional[bool] = None,
        page: int = 1,
        size: int = 50,
    ) -> Dict[str, Any]:
        """Get devices for a router with optional filtering."""
        try:
            query = select(RouterDevice).where(RouterDevice.router_id == router_id)

            if device_type:
                query = query.where(RouterDevice.device_type == device_type)
            if is_online is not None:
                query = query.where(RouterDevice.is_online == is_online)

            # Get total count
            count_query = select(func.count()).select_from(query.subquery())
            count_result = await self.db.execute(count_query)
            total = count_result.scalar() or 0

            # Apply pagination
            offset = (page - 1) * size
            query = query.order_by(RouterDevice.last_seen.desc())
            query = query.offset(offset).limit(size)

            result = await self.db.execute(query)
            devices = result.scalars().all()

            return {
                "items": devices,
                "total": total,
                "page": page,
                "size": size,
                "pages": (total + size - 1) // size if size > 0 else 0,
            }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting devices for router {router_id}: {e}")
            raise RouterOperationError(f"Failed to get devices: {e}")

    async def create_device(
        self,
        router_id: int,
        device_name: str,
        device_type: str,
        mac_address: Optional[str] = None,
        ip_address: Optional[str] = None,
        is_online: bool = False,
    ) -> RouterDevice:
        """Create a new router device."""
        try:
            # Validate input
            if not device_name or len(device_name.strip()) < 1:
                raise ValidationError("Device name is required")
            if device_type not in ["hotspot", "pppoe", "dhcp", "static"]:
                raise ValidationError("Invalid device type")

            device = RouterDevice(
                router_id=router_id,
                device_name=device_name.strip(),
                device_type=device_type,
                mac_address=mac_address,
                ip_address=ip_address,
                is_online=is_online,
                last_seen=datetime.utcnow() if is_online else None,
            )

            self.db.add(device)
            await self.db.commit()
            await self.db.refresh(device)

            logger.info(f"Created device {device_name} for router {router_id}")
            return device

        except ValidationError:
            raise
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Database error creating device: {e}")
            raise RouterOperationError(f"Failed to create device: {e}")

    async def update_device(
        self,
        device_id: int,
        **kwargs,
    ) -> Optional[RouterDevice]:
        """Update a router device."""
        try:
            device = await self.get_device(device_id)
            if not device:
                return None

            # Update allowed fields
            allowed_fields = [
                "device_name",
                "device_type",
                "mac_address",
                "ip_address",
                "is_online",
                "bytes_sent",
                "bytes_received",
                "uptime",
            ]

            for field, value in kwargs.items():
                if field in allowed_fields and value is not None:
                    setattr(device, field, value)

            # Update last_seen if device is now online
            if kwargs.get("is_online"):
                device.last_seen = datetime.utcnow()

            await self.db.commit()
            await self.db.refresh(device)

            logger.info(f"Updated device {device_id}")
            return device

        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Database error updating device {device_id}: {e}")
            raise RouterOperationError(f"Failed to update device: {e}")

    async def delete_device(self, device_id: int) -> bool:
        """Delete a router device."""
        try:
            device = await self.get_device(device_id)
            if not device:
                return False

            await self.db.delete(device)
            await self.db.commit()

            logger.info(f"Deleted device {device_id}")
            return True

        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Database error deleting device {device_id}: {e}")
            raise RouterOperationError(f"Failed to delete device: {e}")

    async def get_device_stats(self, router_id: int) -> Dict[str, Any]:
        """Get device statistics for a router."""
        try:
            # Total devices
            total_query = select(func.count()).select_from(
                select(RouterDevice).where(RouterDevice.router_id == router_id).subquery()
            )
            total_result = await self.db.execute(total_query)
            total = total_result.scalar() or 0

            # Online devices
            online_query = select(func.count()).select_from(
                select(RouterDevice)
                .where(RouterDevice.router_id == router_id)
                .where(RouterDevice.is_online == True)
                .subquery()
            )
            online_result = await self.db.execute(online_query)
            online = online_result.scalar() or 0

            # Devices by type
            type_query = (
                select(RouterDevice.device_type, func.count())
                .where(RouterDevice.router_id == router_id)
                .group_by(RouterDevice.device_type)
            )
            type_result = await self.db.execute(type_query)
            by_type = {row[0]: row[1] for row in type_result.all()}

            # Total bandwidth
            bandwidth_query = select(
                func.sum(RouterDevice.bytes_sent),
                func.sum(RouterDevice.bytes_received),
            ).where(RouterDevice.router_id == router_id)
            bandwidth_result = await self.db.execute(bandwidth_query)
            bandwidth = bandwidth_result.one()

            return {
                "total_devices": total,
                "online_devices": online,
                "offline_devices": total - online,
                "devices_by_type": by_type,
                "total_bytes_sent": bandwidth[0] or 0,
                "total_bytes_received": bandwidth[1] or 0,
            }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting device stats for router {router_id}: {e}")
            return {"error": str(e)}

    async def mark_devices_offline(self, router_id: int) -> int:
        """Mark all devices for a router as offline."""
        try:
            result = await self.db.execute(
                select(RouterDevice)
                .where(RouterDevice.router_id == router_id)
                .where(RouterDevice.is_online == True)
            )
            devices = result.scalars().all()

            count = 0
            for device in devices:
                device.is_online = False
                count += 1

            await self.db.commit()
            logger.info(f"Marked {count} devices offline for router {router_id}")
            return count

        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Database error marking devices offline: {e}")
            return 0
