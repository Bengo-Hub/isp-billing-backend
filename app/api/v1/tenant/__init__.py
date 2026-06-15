"""Tenant-specific API routes."""

from fastapi import APIRouter

from .settings import router as settings_router
from .messages import router as messages_router

# NOTE: tenant payment-gateways + platform-billing routers were removed —
# gateways are owned by treasury-api and ISP-provider billing by subscriptions-api.

router = APIRouter(prefix="/tenant", tags=["Tenant"])

router.include_router(settings_router)
router.include_router(messages_router)
