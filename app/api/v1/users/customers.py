"""ISP Customer users API endpoints."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_pagination_params,
    PaginationParams,
    require_technician_or_admin,
)
from app.core.database import get_db
from app.models.user import User, UserRole, UserStatus
from app.schemas.user import User as UserSchema
from app.modules.auth import UserService

router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def get_customer_users(
    pagination: PaginationParams = Depends(get_pagination_params),
    status: Optional[UserStatus] = Query(None, description="Filter by user status"),
    search: Optional[str] = Query(None, description="Search in username, email, or name"),
    organization_id: Optional[int] = Query(None, description="Filter by organization (platform owners only)"),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get ISP customer users.

    Platform owners can optionally filter by organization_id.
    ISP staff are automatically scoped to their own organization.
    """
    user_service = UserService(db)

    # ISP staff scoped to their org; platform owners can specify or see all
    org_id = organization_id
    if current_user.role != UserRole.PLATFORM_OWNER:
        org_id = current_user.organization_id

    result = await user_service.get_customer_users(
        organization_id=org_id,
        page=pagination.page,
        size=pagination.size,
        status=status,
        search=search,
    )

    result["users"] = [UserSchema.model_validate(u) for u in result["users"]]
    return result
