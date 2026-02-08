"""
Licence enforcement middleware.

Checks organization subscription/trial status on every ISP tenant request.
Blocks suspended organizations with 403, warns grace-period organizations.
"""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.tenant_middleware import get_current_organization_id

logger = logging.getLogger(__name__)


class LicenceEnforcementMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce licence/subscription status for ISP tenants.

    - ACTIVE or TRIAL (valid) → allow request
    - PENDING_PAYMENT (grace period) → allow but add warning header
    - SUSPENDED → block with 403 JSON response
    - licence_bypass=True → skip all checks
    """

    # Paths exempt from licence enforcement
    EXEMPT_PATHS = [
        "/api/v1/auth/",
        "/api/v1/platform/",
        "/api/v1/onboarding",
        "/api/v1/tenant/billing",
        "/api/v1/tenant/licence-status",
        "/api/v1/portal/",
        "/api/v1/provisioning/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    def __init__(self, app, db_session_factory=None):
        super().__init__(app)
        self.db_session_factory = db_session_factory

    async def dispatch(self, request: Request, call_next) -> Response:
        """Check licence status before processing request."""
        # Skip for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # Skip for exempt paths
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return await call_next(request)

        # Get current organization from tenant middleware (already resolved)
        organization_id = get_current_organization_id()

        # No org context = platform owner or unauthenticated → skip
        if not organization_id:
            return await call_next(request)

        # Check organization status
        org_status = await self._get_org_status(organization_id)

        if not org_status:
            return await call_next(request)

        status = org_status.get("status")
        bypass = org_status.get("licence_bypass", False)

        # Bypass flag set by platform admin → skip enforcement
        if bypass:
            response = await call_next(request)
            response.headers["X-Licence-Bypass"] = "true"
            return response

        if status == "suspended":
            logger.warning(f"Blocked request from suspended org {organization_id}: {path}")
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Account suspended - your licence has expired. Please renew your subscription to restore access.",
                    "code": "LICENCE_SUSPENDED",
                    "billing_url": "/billing/subscription",
                },
            )

        if status == "pending_payment":
            response = await call_next(request)
            response.headers["X-Licence-Warning"] = "grace_period"
            days_left = org_status.get("grace_days_left", 0)
            response.headers["X-Grace-Days-Left"] = str(days_left)
            return response

        # Check if trial or subscription has actually expired (status still shows active/trial)
        is_expired = org_status.get("is_expired", False)
        if is_expired:
            # The Celery task hasn't caught up yet - still allow but warn
            response = await call_next(request)
            response.headers["X-Licence-Warning"] = "expired_pending_update"
            return response

        return await call_next(request)

    async def _get_org_status(self, organization_id: int) -> Optional[dict]:
        """Fetch organization licence status from DB."""
        if not self.db_session_factory:
            return None

        try:
            from datetime import datetime
            from sqlalchemy import select
            from app.models.organization import Organization

            async with self.db_session_factory() as session:
                result = await session.execute(
                    select(Organization).where(Organization.id == organization_id)
                )
                org = result.scalar_one_or_none()
                if not org:
                    return None

                # Calculate grace days left
                grace_days_left = 0
                if org.grace_period_ends_at:
                    delta = org.grace_period_ends_at - datetime.utcnow()
                    grace_days_left = max(0, delta.days)

                # Check if subscription/trial has expired
                is_expired = False
                if org.status.value in ("active", "trial"):
                    if org.is_trial and org.trial_ends_at and datetime.utcnow() >= org.trial_ends_at:
                        is_expired = True
                    elif not org.is_trial and org.subscription_ends_at and datetime.utcnow() >= org.subscription_ends_at:
                        is_expired = True

                return {
                    "status": org.status.value,
                    "licence_bypass": org.licence_bypass,
                    "grace_days_left": grace_days_left,
                    "is_expired": is_expired,
                }
        except Exception as e:
            logger.error(f"Error checking org status for {organization_id}: {e}")
            return None
