"""
Payments API Module.

Public endpoints for payment processing:
- Payment verification (callback page)
- Webhook handlers
- Bank listings
"""

from fastapi import APIRouter

from .paystack import router as paystack_router

router = APIRouter()

# Paystack payment endpoints
router.include_router(paystack_router)
