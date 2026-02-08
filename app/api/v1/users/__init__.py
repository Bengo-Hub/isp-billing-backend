"""User Management API routes."""

from fastapi import APIRouter
from .users import router as users_router
from .rbac import router as rbac_router
from .staff import router as staff_router
from .customers import router as customers_router

router = APIRouter()
router.include_router(staff_router, prefix="/users/staff", tags=["ISP Staff Users"])
router.include_router(customers_router, prefix="/users/customers", tags=["ISP Customer Users"])
router.include_router(users_router, prefix="/users", tags=["Users"])
router.include_router(rbac_router, prefix="/rbac", tags=["RBAC Management"])
