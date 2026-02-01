"""
Payments API Module.

Public endpoints for payment processing:
- Payment verification (callback page)
- Webhook handlers
- Bank listings
"""

from fastapi import APIRouter

from .paystack import router as paystack_router
from .gateways import router as gateways_router

router = APIRouter()

# Paystack payment endpoints
router.include_router(paystack_router)

# Public payment gateway endpoints
router.include_router(gateways_router)
