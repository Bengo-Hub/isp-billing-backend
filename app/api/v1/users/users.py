"""Users API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_pagination_params,
    PaginationParams,
    require_admin,
    require_technician_or_admin,
)
from app.core.database import get_db
from app.models.user import User, UserRole, UserStatus
from app.core.security import get_password_hash, create_access_token
from app.schemas.user import User as UserSchema, UserUpdate, UserProfile, AdminSetPassword
from app.modules.auth import UserService

router = APIRouter()


@router.get("/me", response_model=UserProfile)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Get current user profile with statistics."""
    user_service = UserService(db)
    stats = await user_service.get_user_stats(current_user.id)
    
    # Convert User to UserProfile with stats
    profile_data = current_user.to_dict()
    profile_data.update(stats)
    
    return UserProfile(**profile_data)


@router.patch("/me", response_model=UserSchema)
async def update_current_user(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Update current user profile."""
    user_service = UserService(db)
    updated_user = await user_service.update_user(current_user.id, user_data)
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(updated_user)


@router.get("/", response_model=Dict[str, Any])
async def get_users(
    pagination: PaginationParams = Depends(get_pagination_params),
    role: Optional[UserRole] = Query(None, description="Filter by user role"),
    status: Optional[UserStatus] = Query(None, description="Filter by user status"),
    search: Optional[str] = Query(None, description="Search in username, email, or name"),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get all users (admin only).

    Platform owners see all users. ISP admins are scoped to their organization.
    """
    user_service = UserService(db)

    # ISP admins are scoped to their own org
    organization_id = None
    if current_user.role != UserRole.PLATFORM_OWNER:
        organization_id = current_user.organization_id

    result = await user_service.get_all(
        page=pagination.page,
        size=pagination.size,
        role=role,
        status=status,
        search=search,
        organization_id=organization_id,
    )

    # Convert SQLAlchemy models to Pydantic schemas
    users_data = [UserSchema.model_validate(user) for user in result["users"]]
    result["users"] = users_data

    return result


@router.get("/{user_id}", response_model=UserSchema)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Get user by ID."""
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(user)


@router.patch("/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Update user (admin only)."""
    user_service = UserService(db)
    updated_user = await user_service.update_user(user_id, user_data)
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(updated_user)


@router.patch("/{user_id}/status", response_model=UserSchema)
async def update_user_status(
    user_id: int,
    status: UserStatus,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Update user status (admin only)."""
    user_service = UserService(db)
    updated_user = await user_service.update_user_status(user_id, status)
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(updated_user)


@router.patch("/{user_id}/role", response_model=UserSchema)
async def update_user_role(
    user_id: int,
    role: UserRole,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Update user role (admin only)."""
    user_service = UserService(db)
    updated_user = await user_service.update_user_role(user_id, role)
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(updated_user)


@router.patch("/{user_id}/activate", response_model=UserSchema)
async def activate_user(
    user_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Activate user (admin only)."""
    user_service = UserService(db)
    updated_user = await user_service.activate_user(user_id)
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(updated_user)


@router.patch("/{user_id}/deactivate", response_model=UserSchema)
async def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Deactivate user (admin only)."""
    user_service = UserService(db)
    updated_user = await user_service.deactivate_user(user_id)
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserSchema.model_validate(updated_user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Delete user (admin only)."""
    user_service = UserService(db)
    success = await user_service.delete_user(user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {"message": "User deleted successfully"}


@router.post("/{user_id}/set-password")
async def admin_set_password(
    user_id: int,
    password_data: AdminSetPassword,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Set a user's password (admin only). Does not require the current password."""
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent non-platform-owners from changing platform owner passwords
    if user.role == UserRole.PLATFORM_OWNER and current_user.role != UserRole.PLATFORM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change platform owner password",
        )

    user.hashed_password = get_password_hash(password_data.new_password)
    await db.commit()

    return {"message": "Password updated successfully"}


@router.post("/{user_id}/generate-api-token")
async def generate_api_token(
    user_id: int,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Generate a long-lived API token for a user (admin only)."""
    from datetime import timedelta

    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "organization_id": user.organization_id,
            "token_purpose": "api",
        },
        expires_delta=timedelta(days=365),
    )

    return {
        "token": token,
        "user_id": user.id,
        "username": user.username,
        "expires_in_days": 365,
    }
