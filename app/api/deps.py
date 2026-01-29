"""API dependencies and middleware."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Union

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.core.security import verify_token
from app.models.user import User, UserRole
from app.modules.auth import UserService


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Use this when you need a database session outside of FastAPI's
    dependency injection (e.g., in webhook handlers, background tasks).

    Usage:
        async with get_db_session() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class OAuth2PasswordBearerOrHTTPBearer(OAuth2PasswordBearer):
    """
    Custom security scheme that supports both OAuth2 password bearer (for Swagger UI)
    and HTTP Bearer token (for manual API usage).
    """
    
    def __init__(self, tokenUrl: str, auto_error: bool = True):
        super().__init__(tokenUrl=tokenUrl, auto_error=auto_error)
        self.http_bearer = HTTPBearer(auto_error=False)
    
    async def __call__(self, request: Request) -> Optional[str]:
        # First try OAuth2 password bearer (for Swagger UI)
        try:
            token = await super().__call__(request)
            if token:
                return token
        except HTTPException:
            pass
        
        # Then try HTTP Bearer (for manual API usage)
        try:
            credentials = await self.http_bearer(request)
            if credentials:
                return credentials.credentials
        except HTTPException:
            pass
        
        # If auto_error is True and no token found, raise exception
        if self.auto_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


# Security scheme that supports both OAuth2 and Bearer token
security_scheme = OAuth2PasswordBearerOrHTTPBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user_bearer(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user via Bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(credentials.credentials)
    if token_data is None:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user_oauth2(
    token: str = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user via OAuth2 token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(token)
    if token_data is None:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user(
    token: str = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user (supports both OAuth2 and Bearer token)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(token)
    if token_data is None:
        raise credentials_exception

    user_service = UserService(db)
    user = await user_service.get_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


async def get_current_verified_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Get current verified user."""
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not verified"
        )
    return current_user


def require_role(required_role: UserRole):
    """Require specific user role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        # Platform owner has access to everything
        if current_user.role == UserRole.PLATFORM_OWNER:
            return current_user
        # ISP_ADMIN is treated as the legacy ADMIN for backwards compatibility
        if current_user.role == UserRole.ISP_ADMIN and required_role == UserRole.ADMIN:
            return current_user
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_admin():
    """Require admin role (ISP_ADMIN or PLATFORM_OWNER)."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        # Support both old ADMIN role and new ISP_ADMIN role
        admin_roles = [UserRole.PLATFORM_OWNER, UserRole.ISP_ADMIN]
        # Also support legacy ADMIN if it exists in enum
        if hasattr(UserRole, 'ADMIN'):
            admin_roles.append(UserRole.ADMIN)
        if current_user.role not in admin_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_technician_or_admin():
    """Require technician or admin role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        # Support both old and new role names
        allowed_roles = [UserRole.PLATFORM_OWNER, UserRole.ISP_ADMIN, UserRole.ISP_TECHNICIAN]
        # Also support legacy roles if they exist
        if hasattr(UserRole, 'ADMIN'):
            allowed_roles.append(UserRole.ADMIN)
        if hasattr(UserRole, 'TECHNICIAN'):
            allowed_roles.append(UserRole.TECHNICIAN)
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_customer_or_admin():
    """Require customer or admin role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        allowed_roles = [UserRole.PLATFORM_OWNER, UserRole.ISP_ADMIN, UserRole.CUSTOMER]
        # Also support legacy ADMIN if it exists
        if hasattr(UserRole, 'ADMIN'):
            allowed_roles.append(UserRole.ADMIN)
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


class PaginationParams:
    """Pagination parameters."""

    def __init__(
        self,
        page: int = 1,
        size: int = 20,
        max_size: int = 100,
    ):
        if page < 1:
            page = 1
        if size < 1:
            size = 20
        if size > max_size:
            size = max_size
        
        self.page = page
        self.size = size
        self.offset = (page - 1) * size


def get_pagination_params(
    page: int = 1,
    size: int = 20,
) -> PaginationParams:
    """Get pagination parameters."""
    return PaginationParams(page=page, size=size)
