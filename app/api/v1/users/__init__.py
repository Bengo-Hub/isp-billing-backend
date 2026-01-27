"""User Management API routes."""

from fastapi import APIRouter
from .users import router as users_router
from .rbac import router as rbac_router

router = APIRouter()
router.include_router(users_router, prefix="/users", tags=["Users"])
router.include_router(rbac_router, prefix="/rbac", tags=["RBAC Management"])
