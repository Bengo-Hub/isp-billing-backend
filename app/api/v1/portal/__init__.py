"""Customer Portal API routes."""

from fastapi import APIRouter

from .hotspot import router as hotspot_router
from .pppoe import router as pppoe_router

router = APIRouter(prefix="/portal", tags=["Portal"])

router.include_router(hotspot_router)
router.include_router(pppoe_router)
