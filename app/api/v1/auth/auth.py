"""Authentication API endpoints."""

from datetime import timedelta, datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_pagination_params, PaginationParams
from app.core.database import get_db
from app.core.security import create_token_pair, verify_token
from app.models.user import User
from app.schemas.user import (
    TokenRefresh,
    User as UserSchema,
    UserCreate,
    UserLogin,
    UserPasswordChange,
    UserPasswordReset,
    UserPasswordResetConfirm,
    UserVerification,
)
from app.schemas.auth import Token
from app.modules.auth import AuthService, UserService

router = APIRouter()


@router.post("/register", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Register a new user."""
    auth_service = AuthService(db)
    user = await auth_service.register_user(user_data)
    return UserSchema.model_validate(user)


@router.post("/login",
            summary="User Login", 
            description="Login with username and password to get access tokens. Compatible with OAuth2 password flow for Swagger UI.",
            responses={
                200: {
                    "description": "Successful login",
                    "content": {
                        "application/json": {
                            "example": {
                                "data": {
                                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                    "token_type": "bearer",
                                    "expires_in": 1800,
                                    "user": {"id": 1, "username": "admin", "email": "admin@example.com"}
                                }
                            }
                        }
                    }
                },
                401: {"description": "Invalid credentials"},
                400: {"description": "Inactive user"}
            })
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Login user and return JWT tokens wrapped in a `data` envelope including user info.
    """
    auth_service = AuthService(db)
    user = await auth_service.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # Check if 2FA is enabled — return challenge token instead of full access
    from sqlalchemy import select as sa_select
    from app.models.user_settings import UserSettings
    from app.core.security import create_2fa_challenge_token

    settings_result = await db.execute(
        sa_select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings = settings_result.scalar_one_or_none()

    if (
        user_settings
        and user_settings.two_factor_enabled
        and user_settings.two_factor_confirmed_at
    ):
        challenge_token = create_2fa_challenge_token(
            user_id=user.id,
            username=user.username,
            role=user.role.value,
            organization_id=user.organization_id,
        )
        return {
            "data": {
                "requires_2fa": True,
                "temp_token": challenge_token,
                "message": "Two-factor authentication required.",
            }
        }
    
    # Create tokens
    token_data = create_token_pair(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )
    
    # Update last login
    await auth_service.update_last_login(user.id)
    
    # Prepare user payload
    user_payload = UserSchema.model_validate(user).model_dump()

    # Compute effective permissions (role-derived + user overrides)
    permissions = []
    seen = set()
    now = datetime.utcnow()

    if getattr(user, "role_obj", None) and getattr(user.role_obj, "permissions", None):
        for p in user.role_obj.permissions:
            permissions.append({
                "id": p.id,
                "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                "resource": p.resource,
                "description": p.description,
            })
            seen.add(p.id)

    for up in getattr(user, "permission_overrides", []) or []:
        # Skip expired overrides
        if up.expires_at and up.expires_at < now:
            continue
        p = up.permission
        if not p:
            continue
        if up.is_granted:
            if p.id not in seen:
                permissions.append({
                    "id": p.id,
                    "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                    "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                    "resource": p.resource,
                    "description": p.description,
                })
                seen.add(p.id)
        else:
            # Deny => remove if present
            permissions = [pp for pp in permissions if pp.get("id") != p.id]
            if p.id in seen:
                seen.remove(p.id)

    user_payload["permissions"] = permissions

    # Include organization info for all users (except platform superuser)
    organization_info = None
    customer_portal_info = None

    if user.organization_id:
        from sqlalchemy import select
        from app.models.organization import Organization

        # Get organization details
        org_result = await db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        organization = org_result.scalar_one_or_none()

        if organization:
            organization_info = {
                "organization_id": organization.id,
                "organization_slug": organization.slug,
                "organization_name": organization.name,
            }

            # For customers, include subscription-specific portal URL
            if user.role.value == "customer":
                from app.models.subscription import Subscription, SubscriptionType

                # Get customer's active subscription type
                sub_result = await db.execute(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.status.in_(["active", "suspended"])
                    ).order_by(Subscription.created_at.desc()).limit(1)
                )
                subscription = sub_result.scalar_one_or_none()

                customer_portal_info = {
                    "organization_slug": organization.slug,
                    "subscription_type": subscription.subscription_type.value if subscription else "hotspot",
                    "portal_url": f"/{organization.slug}/portal/{'pppoe' if subscription and subscription.subscription_type == SubscriptionType.PPPOE else 'hotspot'}"
                }

    response_data = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "token_type": token_data["token_type"],
        "expires_in": 30 * 60,  # 30 minutes
        "user": user_payload,
    }

    # Add organization info for ISP users (isp_admin, isp_technician)
    if organization_info and user.role.value in ["isp_admin", "isp_technician"]:
        response_data["organization"] = organization_info

    # Add customer portal info for customers
    if customer_portal_info:
        response_data["customer_portal"] = customer_portal_info

    return {"data": response_data}


@router.post("/refresh")
async def refresh_token(
    token_data: TokenRefresh,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token (returns wrapped `data`)."""
    auth_service = AuthService(db)
    
    # Verify refresh token
    token_info = verify_token(token_data.refresh_token, token_type="refresh")
    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Get user
    user_service = UserService(db)
    user = await user_service.get_by_id(token_info.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    # Create new tokens
    new_token_data = create_token_pair(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )
    
    return {
        "data": {
            "access_token": new_token_data["access_token"],
            "refresh_token": new_token_data["refresh_token"],
            "token_type": new_token_data["token_type"],
            "expires_in": 30 * 60,
        }
    }


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Logout user and invalidate tokens."""
    auth_service = AuthService(db)
    await auth_service.logout_user(current_user.id)
    return {"message": "Successfully logged out"}


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current user information (wrapped in `data`)."""
    # Convert SQLAlchemy model to Pydantic schema
    user_payload = UserSchema.model_validate(current_user).model_dump()

    # Attach effective permissions
    permissions = []
    seen = set()
    now = datetime.utcnow()

    if getattr(current_user, "role_obj", None) and getattr(current_user.role_obj, "permissions", None):
        for p in current_user.role_obj.permissions:
            permissions.append({
                "id": p.id,
                "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                "resource": p.resource,
                "description": p.description,
            })
            seen.add(p.id)

    for up in getattr(current_user, "permission_overrides", []) or []:
        if up.expires_at and up.expires_at < now:
            continue
        p = up.permission
        if not p:
            continue
        if up.is_granted:
            if p.id not in seen:
                permissions.append({
                    "id": p.id,
                    "module": p.module.value if hasattr(p.module, "value") else str(p.module),
                    "action": p.action.value if hasattr(p.action, "value") else str(p.action),
                    "resource": p.resource,
                    "description": p.description,
                })
                seen.add(p.id)
        else:
            permissions = [pp for pp in permissions if pp.get("id") != p.id]
            if p.id in seen:
                seen.remove(p.id)

    user_payload["permissions"] = permissions
    return {"data": user_payload}


@router.post("/verify")
async def verify_user(
    verification_data: UserVerification,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Verify user email or phone."""
    auth_service = AuthService(db)
    success = await auth_service.verify_user(
        verification_data.token,
        verification_data.verification_type,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        )
    
    return {"message": "User verified successfully"}


@router.post("/resend-verification")
async def resend_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Resend verification email or SMS."""
    auth_service = AuthService(db)
    await auth_service.resend_verification(current_user.id)
    return {"message": "Verification sent successfully"}


@router.post("/forgot-password")
async def forgot_password(
    password_reset_data: UserPasswordReset,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Request password reset."""
    auth_service = AuthService(db)
    await auth_service.request_password_reset(password_reset_data.email)
    return {"message": "Password reset instructions sent to your email"}


@router.post("/reset-password")
async def reset_password(
    password_reset_data: UserPasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Reset password with token."""
    auth_service = AuthService(db)
    success = await auth_service.reset_password(
        password_reset_data.token,
        password_reset_data.new_password,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    return {"message": "Password reset successfully"}


@router.post("/change-password")
async def change_password(
    password_data: UserPasswordChange,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Change user password."""
    auth_service = AuthService(db)
    success = await auth_service.change_password(
        current_user.id,
        password_data.current_password,
        password_data.new_password,
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    return {"message": "Password changed successfully"}


@router.get("/sessions")
async def get_user_sessions(
    current_user: User = Depends(get_current_user),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get user active sessions."""
    auth_service = AuthService(db)
    sessions = await auth_service.get_user_sessions(
        current_user.id,
        page=pagination.page,
        size=pagination.size,
    )
    return sessions


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Revoke a specific session."""
    auth_service = AuthService(db)
    success = await auth_service.revoke_session(session_id, current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    return {"message": "Session revoked successfully"}


@router.delete("/sessions")
async def revoke_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Revoke all user sessions except current one."""
    auth_service = AuthService(db)
    await auth_service.revoke_all_sessions(current_user.id)
    return {"message": "All sessions revoked successfully"}
