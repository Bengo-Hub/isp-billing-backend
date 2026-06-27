"""
Public Payment Gateway Endpoints (captive package-purchase flow).

Re-implemented after the local ``PaymentGatewayConfig`` table was dropped
(gateways are now owned by treasury-api). This endpoint is the AUTHORITATIVE,
online-only payment-methods list the captive buy page consumes
(``useAvailablePaymentGateways`` → ``GET /payment-gateways/available``).

Two payment-gateway bugs are fixed here via the centralized filter in
``app.modules.payments.gateway_filter``:

  Issue 1 — Cash / Cash-on-Delivery / manual / offline rails are NEVER returned
            for an ISP package payment (there is no delivery; the customer must
            pay online to get internet). Mirrors subscriptions-api's online-only
            restriction.

  Issue 2 — A 2-layer ACTIVE gate. A gateway is returned ACTIVE only when it is
            BOTH (Layer 1) enabled (platform-owner and/or tenant enabled, as
            resolved by treasury) AND (Layer 2) has ALL its essential tenant
            configs present (e.g. M-Pesa needs short code/paybill + consumer
            key/secret + passkey). A gateway flagged active but missing essential
            config is filtered out — selecting it would otherwise fail.

The response field contract is unchanged (the frontend reads ``gateway_type`` /
``is_active`` / ``is_primary`` / ``name`` / ``display_name`` / ...).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.models.organization import Organization
from app.modules.payments import (
    filter_captive_payment_gateways,
    normalize_gateway_type,
)
from app.services.treasury_client import TreasuryClient
from app.utils.tenant import get_org_slug_from_request

logger = get_logger(__name__)

router = APIRouter(prefix="/payment-gateways", tags=["Public - Payment Gateways"])


# =========================================================================
# Schemas (response contract kept stable for the captive buy page)
# =========================================================================

class AvailableGatewayResponse(BaseModel):
    """Schema for an available payment gateway (online-only, config-complete)."""

    id: int
    gateway_type: str
    name: str
    display_name: str
    is_active: bool
    is_primary: bool
    environment: str = "production"
    # M-PESA specific (optional; present when treasury exposes them)
    paybill_number: Optional[str] = None
    till_number: Optional[str] = None


# =========================================================================
# Helpers
# =========================================================================

def _build_tenant_configs(*, platform_rail: bool = False) -> Dict[str, Dict[str, Any]]:
    """Build the Layer-2 tenant-config bag keyed by normalised gateway type.

    Customer payments route through the PLATFORM M-Pesa rail, whose essential
    credentials are owned by isp-billing (``settings.mpesa_*``). We surface them
    here so the essential-config gate hides M-Pesa when any required field
    (short code / consumer key / consumer secret / passkey) is unset — which is
    exactly the "M-Pesa shows active but isn't configured" bug.

    Paystack / card run on platform-managed keys held BY TREASURY (isp-billing
    never sees them). For those rails treasury is the credential authority, so the
    local essential-config gate cannot validate them. When ``platform_rail`` is
    True (i.e. we are listing the PLATFORM tenant's treasury-enabled gateways), we
    supply a sentinel "treasury-managed" config bag for paystack/card so the
    Layer-2 gate trusts treasury's Layer-1 enable state instead of hiding them for
    a key isp-billing structurally cannot hold. The cash/COD exclusion and the
    M-Pesa local-config gate still apply.
    """
    mpesa_cfg: Dict[str, Any] = {
        "shortcode": settings.mpesa_shortcode,
        "consumer_key": settings.mpesa_consumer_key,
        "consumer_secret": settings.mpesa_consumer_secret,
        "passkey": settings.mpesa_passkey,
    }
    configs: Dict[str, Dict[str, Any]] = {
        "mpesa": mpesa_cfg,
        "mpesa_paybill": mpesa_cfg,
        "mpesa_till": mpesa_cfg,
    }
    if platform_rail:
        # Treasury holds these keys; satisfy the local gate so treasury's enable
        # state (Layer 1) is authoritative for the platform rail.
        treasury_managed = {"secret_key": "managed-by-treasury"}
        configs["paystack"] = treasury_managed
        configs["card"] = treasury_managed
    return configs


def _display_name(gateway_type: str, name: Optional[str]) -> str:
    """Human-facing label, falling back to a sensible default per type."""
    if name:
        return name
    gt = normalize_gateway_type(gateway_type)
    return {
        "mpesa": "M-Pesa",
        "mpesa_paybill": "M-Pesa",
        "mpesa_till": "M-Pesa",
        "paystack": "Card / Mobile Money",
        "card": "Card",
    }.get(gt, gateway_type or "Payment")


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/available", response_model=List[AvailableGatewayResponse])
async def get_available_payment_gateways(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return online-only, essential-config-complete gateways for the org.

    Public endpoint (the captive page is unauthenticated). Resolves the org from
    the ``X-Organization-Slug`` header (falling back to the first active org),
    pulls the tenant's treasury-enabled gateways (Layer 1), then applies the
    centralized captive filter (cash/COD exclusion + Layer-2 essential-config
    gate). Returns ``[]`` on any resolution/treasury failure rather than erroring
    — the buy page degrades gracefully.
    """
    try:
        org_slug = await get_org_slug_from_request(request, db)
    except Exception as exc:  # no org context → no methods
        logger.warning("payment-gateways/available: no org context: %s", exc)
        return []

    result = await db.execute(
        select(Organization).where(Organization.slug == org_slug)
    )
    organization = result.scalar_one_or_none()
    if not organization or not getattr(organization, "uuid", None):
        return []

    # Layer 1 — HYBRID sourcing. Treasury is the source of truth for enabled
    # gateways. First try the ISP tenant's OWN selected gateways (tenant override);
    # if it has none, fall back to the PLATFORM operating tenant's gateways, because
    # captive customers pay the platform rail ("Codevertex Africa Limited"). Empty
    # list on any treasury problem (never raises).
    client = TreasuryClient()
    raw_gateways = await client.list_active_gateways(tenant=str(organization.uuid))

    using_platform_rail = False
    if not raw_gateways:
        platform_tenant = (settings.platform_treasury_tenant or "").strip()
        if platform_tenant:
            logger.info(
                "payment-gateways/available: ISP tenant %s has no treasury gateways; "
                "falling back to platform tenant %s",
                organization.uuid,
                platform_tenant,
            )
            raw_gateways = await client.list_active_gateways(tenant=platform_tenant)
            using_platform_rail = bool(raw_gateways)

    # Apply Issue-1 (cash/COD exclusion) + Layer-2 (essential-config gate). This
    # is the SAME helper every gateway-listing path should use. For the platform
    # rail, treasury holds the paystack/card credentials, so trust its enable state.
    tenant_configs = _build_tenant_configs(platform_rail=using_platform_rail)
    filtered = filter_captive_payment_gateways(
        raw_gateways, tenant_configs=tenant_configs
    )

    # Map to the stable frontend contract. ``id`` is best-effort (treasury ids
    # are UUIDs; the frontend only uses it as a React key) — emit a stable int.
    available: List[AvailableGatewayResponse] = []
    for idx, gw in enumerate(filtered):
        gw_type = str(gw.get("gateway_type") or gw.get("type") or "")
        name = gw.get("name")
        available.append(
            AvailableGatewayResponse(
                id=idx + 1,
                gateway_type=gw_type,
                name=name or _display_name(gw_type, name),
                display_name=_display_name(gw_type, name),
                is_active=bool(gw.get("is_active", True)),
                is_primary=bool(gw.get("is_primary", False)),
                environment=str(gw.get("environment") or "production"),
                paybill_number=gw.get("paybill_number") or gw.get("paybill"),
                till_number=gw.get("till_number") or gw.get("till"),
            )
        )

    return available
