"""Authentication API routes."""

from fastapi import APIRouter
from .auth import router as auth_router
from .two_factor import router as two_factor_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(two_factor_router)
