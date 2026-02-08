"""Tenant-specific API routes."""

from fastapi import APIRouter

from .payment_gateways import router as payment_gateways_router
from .settings import router as settings_router
from .messages import router as messages_router
from .billing import router as billing_router

router = APIRouter(prefix="/tenant", tags=["Tenant"])

router.include_router(payment_gateways_router)
router.include_router(settings_router)
router.include_router(messages_router)
router.include_router(billing_router)
