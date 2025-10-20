"""API dependencies and middleware."""

from typing import AsyncGenerator, Optional, Union

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_token
from app.models.user import User, UserRole
from app.services.user_service import UserService


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
        if current_user.role != required_role and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


def require_admin():
    """Require admin role."""
    return require_role(UserRole.ADMIN)


def require_technician_or_admin():
    """Require technician or admin role."""
    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in [UserRole.ADMIN, UserRole.TECHNICIAN]:
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
        if current_user.role not in [UserRole.ADMIN, UserRole.CUSTOMER]:
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
