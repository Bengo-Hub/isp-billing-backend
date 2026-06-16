"""Platform Owner API routes."""

from fastapi import APIRouter

from .organizations import router as organizations_router
from .analytics import router as analytics_router
from .settings import router as settings_router
from .users import router as platform_users_router

# NOTE: platform billing / subscription-tiers / payment-gateway admin routers were
# removed — those subsystems are now owned by treasury/subscriptions-api.
# NOTE (Phase C1): the /sms-gateways and /whatsapp platform routers were removed —
# SMS gateways + WhatsApp gateways/subscriptions are owned by notifications-api now.

router = APIRouter(prefix="/platform", tags=["Platform"])

router.include_router(organizations_router)
router.include_router(analytics_router)
router.include_router(settings_router)
router.include_router(platform_users_router, prefix="/users", tags=["Platform Users"])
