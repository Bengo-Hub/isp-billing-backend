"""Communications API routes."""

from fastapi import APIRouter
from .campaigns import router as campaigns_router
from .emails import router as emails_router

router = APIRouter()
router.include_router(campaigns_router, prefix="/campaigns", tags=["Campaigns"])
router.include_router(emails_router, prefix="/emails", tags=["Emails"])
