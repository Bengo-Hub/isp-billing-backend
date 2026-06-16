"""Administration API routes."""

from fastapi import APIRouter
from .admin import router as admin_router
from .configuration import router as configuration_router

# NOTE: the /licence admin router was removed — ISP-provider licensing is owned
# by the central subscriptions-api now.
# NOTE (Phase C1): the /sms-credit admin router was removed — SMS credits are
# owned by notifications-api now.

router = APIRouter()
router.include_router(admin_router, prefix="/admin", tags=["System Administration"])
router.include_router(configuration_router, prefix="/configuration", tags=["Configuration"])
