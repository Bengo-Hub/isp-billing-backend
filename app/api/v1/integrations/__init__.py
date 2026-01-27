"""External Integrations API routes."""

from fastapi import APIRouter
from .mpesa import router as mpesa_router
from .urls import router as urls_router

router = APIRouter()
router.include_router(mpesa_router, prefix="/mpesa", tags=["M-PESA Integration"])
router.include_router(urls_router)
