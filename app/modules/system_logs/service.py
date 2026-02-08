"""System logs service."""

from datetime import datetime, date
from typing import Any, Dict, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_log import SystemLog, LogLevel
from app.api.deps import PaginationParams
from app.core.tenant_middleware import get_current_organization_id


class SystemLogService:
    """System logs service."""

    def __init__(self, db: AsyncSession, organization_id: Optional[int] = None):
        self.db = db
        # Use explicitly passed org_id, or fall back to centralized tenant context
        self.organization_id = organization_id or get_current_organization_id()

    async def get_all(
        self,
        pagination: PaginationParams,
        level: Optional[LogLevel] = None,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Get all system logs with pagination and filters."""
        query = select(SystemLog).where(SystemLog.organization_id == self.organization_id)

        # Apply filters
        if level:
            query = query.where(SystemLog.level == level)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    SystemLog.message.ilike(search_term),
                    SystemLog.details.ilike(search_term),
                    SystemLog.action.ilike(search_term),
                    SystemLog.user_email.ilike(search_term)
                )
            )
        if date_from:
            query = query.where(func.date(SystemLog.timestamp) >= date_from)
        if date_to:
            query = query.where(func.date(SystemLog.timestamp) <= date_to)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get logs with pagination
        query = query.order_by(SystemLog.timestamp.desc())
        query = query.offset(pagination.offset).limit(pagination.size)

        result = await self.db.execute(query)
        logs = result.scalars().all()

        # Get statistics
        stats = await self.get_statistics()

        return {
            "items": logs,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size,
            "stats": stats,
        }

    async def create_log(
        self,
        level: LogLevel,
        message: str,
        details: Optional[str] = None,
        user_id: Optional[int] = None,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
    ) -> SystemLog:
        """Create a new system log."""
        log = SystemLog(
            organization_id=self.organization_id,
            level=level,
            message=message,
            details=details,
            user_id=user_id,
            user_email=user_email,
            ip_address=ip_address,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            timestamp=datetime.utcnow(),
        )

        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def get_statistics(self) -> Dict[str, Any]:
        """Get system log statistics."""
        # Count by level
        error_query = select(func.count()).where(
            and_(
                SystemLog.organization_id == self.organization_id,
                SystemLog.level == LogLevel.ERROR
            )
        )
        error_result = await self.db.execute(error_query)
        error_count = error_result.scalar()

        warning_query = select(func.count()).where(
            and_(
                SystemLog.organization_id == self.organization_id,
                SystemLog.level == LogLevel.WARNING
            )
        )
        warning_result = await self.db.execute(warning_query)
        warning_count = warning_result.scalar()

        info_query = select(func.count()).where(
            and_(
                SystemLog.organization_id == self.organization_id,
                SystemLog.level == LogLevel.INFO
            )
        )
        info_result = await self.db.execute(info_query)
        info_count = info_result.scalar()

        success_query = select(func.count()).where(
            and_(
                SystemLog.organization_id == self.organization_id,
                SystemLog.level == LogLevel.SUCCESS
            )
        )
        success_result = await self.db.execute(success_query)
        success_count = success_result.scalar()

        # Total logs
        total_query = select(func.count()).where(
            SystemLog.organization_id == self.organization_id
        )
        total_result = await self.db.execute(total_query)
        total_logs = total_result.scalar()

        return {
            "error_count": error_count or 0,
            "warning_count": warning_count or 0,
            "info_count": info_count or 0,
            "success_count": success_count or 0,
            "total_logs": total_logs or 0,
        }
