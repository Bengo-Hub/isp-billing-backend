"""Admin-only API endpoints for system management."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.user import User
from app.services.data_integrity_service import DataIntegrityService

router = APIRouter()


@router.get("/data-integrity/check", response_model=Dict[str, Any])
async def check_data_integrity(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Check for data integrity issues (admin only)."""
    service = DataIntegrityService(db)
    summary = await service.get_integrity_summary()
    return summary


@router.post("/data-integrity/fix-orphaned-subscriptions")
async def fix_orphaned_subscriptions(
    dry_run: bool = Query(True, description="If true, only shows what would be fixed without making changes"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Fix orphaned subscriptions (admin only)."""
    service = DataIntegrityService(db)
    result = await service.fix_orphaned_subscriptions(dry_run=dry_run)
    return result


@router.post("/data-integrity/log-issues")
async def log_integrity_issues(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Log all data integrity issues to the system logs (admin only)."""
    service = DataIntegrityService(db)
    await service.log_integrity_issues()
    return {"message": "Data integrity issues logged successfully"}
