"""Organization context dependencies for multi-tenancy."""

from typing import Optional
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.api.deps import get_current_user


async def get_org_from_header(
    x_organization_slug: Optional[str] = Header(None, alias="X-Organization-Slug"),
    db: AsyncSession = Depends(get_db),
) -> Optional[Organization]:
    """
    Extract organization from X-Organization-Slug header.
    Returns None if header is not provided (e.g., for platform routes).
    Raises 404 if organization slug is invalid.
    """
    if not x_organization_slug:
        return None

    result = await db.execute(
        select(Organization).where(Organization.slug == x_organization_slug)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{x_organization_slug}' not found",
        )

    return organization


async def get_required_org(
    organization: Optional[Organization] = Depends(get_org_from_header),
) -> Organization:
    """
    Require organization context.
    Raises 400 if X-Organization-Slug header is missing.
    """
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required. Please provide X-Organization-Slug header.",
        )

    return organization


async def validate_user_org_access(
    organization: Organization = Depends(get_required_org),
    current_user: User = Depends(get_current_user),
) -> Organization:
    """
    Validate that the current user belongs to the requested organization.
    Platform superusers can access any organization.
    """
    # Platform superusers can access any organization
    if current_user.role.value == "platform_owner":
        return organization

    # ISP admins, technicians, and customers must match organization
    if current_user.organization_id != organization.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to access this organization",
        )

    return organization


def get_org_id_for_query(
    current_user: User = Depends(get_current_user),
    organization: Optional[Organization] = Depends(get_org_from_header),
) -> int:
    """
    Get organization ID for database queries.
    - Platform superusers: Use org from header if provided, otherwise allow access to all
    - ISP users: Use their own organization_id (validated against header if provided)
    - Customers: Use their own organization_id (validated against header if provided)

    Returns the organization ID to use in queries.
    Raises 403 if user tries to access a different organization.
    """
    # Platform superusers can query any organization
    if current_user.role.value == "platform_owner":
        if organization:
            return organization.id
        # If no org specified, this should be handled by the endpoint
        # (e.g., list all organizations for platform admin)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required for this operation",
        )

    # For ISP users and customers, validate organization matches
    if organization and current_user.organization_id != organization.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Organization mismatch",
        )

    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not belong to any organization",
        )

    return current_user.organization_id
