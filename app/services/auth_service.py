"""Authentication service."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.user import User, UserSession, UserVerification
from app.schemas.user import UserCreate
from app.services.notification_service import NotificationService


class AuthService:
    """Authentication service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.notification_service = NotificationService(db)

    async def register_user(self, user_data: UserCreate) -> User:
        """Register a new user."""
        # Check if user already exists
        existing_user = await self.get_user_by_username(user_data.username)
        if existing_user:
            raise ValueError("Username already registered")

        existing_user = await self.get_user_by_email(user_data.email)
        if existing_user:
            raise ValueError("Email already registered")

        # Create user
        hashed_password = get_password_hash(user_data.password)
        user = User(
            username=user_data.username,
            email=user_data.email,
            phone=user_data.phone,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            hashed_password=hashed_password,
            role=user_data.role,
            bio=user_data.bio,
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        # Send verification email
        await self._send_verification_email(user)

        return user

    async def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Authenticate user with username and password."""
        user = await self.get_user_by_username(username)
        if not user:
            return None

        if not verify_password(password, user.hashed_password):
            return None

        return user

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def update_last_login(self, user_id: int) -> None:
        """Update user's last login timestamp."""
        user = await self.db.get(User, user_id)
        if user:
            user.last_login = datetime.utcnow()
            await self.db.commit()

    async def logout_user(self, user_id: int) -> None:
        """Logout user by deactivating all sessions."""
        result = await self.db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.is_active == True
            )
        )
        sessions = result.scalars().all()
        
        for session in sessions:
            session.is_active = False
        
        await self.db.commit()

    async def verify_user(self, token: str, verification_type: str) -> bool:
        """Verify user with token."""
        result = await self.db.execute(
            select(UserVerification).where(
                UserVerification.token == token,
                UserVerification.verification_type == verification_type,
                UserVerification.is_used == False,
                UserVerification.expires_at > datetime.utcnow()
            )
        )
        verification = result.scalar_one_or_none()
        
        if not verification:
            return False

        # Mark verification as used
        verification.is_used = True

        # Update user verification status
        user = await self.db.get(User, verification.user_id)
        if user:
            if verification_type == "email":
                user.is_verified = True
                user.email_verified_at = datetime.utcnow()
            elif verification_type == "phone":
                user.phone_verified_at = datetime.utcnow()

        await self.db.commit()
        return True

    async def resend_verification(self, user_id: int) -> None:
        """Resend verification email or SMS."""
        user = await self.db.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        if user.is_verified:
            raise ValueError("User already verified")

        await self._send_verification_email(user)

    async def request_password_reset(self, email: str) -> None:
        """Request password reset."""
        user = await self.get_user_by_email(email)
        if not user:
            # Don't reveal if email exists
            return

        # Create password reset token
        token = str(uuid4())
        verification = UserVerification(
            user_id=user.id,
            verification_type="password_reset",
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )

        self.db.add(verification)
        await self.db.commit()

        # Send password reset email
        await self.notification_service.send_password_reset_email(user, token)

    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password with token."""
        result = await self.db.execute(
            select(UserVerification).where(
                UserVerification.token == token,
                UserVerification.verification_type == "password_reset",
                UserVerification.is_used == False,
                UserVerification.expires_at > datetime.utcnow()
            )
        )
        verification = result.scalar_one_or_none()
        
        if not verification:
            return False

        # Update password
        user = await self.db.get(User, verification.user_id)
        if user:
            user.hashed_password = get_password_hash(new_password)
            verification.is_used = True
            await self.db.commit()
            return True

        return False

    async def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> bool:
        """Change user password."""
        user = await self.db.get(User, user_id)
        if not user:
            return False

        if not verify_password(current_password, user.hashed_password):
            return False

        user.hashed_password = get_password_hash(new_password)
        await self.db.commit()
        return True

    async def get_user_sessions(
        self, user_id: int, page: int = 1, size: int = 20
    ) -> Dict[str, Any]:
        """Get user sessions with pagination."""
        offset = (page - 1) * size
        
        # Get total count
        count_result = await self.db.execute(
            select(UserSession).where(UserSession.user_id == user_id)
        )
        total = len(count_result.scalars().all())

        # Get sessions
        result = await self.db.execute(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        sessions = result.scalars().all()

        return {
            "sessions": sessions,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,
        }

    async def revoke_session(self, session_id: int, user_id: int) -> bool:
        """Revoke a specific session."""
        result = await self.db.execute(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.user_id == user_id
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            return False

        session.is_active = False
        await self.db.commit()
        return True

    async def revoke_all_sessions(self, user_id: int) -> None:
        """Revoke all user sessions."""
        result = await self.db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.is_active == True
            )
        )
        sessions = result.scalars().all()
        
        for session in sessions:
            session.is_active = False
        
        await self.db.commit()

    async def _send_verification_email(self, user: User) -> None:
        """Send verification email to user."""
        # Create verification token
        token = str(uuid4())
        verification = UserVerification(
            user_id=user.id,
            verification_type="email",
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )

        self.db.add(verification)
        await self.db.commit()

        # Send email
        await self.notification_service.send_verification_email(user, token)
