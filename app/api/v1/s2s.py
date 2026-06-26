"""Service-to-service (S2S) endpoints.

Internal, trusted callers only — authenticated via the shared
``INTERNAL_SERVICE_KEY`` (header ``X-API-Key``), not a user JWT. These routes
exist for other Codevertex backends (e.g. subscriptions-api's billing engine)
to read aggregate, tenant-scoped facts from isp-billing.

Mounted under the global ``/api/v1`` prefix with router prefix ``/s2s``, so the
PPPoE active-count endpoint resolves to:

    GET /api/v1/s2s/tenants/{tenant_id}/pppoe/active-count
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.sso import verify_service_key
from app.models.organization import Organization
from app.models.subscription import (
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
)

# All routes here require a valid internal service key (X-API-Key). Unauthenticated
# callers get 401 from verify_service_key.
router = APIRouter(dependencies=[Depends(verify_service_key)])


class PPPoEActiveCountResponse(BaseModel):
    """Active PPPoE subscriber count for a tenant."""

    tenant_id: UUID
    active_pppoe_subscribers: int


@router.get(
    "/tenants/{tenant_id}/pppoe/active-count",
    response_model=PPPoEActiveCountResponse,
    tags=["S2S"],
    summary="Active PPPoE subscriber count for a tenant",
)
async def get_active_pppoe_count(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PPPoEActiveCountResponse:
    """Return the number of ACTIVE PPPoE subscriptions for ``tenant_id``.

    ``tenant_id`` is the central auth-api tenant UUID, mirrored locally as
    ``Organization.uuid`` (kept in sync with ``Organization.auth_tenant_id``).
    Subscriptions are tenant-scoped via ``Subscription.organization_id``, so we
    resolve the tenant UUID to the local organization id and count from there.

    Returns 0 (not 404) when the tenant is unknown locally or has no matching
    subscriptions.
    """
    # Resolve tenant UUID -> local organization id (standard tenant scoping).
    org_id = (
        await db.execute(
            select(Organization.id).where(
                or_(
                    Organization.uuid == tenant_id,
                    Organization.auth_tenant_id == str(tenant_id),
                )
            )
        )
    ).scalar_one_or_none()

    if org_id is None:
        return PPPoEActiveCountResponse(tenant_id=tenant_id, active_pppoe_subscribers=0)

    count = (
        await db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(
                Subscription.organization_id == org_id,
                Subscription.subscription_type == SubscriptionType.PPPOE,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
    ).scalar()

    return PPPoEActiveCountResponse(
        tenant_id=tenant_id,
        active_pppoe_subscribers=int(count or 0),
    )
