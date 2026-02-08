"""User service."""

import re
from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.models.user import User, UserRole, UserStatus
from app.schemas.user import UserUpdate
from app.core.logging import get_logger
from app.core.exceptions import ValidationError, AuthenticationError


class UserService:
    """User service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    # Validation methods
    def _validate_email(self, email: str) -> bool:
        """Validate email format."""
        if not email:
            return False
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    def _validate_phone_number(self, phone_number: str) -> bool:
        """Validate phone number format."""
        if not phone_number:
            return True  # Phone number is optional
        # Remove any non-digit characters
        clean_phone = re.sub(r'\D', '', phone_number)
        # Check if it's a valid phone number (10-15 digits)
        return len(clean_phone) >= 10 and len(clean_phone) <= 15

    def _validate_username(self, username: str) -> bool:
        """Validate username format."""
        if not username or len(username) < 3 or len(username) > 50:
            return False
        # Username should only contain alphanumeric characters and underscores
        pattern = r'^[a-zA-Z0-9_]+$'
        return bool(re.match(pattern, username))

    def _validate_password_strength(self, password: str) -> bool:
        """Validate password strength."""
        if not password or len(password) < 8:
            return False
        # Password should contain at least one uppercase, one lowercase, one digit
        has_upper = bool(re.search(r'[A-Z]', password))
        has_lower = bool(re.search(r'[a-z]', password))
        has_digit = bool(re.search(r'\d', password))
        return has_upper and has_lower and has_digit

    def _validate_user_data(self, user_data: Dict[str, Any]) -> None:
        """Validate user data."""
        if 'email' in user_data and not self._validate_email(user_data['email']):
            raise ValidationError("Invalid email format")
        
        if 'phone_number' in user_data and not self._validate_phone_number(user_data['phone_number']):
            raise ValidationError("Invalid phone number format")
        
        if 'username' in user_data and not self._validate_username(user_data['username']):
            raise ValidationError("Username must be 3-50 characters long and contain only alphanumeric characters and underscores")
        
        if 'password' in user_data and not self._validate_password_strength(user_data['password']):
            raise ValidationError("Password must be at least 8 characters long and contain uppercase, lowercase, and numeric characters")

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID with production-ready error handling.

        Eagerly load RBAC relationships to avoid async lazy-loads when the user is used in request context.
        """
        try:
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValidationError("Invalid user ID")

            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.models.rbac import Role, UserPermission

            query = (
                select(User)
                .where(User.id == user_id)
                .options(
                    selectinload(User.role_obj).selectinload(Role.permissions),
                    selectinload(User.permission_overrides).selectinload(UserPermission.permission),
                )
            )

            result = await self.db.execute(query)
            user = result.scalar_one_or_none()

            if user:
                self.logger.debug(f"Retrieved user {user_id}: {user.username}")
            return user
        except SQLAlchemyError as e:
            self.logger.error(f"Database error retrieving user {user_id}: {e}")
            raise ValidationError(f"Failed to retrieve user: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error retrieving user {user_id}: {e}")
            raise ValidationError(f"Unexpected error: {e}")

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        size: int = 20,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        search: Optional[str] = None,
        organization_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get all users with pagination and filters."""
        query = select(User)

        # Scope to organization if provided
        if organization_id is not None:
            query = query.where(User.organization_id == organization_id)

        # Apply filters
        if role:
            query = query.where(User.role == role)
        if status:
            query = query.where(User.status == status)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (User.username.ilike(search_term))
                | (User.email.ilike(search_term))
                | (User.first_name.ilike(search_term))
                | (User.last_name.ilike(search_term))
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Calculate offset
        offset = (page - 1) * size

        # Get users with pagination
        query = query.order_by(User.created_at.desc())
        query = query.offset(offset).limit(size)

        result = await self.db.execute(query)
        users = result.scalars().all()

        return {
            "users": users,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,
        }

    async def _paginated_query(
        self,
        query,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """Helper: apply pagination to a query and return standardized result."""
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        offset = (page - 1) * size
        query = query.order_by(User.created_at.desc()).offset(offset).limit(size)

        result = await self.db.execute(query)
        users = result.scalars().all()

        return {
            "users": users,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,
        }

    def _apply_search(self, query, search: Optional[str]):
        """Helper: add search filter to a query."""
        if not search:
            return query
        term = f"%{search}%"
        return query.where(
            (User.username.ilike(term))
            | (User.email.ilike(term))
            | (User.first_name.ilike(term))
            | (User.last_name.ilike(term))
        )

    async def get_platform_users(
        self,
        page: int = 1,
        size: int = 20,
        status: Optional[UserStatus] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get platform-level users (PLATFORM_OWNER role, no organization)."""
        query = select(User).where(
            User.role == UserRole.PLATFORM_OWNER,
            User.organization_id.is_(None),
        )
        if status:
            query = query.where(User.status == status)
        query = self._apply_search(query, search)
        return await self._paginated_query(query, page, size)

    async def get_staff_users(
        self,
        organization_id: Optional[int] = None,
        page: int = 1,
        size: int = 20,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get ISP staff users (ISP_ADMIN + ISP_TECHNICIAN) for a tenant."""
        staff_roles = [UserRole.ISP_ADMIN, UserRole.ISP_TECHNICIAN]
        query = select(User).where(User.role.in_(staff_roles))

        if organization_id is not None:
            query = query.where(User.organization_id == organization_id)
        if role and role in staff_roles:
            query = query.where(User.role == role)
        if status:
            query = query.where(User.status == status)
        query = self._apply_search(query, search)
        return await self._paginated_query(query, page, size)

    async def get_customer_users(
        self,
        organization_id: Optional[int] = None,
        page: int = 1,
        size: int = 20,
        status: Optional[UserStatus] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get ISP customer users (CUSTOMER role) for a tenant."""
        query = select(User).where(User.role == UserRole.CUSTOMER)

        if organization_id is not None:
            query = query.where(User.organization_id == organization_id)
        if status:
            query = query.where(User.status == status)
        query = self._apply_search(query, search)
        return await self._paginated_query(query, page, size)

    async def update_user(self, user_id: int, user_data: UserUpdate) -> Optional[User]:
        """Update user information."""
        user = await self.get_by_id(user_id)
        if not user:
            return None

        # Update fields
        update_data = user_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user_status(
        self, user_id: int, status: UserStatus
    ) -> Optional[User]:
        """Update user status."""
        user = await self.get_by_id(user_id)
        if not user:
            return None

        user.status = status
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user_role(self, user_id: int, role: UserRole) -> Optional[User]:
        """Update user role."""
        user = await self.get_by_id(user_id)
        if not user:
            return None

        user.role = role
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def deactivate_user(self, user_id: int) -> Optional[User]:
        """Deactivate user."""
        user = await self.get_by_id(user_id)
        if not user:
            return None

        user.is_active = False
        user.status = UserStatus.INACTIVE
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def activate_user(self, user_id: int) -> Optional[User]:
        """Activate user."""
        user = await self.get_by_id(user_id)
        if not user:
            return None

        user.is_active = True
        user.status = UserStatus.ACTIVE
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: int) -> bool:
        """Delete user (soft delete by deactivating)."""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.is_active = False
        user.status = UserStatus.INACTIVE
        await self.db.commit()
        return True

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Get user statistics."""
        user = await self.get_by_id(user_id)
        if not user:
            return {}

        from sqlalchemy import select, func
        from app.models.subscription import Subscription, SubscriptionStatus
        from app.models.billing import Invoice, InvoiceStatus, Payment

        # Get subscription counts
        subscription_result = await self.db.execute(
            select(func.count(Subscription.id)).where(Subscription.user_id == user_id)
        )
        subscription_count = subscription_result.scalar() or 0

        active_subscription_result = await self.db.execute(
            select(func.count(Subscription.id)).where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.status == SubscriptionStatus.ACTIVE
                )
            )
        )
        active_subscription_count = active_subscription_result.scalar() or 0

        # Get invoice counts
        total_invoices_result = await self.db.execute(
            select(func.count(Invoice.id)).where(Invoice.user_id == user_id)
        )
        total_invoices = total_invoices_result.scalar() or 0

        pending_invoices_result = await self.db.execute(
            select(func.count(Invoice.id)).where(
                and_(
                    Invoice.user_id == user_id,
                    Invoice.status == InvoiceStatus.PENDING
                )
            )
        )
        pending_invoices = pending_invoices_result.scalar() or 0

        # Get payment count
        total_payments_result = await self.db.execute(
            select(func.count(Payment.id)).where(Payment.user_id == user_id)
        )
        total_payments = total_payments_result.scalar() or 0

        return {
            "subscription_count": subscription_count,
            "active_subscription_count": active_subscription_count,
            "total_invoices": total_invoices,
            "pending_invoices": pending_invoices,
            "total_payments": total_payments,
            "last_login": user.last_login,
            "created_at": user.created_at,
        }
