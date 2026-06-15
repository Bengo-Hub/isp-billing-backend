"""
Payments API Module.

Public endpoints for payment processing:
- Payment verification (callback page)
- Webhook handlers
- Bank listings
"""

from fastapi import APIRouter

# NOTE: the local Paystack + public payment-gateway routers were removed —
# customer/tenant payments are centralized on treasury-api now. This router is
# kept (empty) so the api.v1 registration import remains stable.

router = APIRouter()
