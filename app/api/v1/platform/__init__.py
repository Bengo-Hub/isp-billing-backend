"""Platform Owner API routes."""

from fastapi import APIRouter

from .organizations import router as organizations_router
from .billing import router as billing_router
from .analytics import router as analytics_router
from .tiers import router as tiers_router

router = APIRouter(prefix="/platform", tags=["Platform"])

router.include_router(organizations_router)
router.include_router(billing_router)
router.include_router(analytics_router)
router.include_router(tiers_router)
