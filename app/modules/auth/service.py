"""
Enhanced authentication service with RBAC support.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User, UserRole
from app.schemas.auth import Token
from app.core.security import TokenData, verify_password as verify_pwd, get_password_hash as hash_pwd

logger = get_logger(__name__)

# JWT settings
SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days


class AuthService:
    """Authentication service with RBAC support."""
    
    def __init__(self, db: AsyncSession):
        self.db = db

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return verify_pwd(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        """Hash a password."""
        return hash_pwd(password)

    def create_access_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    def create_refresh_token(self, data: Dict[str, Any]) -> str:
        """Create a JWT refresh token."""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    async def authenticate_user(self, username_or_email: str, password: str) -> Optional[User]:
        """Authenticate a user with username/email and password.

        Eagerly load RBAC relationships to avoid async lazy-loads that require greenlet.
        """
        try:
            # Try to find user by username or email and eagerly load role and permissions
            from sqlalchemy.orm import selectinload
            from app.models.rbac import Role, UserPermission

            query = (
                select(User)
                .where(
                    (User.email == username_or_email) | (User.username == username_or_email),
                    User.is_active.is_(True)
                )
                .options(
                    selectinload(User.role_obj).selectinload(Role.permissions),
                    selectinload(User.permission_overrides).selectinload(UserPermission.permission),
                )
            )

            result = await self.db.execute(query)
            user = result.scalar_one_or_none()

            if not user:
                return None

            if not self.verify_password(password, user.hashed_password):
                return None

            # Update last login (use naive UTC to match DB timestamp defaults)
            user.last_login = datetime.utcnow()
            await self.db.commit()

            return user

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        try:
            result = await self.db.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            return None

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        try:
            result = await self.db.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by email: {e}")
            return None

    def verify_token(self, token: str) -> Optional[TokenData]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id: int = payload.get("sub")
            token_type: str = payload.get("type")
            username: str = payload.get("username")
            role: str = payload.get("role")
            
            if user_id is None or token_type != "access":
                return None
                
            return TokenData(user_id=user_id, username=username, role=role)
            
        except JWTError:
            return None

    def create_provisioning_token(self, user_id: int, router_id: int, permissions: list) -> str:
        """Create a specialized token for router provisioning."""
        data = {
            "sub": user_id,
            "router_id": router_id,
            "permissions": permissions,
            "purpose": "provisioning",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1)  # Short-lived token
        }
        return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

    def verify_provisioning_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify a provisioning token."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("purpose") != "provisioning":
                return None
            return payload
        except JWTError:
            return None

    def check_permission(self, user: User, required_permission: str) -> bool:
        """Check if user has required permission based on role."""
        role_permissions = {
            UserRole.ADMIN: [
                "users.create", "users.read", "users.update", "users.delete",
                "routers.create", "routers.read", "routers.update", "routers.delete",
                "provisioning.create", "provisioning.read", "provisioning.update",
                "billing.create", "billing.read", "billing.update", "billing.delete",
                "settings.read", "settings.update"
            ],
            UserRole.TECHNICIAN: [
                "routers.read", "routers.update",
                "provisioning.create", "provisioning.read", "provisioning.update",
                "billing.read"
            ],
            UserRole.CUSTOMER: [
                "routers.read",
                "billing.read"
            ]
        }
        
        user_permissions = role_permissions.get(user.role, [])
        return required_permission in user_permissions

    async def update_last_login(self, user_id: int) -> None:
        """Update user's last login timestamp."""
        try:
            user = await self.get_user_by_id(user_id)
            if user:
                # Use naive UTC datetime to be consistent with model defaults
                user.last_login = datetime.utcnow()
                await self.db.commit()
        except Exception as e:
            logger.error(f"Error updating last login: {e}")

    async def login(self, username_or_email: str, password: str) -> Token:
        """Authenticate user and return tokens."""
        user = await self.authenticate_user(username_or_email, password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token = self.create_access_token(
            data={"sub": user.id, "username": user.username, "role": user.role.value}
        )
        refresh_token = self.create_refresh_token(
            data={"sub": user.id, "username": user.username}
        )
        
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )