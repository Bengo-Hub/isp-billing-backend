"""Platform users API endpoints."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_pagination_params,
    PaginationParams,
)
from app.api.deps_tenant import require_platform_owner
from app.core.database import get_db
from app.models.user import User, UserStatus
from app.schemas.user import User as UserSchema
from app.modules.auth import UserService

router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def get_platform_users(
    pagination: PaginationParams = Depends(get_pagination_params),
    status: Optional[UserStatus] = Query(None, description="Filter by user status"),
    search: Optional[str] = Query(None, description="Search in username, email, or name"),
    current_user: User = Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get platform-level users (platform owners only).

    Returns users with PLATFORM_OWNER role and no organization.
    """
    user_service = UserService(db)

    result = await user_service.get_platform_users(
        page=pagination.page,
        size=pagination.size,
        status=status,
        search=search,
    )

    result["users"] = [UserSchema.model_validate(u) for u in result["users"]]
    return result
