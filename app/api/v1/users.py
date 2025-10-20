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
from app.schemas.user import User as UserSchema, UserUpdate, UserProfile
from app.services.user_service import UserService

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
    """Get all users (admin only)."""
    user_service = UserService(db)
    result = await user_service.get_all(
        page=pagination.page,
        size=pagination.size,
        role=role,
        status=status,
        search=search,
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
