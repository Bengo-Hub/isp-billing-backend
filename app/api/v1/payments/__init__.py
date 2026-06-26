"""
Payments API Module.

Public endpoints for payment processing:
- Payment verification (callback page)
- Webhook handlers
- Bank listings
"""

from fastapi import APIRouter

# NOTE: the local Paystack + direct payment-initiation routers were removed —
# customer/tenant payments are centralized on treasury-api now.
#
# The PUBLIC payment-gateway LISTING endpoint (GET /payment-gateways/available)
# is re-added below: it is the authoritative, ONLINE-ONLY methods list the
# captive buy page consumes. It sources gateway enable-state from treasury-api
# (Layer 1) and applies the centralized cash/COD exclusion + essential-config
# gate (Layer 2) — see app.modules.payments.gateway_filter.
from .gateways import router as gateways_router

router = APIRouter()
router.include_router(gateways_router)
