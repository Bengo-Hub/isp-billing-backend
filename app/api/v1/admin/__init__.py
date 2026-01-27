"""Administration API routes."""

from fastapi import APIRouter
from .admin import router as admin_router
from .licence import router as licence_router
from .sms_credit import router as sms_credit_router
from .configuration import router as configuration_router

router = APIRouter()
router.include_router(admin_router, prefix="/admin", tags=["System Administration"])
router.include_router(licence_router, prefix="/licence", tags=["Licence Management"])
router.include_router(sms_credit_router, prefix="/sms-credit", tags=["SMS Credit"])
router.include_router(configuration_router, prefix="/config", tags=["Configuration"])
