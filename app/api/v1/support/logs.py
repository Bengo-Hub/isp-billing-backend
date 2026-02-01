"""System Logs API endpoints."""

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.models.system_log import LogLevel
from app.schemas.system_log import (
    SystemLog, SystemLogCreate, SystemLogListResponse, SystemLogStats
)
from app.modules.system_logs import SystemLogService

router = APIRouter()


@router.get("/system", response_model=SystemLogListResponse)
async def get_system_logs(
    pagination: PaginationParams = Depends(),
    level: Optional[LogLevel] = Query(None, description="Filter by log level"),
    search: Optional[str] = Query(None, description="Search in message, details, action, or user email"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SystemLogListResponse:
    """Get all system logs with pagination and filters."""
    service = SystemLogService(db, current_user.organization_id)
    result = await service.get_all(
        pagination=pagination,
        level=level,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    return SystemLogListResponse(**result)


@router.post("/system", response_model=SystemLog, status_code=status.HTTP_201_CREATED)
async def create_system_log(
    log_data: SystemLogCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SystemLog:
    """Create a new system log."""
    service = SystemLogService(db, current_user.organization_id)
    log = await service.create_log(
        level=log_data.level,
        message=log_data.message,
        details=log_data.details,
        user_id=current_user.id,
        user_email=log_data.user_email or current_user.email,
        ip_address=log_data.ip_address,
        action=log_data.action,
        entity_type=log_data.entity_type,
        entity_id=log_data.entity_id,
    )
    return log


@router.get("/system/stats", response_model=SystemLogStats)
async def get_system_log_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SystemLogStats:
    """Get system log statistics."""
    service = SystemLogService(db, current_user.organization_id)
    stats = await service.get_statistics()
    return SystemLogStats(**stats)
