"""
Multi-tenancy utility for retrieving organization slug with fallback layers.

This module provides a centralized way to retrieve organization slug from various sources
with a fallback mechanism to ensure all endpoints can operate with organization context.
"""

import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization

logger = logging.getLogger(__name__)


async def get_org_slug_from_request(
    request: Request,
    db: AsyncSession,
    org_slug_param: Optional[str] = None,
) -> str:
    """
    Get organization slug with multi-layer fallback mechanism.

    Fallback layers:
    1. From request headers (X-Organization-Slug)
    2. From function parameter (passed from path/query params)
    3. From first organization in database (default fallback)

    Args:
        request: FastAPI request object
        db: Database session
        org_slug_param: Optional org slug from path/query parameters

    Returns:
        Organization slug string

    Raises:
        HTTPException: If no organization found in any fallback layer
    """

    # Layer 1: Check request headers
    org_slug = request.headers.get("X-Organization-Slug")
    if org_slug:
        logger.debug(f"Organization slug retrieved from headers: {org_slug}")

        # Validate that organization exists
        result = await db.execute(
            select(Organization).where(Organization.slug == org_slug)
        )
        org = result.scalar_one_or_none()

        if org:
            return org_slug
        else:
            logger.warning(f"Organization slug from headers '{org_slug}' not found in database")

    # Layer 2: Check function parameter (from path/query params)
    if org_slug_param:
        logger.debug(f"Organization slug retrieved from parameters: {org_slug_param}")

        # Validate that organization exists
        result = await db.execute(
            select(Organization).where(Organization.slug == org_slug_param)
        )
        org = result.scalar_one_or_none()

        if org:
            return org_slug_param
        else:
            logger.warning(f"Organization slug from parameters '{org_slug_param}' not found in database")

    # Layer 3: Fallback to first organization in database
    logger.debug("No org slug in headers or params, falling back to first organization in database")

    result = await db.execute(
        select(Organization)
        .where(Organization.status == "ACTIVE")
        .order_by(Organization.created_at.asc())
        .limit(1)
    )
    first_org = result.scalar_one_or_none()

    if first_org:
        logger.info(f"Using fallback organization: {first_org.slug} (ID: {first_org.id})")
        return first_org.slug

    # No organization found in any layer
    logger.error("No organization found in headers, params, or database")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No organization context available. Please specify organization."
    )


async def get_organization_by_slug_with_fallback(
    request: Request,
    db: AsyncSession,
    org_slug_param: Optional[str] = None,
) -> Organization:
    """
    Get organization object with multi-layer fallback mechanism.

    Uses get_org_slug_from_request to determine slug, then retrieves full organization.

    Args:
        request: FastAPI request object
        db: Database session
        org_slug_param: Optional org slug from path/query parameters

    Returns:
        Organization object

    Raises:
        HTTPException: If no organization found
    """

    org_slug = await get_org_slug_from_request(request, db, org_slug_param)

    result = await db.execute(
        select(Organization).where(Organization.slug == org_slug)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{org_slug}' not found"
        )

    return organization


async def get_org_id_from_request(
    request: Request,
    db: AsyncSession,
    org_slug_param: Optional[str] = None,
) -> int:
    """
    Get organization ID with multi-layer fallback mechanism.

    Convenience method that returns organization ID instead of slug.

    Args:
        request: FastAPI request object
        db: Database session
        org_slug_param: Optional org slug from path/query parameters

    Returns:
        Organization ID (integer)

    Raises:
        HTTPException: If no organization found
    """

    organization = await get_organization_by_slug_with_fallback(request, db, org_slug_param)
    return organization.id
