"""Customer Portal API routes."""

from fastapi import APIRouter, Depends

from app.api.deps_tenant import get_organization_by_slug
from app.models.organization import Organization

from .hotspot import router as hotspot_router
from .pppoe import router as pppoe_router

router = APIRouter(prefix="/portal", tags=["Portal"])

router.include_router(hotspot_router)
router.include_router(pppoe_router)


# General portal endpoints (not specific to hotspot or pppoe)
@router.get("/{org_slug}/terms")
async def get_terms_and_conditions(
    org_slug: str,
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get organization's terms of service and privacy policy.

    Public endpoint - no authentication required.
    """
    return {
        "terms_of_service": organization.terms_of_service or "Terms of service not configured.",
        "privacy_policy": organization.privacy_policy or "Privacy policy not configured.",
    }
