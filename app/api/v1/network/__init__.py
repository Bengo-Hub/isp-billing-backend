"""Network Management API routes."""

from fastapi import APIRouter
from .routers import router as routers_router
from .gateway_management import router as gateway_router

router = APIRouter()
router.include_router(routers_router, prefix="/routers", tags=["Routers"])
router.include_router(gateway_router, prefix="/gateways", tags=["Gateway Management"])
