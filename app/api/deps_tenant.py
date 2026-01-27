"""
Tenant-aware dependencies for FastAPI endpoints.

Provides dependencies for:
- Getting current organization from context
- Requiring platform owner access
- Requiring ISP admin access
- Requiring ISP staff access (admin or technician)
- Tenant-scoped database queries
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.tenant_middleware import get_current_organization_id, get_current_tenant
from app.models.organization import Organization, OrganizationStatus
from app.models.user import User, UserRole


class TenantNotFoundError(HTTPException):
    """Exception raised when tenant is not found."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )


class TenantAccessDeniedError(HTTPException):
    """Exception raised when access to tenant is denied."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this organization is denied"
        )


class TenantSuspendedError(HTTPException):
    """Exception raised when tenant is suspended."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization is suspended. Please contact support."
        )


class PlatformOwnerRequiredError(HTTPException):
    """Exception raised when platform owner access is required."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform owner access required"
        )


class ISPAdminRequiredError(HTTPException):
    """Exception raised when ISP admin access is required."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ISP administrator access required"
        )


class ISPStaffRequiredError(HTTPException):
    """Exception raised when ISP staff access is required."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ISP staff access required"
        )


async def get_current_organization(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    """
    Get the current organization for the authenticated user.

    For platform owners, this will raise an error as they don't belong to an org.
    Use get_optional_organization for endpoints that support both platform owners and ISP users.
    """
    if current_user.role == UserRole.PLATFORM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Platform owners must specify an organization"
        )

    if not current_user.organization_id:
        raise TenantNotFoundError()

    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise TenantNotFoundError()

    if organization.status == OrganizationStatus.SUSPENDED:
        raise TenantSuspendedError()

    return organization


async def get_optional_organization(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Optional[Organization]:
    """
    Get the current organization if available.

    Returns None for platform owners.
    """
    if current_user.role == UserRole.PLATFORM_OWNER:
        return None

    if not current_user.organization_id:
        return None

    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    return result.scalar_one_or_none()


async def get_organization_from_context(
    db: AsyncSession = Depends(get_db),
) -> Optional[Organization]:
    """
    Get organization from tenant context (set by middleware).

    Use this for unauthenticated portal endpoints.
    """
    organization_id = get_current_organization_id()
    if not organization_id:
        return None

    # Check if full tenant is already loaded
    tenant = get_current_tenant()
    if tenant:
        return tenant

    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    return result.scalar_one_or_none()


async def require_organization_from_context(
    organization: Optional[Organization] = Depends(get_organization_from_context),
) -> Organization:
    """
    Require organization from context, raise 404 if not found.

    Use this for portal endpoints that must have an organization.
    """
    if not organization:
        raise TenantNotFoundError()

    if organization.status == OrganizationStatus.SUSPENDED:
        raise TenantSuspendedError()

    return organization


async def require_platform_owner(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require platform owner access.

    Raises 403 if user is not a platform owner.
    """
    if current_user.role != UserRole.PLATFORM_OWNER:
        raise PlatformOwnerRequiredError()

    return current_user


async def require_platform_integration_access(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require platform owner access for integration secrets/URLs.
    
    Only platform owners (ISP Software Provider staff) can access:
    - API keys and secrets
    - Webhook/callback URLs
    - Platform-level gateway configurations
    
    Raises 403 if user is not a platform owner.
    """
    if current_user.role != UserRole.PLATFORM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform integration access required. Only ISP Software Provider staff can access integration secrets and URLs."
        )
    return current_user


async def require_isp_admin(
    current_user: User = Depends(get_current_user),
    organization: Organization = Depends(get_current_organization),
) -> User:
    """
    Require ISP administrator access.

    Raises 403 if user is not an ISP admin.
    """
    if current_user.role not in [UserRole.ISP_ADMIN, UserRole.PLATFORM_OWNER]:
        raise ISPAdminRequiredError()

    return current_user


async def require_tenant_integration_access(
    current_user: User = Depends(get_current_user),
    organization: Organization = Depends(get_current_organization),
) -> User:
    """
    Require ISP Admin access for tenant-specific integration configuration.
    
    ISP Admins can configure:
    - Which payment gateway to use (from activated options)
    - Their payout account details
    - SMS provider selection and top-up
    - Notification preferences
    
    ISP Admins CANNOT access:
    - API keys and secrets (platform owner only)
    - Webhook/callback URLs (platform owner only)
    - Enable/disable gateways (platform owner only)
    
    Raises 403 if user is not an ISP admin or platform owner.
    """
    if current_user.role not in [UserRole.ISP_ADMIN, UserRole.PLATFORM_OWNER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ISP administrator access required for integration configuration"
        )
    return current_user


async def require_isp_staff(
    current_user: User = Depends(get_current_user),
    organization: Organization = Depends(get_current_organization),
) -> User:
    """
    Require ISP staff access (admin or technician).

    Raises 403 if user is not ISP staff.
    """
    if current_user.role not in [UserRole.ISP_ADMIN, UserRole.ISP_TECHNICIAN, UserRole.PLATFORM_OWNER]:
        raise ISPStaffRequiredError()

    return current_user


async def require_active_subscription(
    organization: Organization = Depends(get_current_organization),
) -> Organization:
    """
    Require an active subscription.

    Raises 403 if subscription is expired.
    """
    if not organization.is_subscription_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Subscription expired. Please renew your subscription."
        )

    return organization


async def get_organization_by_id(
    organization_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
) -> Organization:
    """
    Get an organization by ID (platform owner only).

    Used for platform admin endpoints to manage organizations.
    """
    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise TenantNotFoundError()

    return organization


async def get_organization_by_slug(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Get an organization by slug.

    Used for portal endpoints that receive org slug in path.
    """
    result = await db.execute(
        select(Organization).where(Organization.slug == org_slug)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise TenantNotFoundError()

    if organization.status == OrganizationStatus.SUSPENDED:
        raise TenantSuspendedError()

    return organization


class TenantQueryMixin:
    """
    Mixin for tenant-scoped database queries.

    Usage:
        class UserService(TenantQueryMixin):
            async def get_all(self, db: AsyncSession) -> list[User]:
                return await self.tenant_query(
                    db,
                    select(User).where(User.is_active == True)
                )
    """

    async def tenant_query(
        self,
        db: AsyncSession,
        query,
        organization_id: Optional[int] = None,
    ):
        """
        Add tenant filter to query.

        Args:
            db: Database session
            query: SQLAlchemy select query
            organization_id: Optional org ID, uses context if not provided
        """
        org_id = organization_id or get_current_organization_id()

        if org_id is None:
            raise TenantNotFoundError()

        # Add organization_id filter
        query = query.where(query.column_descriptions[0]["entity"].organization_id == org_id)

        result = await db.execute(query)
        return result.scalars().all()


def tenant_scope(organization_id: Optional[int] = None):
    """
    Decorator to add tenant scope to a query.

    Usage:
        @tenant_scope()
        async def get_users(db: AsyncSession) -> list[User]:
            return await db.execute(select(User))
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            org_id = organization_id or get_current_organization_id()
            if org_id is None:
                raise TenantNotFoundError()
            kwargs["organization_id"] = org_id
            return await func(*args, **kwargs)
        return wrapper
    return decorator
