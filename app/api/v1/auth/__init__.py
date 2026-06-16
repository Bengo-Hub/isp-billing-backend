"""Authentication API routes."""

from fastapi import APIRouter
from .auth import router as auth_router

# 2FA is handled centrally by the SSO IdP (auth-api) — the local two_factor
# router was removed as part of the SSO auth migration.

router = APIRouter()
router.include_router(auth_router)
