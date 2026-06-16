"""Tenant-specific API routes."""

from fastapi import APIRouter

from .settings import router as settings_router

# NOTE: tenant payment-gateways + platform-billing routers were removed —
# gateways are owned by treasury-api and ISP-provider billing by subscriptions-api.
# NOTE (Phase C1): the tenant /messages (SMS balance/topup/history) router was
# removed — SMS messaging + credits are owned by notifications-api now.

router = APIRouter(prefix="/tenant", tags=["Tenant"])

router.include_router(settings_router)
