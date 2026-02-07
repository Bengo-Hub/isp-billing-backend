"""Business Operations API routes."""

from fastapi import APIRouter
from .plans import router as plans_router
from .subscriptions import router as subscriptions_router
from .billing import router as billing_router
from .expenses import router as expenses_router
from .leads import router as leads_router
from .vouchers import router as vouchers_router

router = APIRouter()
router.include_router(plans_router, prefix="/plans", tags=["Service Plans"])
router.include_router(subscriptions_router, prefix="/subscriptions", tags=["Subscriptions"])
router.include_router(billing_router, prefix="/billing", tags=["Billing & Payments"])
router.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
router.include_router(leads_router, prefix="/leads", tags=["Leads"])
router.include_router(vouchers_router, prefix="/vouchers", tags=["Vouchers"])
