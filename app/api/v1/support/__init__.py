"""Support & Analytics API routes."""

from fastapi import APIRouter
from .notifications import router as notifications_router
from .reports import router as reports_router
from .ui import router as ui_router
from .logs import router as logs_router
from .tickets import router as tickets_router

router = APIRouter()
router.include_router(notifications_router, prefix="/notifications", tags=["Notifications & Support"])
router.include_router(reports_router, prefix="/reports", tags=["Reports & Analytics"])
router.include_router(ui_router, prefix="/ui", tags=["User Interface"])
router.include_router(logs_router, prefix="/logs", tags=["System Logs"])
router.include_router(tickets_router, prefix="/tickets", tags=["Support Tickets"])
