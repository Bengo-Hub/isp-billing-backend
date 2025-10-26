"""API v1 package."""

from fastapi import APIRouter

from .auth import router as auth_router
from .users import router as users_router
from .routers import router as routers_router
from .plans import router as plans_router
from .subscriptions import router as subscriptions_router
from .billing import router as billing_router
from .notifications import router as notifications_router
from .reports import router as reports_router
from .provisioning import router as provisioning_router
from .licence import router as licence_router
from .sms_credit import router as sms_credit_router
from .ui import router as ui_router
from .gateway_management import router as gateway_router
from .admin import router as admin_router
from .rbac import router as rbac_router

api_router = APIRouter()

# Include all routers
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users_router, prefix="/users", tags=["Users"])
api_router.include_router(routers_router, prefix="/routers", tags=["Routers"])
api_router.include_router(plans_router, prefix="/plans", tags=["Service Plans"])
api_router.include_router(subscriptions_router, prefix="/subscriptions", tags=["Subscriptions"])
api_router.include_router(billing_router, prefix="/billing", tags=["Billing & Payments"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["Notifications & Support"])
api_router.include_router(reports_router, prefix="/reports", tags=["Reports & Analytics"])
api_router.include_router(provisioning_router, prefix="/provisioning", tags=["Device Provisioning"])
api_router.include_router(licence_router, prefix="/licence", tags=["Licence Management"])
api_router.include_router(ui_router, prefix="/ui", tags=["User Interface"])
api_router.include_router(gateway_router, prefix="/gateways", tags=["Gateway Management"])
api_router.include_router(admin_router, prefix="/admin", tags=["System Administration"])
api_router.include_router(sms_credit_router, prefix="/sms-credit", tags=["SMS Credit"])
api_router.include_router(rbac_router, prefix="/rbac", tags=["RBAC Management"])
