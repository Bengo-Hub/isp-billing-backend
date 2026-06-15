"""Business Operations API routes."""

from fastapi import APIRouter, Depends
from app.api.deps import enforce_subscription_active
from .plans import router as plans_router
from .subscriptions import router as subscriptions_router
from .billing import router as billing_router
from .expenses import router as expenses_router
from .leads import router as leads_router
from .vouchers import router as vouchers_router

# Phase 1b: opt-in subscription gating on ISP-admin business endpoints.
# Mutating requests from a non-platform SSO user with an inactive subscription
# get 403 {code: "subscription_inactive"}. Reads + local-JWT + S2S unaffected.
# NOTE: this is the ISP-admin business surface only — the public captive
# portal (app/api/v1/portal/*) is deliberately NOT gated.
router = APIRouter(dependencies=[Depends(enforce_subscription_active)])
router.include_router(plans_router, prefix="/plans", tags=["Service Plans"])
router.include_router(subscriptions_router, prefix="/subscriptions", tags=["Subscriptions"])
router.include_router(billing_router, prefix="/billing", tags=["Billing & Payments"])
router.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
router.include_router(leads_router, prefix="/leads", tags=["Leads"])
router.include_router(vouchers_router, prefix="/vouchers", tags=["Vouchers"])
