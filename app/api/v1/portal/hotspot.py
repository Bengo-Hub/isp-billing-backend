"""
Hotspot Customer Portal API.

Public endpoints for hotspot customers to:
- View available packages
- Purchase packages via M-PESA
- Redeem voucher codes
- Check session status
- Login and reconnect (returning users)
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.api.deps_tenant import get_organization_by_slug
from app.models.organization import Organization, OrganizationSettings
from app.models.plan import ServicePlan, PlanType, PlanStatus
from app.models.customer_portal import VoucherCode, CustomerSession, CustomerPurchase, VoucherStatus, SessionStatus
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionType
from app.models.router import Router
from app.integrations.mikrotik import get_mikrotik_client

# DEPRECATED (customer payments centralized on treasury-api):
#   The CUSTOMER hotspot purchase path no longer uses isp-billing's own payment
#   gateways. ``PaymentGatewayConfig`` / ``GatewayType`` / ``PaymentGatewayFactory``
#   are intentionally NO LONGER imported here — treasury-api is the single source
#   of truth for initiating + confirming customer payments (NATS consumer primary,
#   treasury get_status polling fallback). The model + integrations remain
#   importable for legacy/admin (SMS-credit / WhatsApp top-up / PPPoE renewal)
#   paths, which are out of scope for this cutover.
from app.utils.hotspot_username import generate_hotspot_credentials

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hotspot", tags=["Portal - Hotspot"])


# =========================================================================
# Schemas
# =========================================================================

class PackageResponse(BaseModel):
    """Schema for package/plan response."""

    id: int
    name: str
    description: Optional[str]
    price: float
    currency: str
    validity_days: int
    download_speed: int  # Mbps
    upload_speed: int  # Mbps
    data_limit: int  # GB, -1 for unlimited
    time_limit: int  # hours, -1 for unlimited
    is_unlimited_data: bool
    is_unlimited_time: bool
    is_popular: bool
    features: List[str]
    plan_type: str  # HOTSPOT / PPPOE / INTERNET / BOTH
    concurrent_sessions: int  # number of simultaneous devices allowed
    # Authoritative access window in MINUTES when set (> 0). Carries sub-day /
    # sub-hour precision (e.g. 5 = 5 min). Null when the plan relies on the
    # legacy validity_days (capped by time_limit) fallback instead.
    duration_minutes: Optional[int] = None
    # Effective access window in HOURS the customer ACTUALLY gets, computed by the
    # single source of truth ``ServicePlan.access_window_hours()`` (honours
    # duration_minutes → validity_days capped by time_limit). <= 0 means no finite
    # calendar window (e.g. unlimited time). The captive card renders THIS so the
    # displayed validity always matches what is provisioned.
    access_window_hours: float = 0.0


class PurchaseRequest(BaseModel):
    """Schema for purchase request."""

    plan_id: int
    phone_number: str = Field(default="", description="Phone number for M-PESA payments")
    email: Optional[str] = Field(None, description="Email for card/Paystack payments")
    payment_method: Optional[str] = Field("mpesa", description="Payment method: mpesa or paystack")


class PurchaseResponse(BaseModel):
    """Schema for purchase response."""

    success: bool
    reference: str
    message: str
    instructions: Optional[str] = None
    checkout_url: Optional[str] = None
    status: str
    # Fields for the embedded TreasuryPaymentModal (in-app iframe checkout) — the
    # captive buy page opens the modal instead of redirecting to checkout_url.
    intent_id: Optional[str] = None
    initiate_url: Optional[str] = None
    tenant_id: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    reference_type: Optional[str] = None


class VoucherRedeemRequest(BaseModel):
    """Schema for voucher redemption."""

    code: str = Field(..., min_length=4, max_length=50)
    mac_address: Optional[str] = None


class VoucherRedeemResponse(BaseModel):
    """Schema for voucher redemption response."""

    success: bool
    message: str
    plan_name: Optional[str] = None
    # FLOAT hours: access_window_hours() returns fractional hours for sub-hour
    # packages (e.g. a 30-minute voucher → 0.5). An int field rejected those with
    # a Pydantic ValidationError and 500'd the redeem.
    validity_hours: Optional[float] = None
    expires_at: Optional[datetime] = None
    # Hotspot login credentials so the captive portal can show / auto-fill them.
    hotspot_username: Optional[str] = None
    hotspot_password: Optional[str] = None
    # MikroTik hotspot gateway login URL so the captive page can authenticate the
    # client directly (even when opened manually, with no captive redirect param).
    login_url: Optional[str] = None


class SessionStatusResponse(BaseModel):
    """Schema for session status."""

    is_active: bool
    plan_name: Optional[str] = None
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    time_remaining_seconds: Optional[int] = None
    data_used_mb: Optional[float] = None
    data_limit_mb: Optional[float] = None


class PortalConfigResponse(BaseModel):
    """Schema for portal configuration."""

    organization_name: str
    logo_url: Optional[str]
    primary_color: str
    portal_title: Optional[str]
    portal_description: Optional[str]
    show_packages: bool
    allow_guest_purchases: bool
    redirect_url: str = "https://www.google.com"
    # Provider (ISP tenant) subscription gate: when False, the customer-facing buy
    # flow shows a neutral "contact your provider" card instead of packages. The
    # contact card is always included so the UI can render it on a purchase 403.
    provider_active: bool = True
    provider_contact: Optional[dict] = None


class HotspotLoginRequest(BaseModel):
    """Schema for hotspot login (returning users)."""

    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=255)
    mac_address: Optional[str] = Field(None, description="Client MAC from captive redirect")


class HotspotLoginResponse(BaseModel):
    """Schema for hotspot login response."""

    success: bool
    message: str
    session_token: Optional[str] = None
    login_url: Optional[str] = None
    plan_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_active: bool = False


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/{org_slug}/config", response_model=PortalConfigResponse)
async def get_portal_config(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get portal configuration for an organization.

    Public endpoint - no authentication required.
    """
    # Get organization settings
    settings_result = await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == organization.id,
        )
    )
    settings = settings_result.scalar_one_or_none()

    redirect_url = settings.hotspot_redirect_url if settings else "https://www.google.com"
    show_packages = settings.show_packages_on_portal if settings else True
    allow_guest = settings.allow_guest_purchases if settings else True

    # Provider subscription gate (fail-open): tells the customer UI whether to
    # show packages or a neutral "contact your provider" card.
    from app.services.provider_gate import resolve_provider_access
    provider_active, provider_contact = await resolve_provider_access(organization)

    # Branding is owned by auth-api (the SoT). isp-billing stores NO local
    # branding: we fetch it SERVER-SIDE from auth-api's public tenant-by-slug
    # endpoint (cached) and project it through THIS already-walled-gardened
    # portal-config response — so the pre-auth captive device never has to reach
    # auth-api directly. Best-effort: on any failure we fall back to the org name
    # (+ default primary color) so the captive page always renders.
    from app.services.auth_branding_client import get_tenant_branding
    branding = await get_tenant_branding(organization.slug) or {}
    logo_url = branding.get("logo_url")
    primary_color = branding.get("primary_color") or "#9100B0"
    portal_title = branding.get("portal_title") or organization.name
    portal_description = branding.get("portal_description")

    return PortalConfigResponse(
        organization_name=organization.name,
        logo_url=logo_url,
        primary_color=primary_color,
        portal_title=portal_title,
        portal_description=portal_description,
        show_packages=show_packages,
        allow_guest_purchases=allow_guest,
        redirect_url=redirect_url,
        provider_active=provider_active,
        provider_contact=provider_contact,
    )


@router.get("/{org_slug}/packages", response_model=List[PackageResponse])
async def get_packages(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get available ISP packages (hotspot, PPPoE, data/internet plans).

    Returns organization-specific packages only (ISP-level plans).
    Platform-level plans are for licenses/subscriptions, not shown here.

    Public endpoint - no authentication required.
    """
    # Get organization-specific packages (all ISP plan types)
    result = await db.execute(
        select(ServicePlan)
        .where(
            ServicePlan.organization_id == organization.id,
            ServicePlan.plan_type.in_([PlanType.HOTSPOT, PlanType.PPPOE, PlanType.INTERNET, PlanType.BOTH]),
            ServicePlan.status == PlanStatus.ACTIVE,
        )
        .order_by(ServicePlan.sort_order, ServicePlan.price)
    )
    plans = list(result.scalars().all())

    packages = []
    for plan in plans:
        # Get features
        features = []
        if plan.is_unlimited_data:
            features.append("Unlimited data")
        elif plan.data_limit > 0:
            features.append(f"{plan.data_limit} GB data")

        if plan.is_unlimited_time:
            features.append("Unlimited time")
        elif plan.time_limit > 0:
            features.append(f"{plan.time_limit} hours")

        features.append(f"Up to {plan.download_speed} Mbps download")
        features.append(f"Up to {plan.upload_speed} Mbps upload")

        if plan.concurrent_sessions > 1:
            features.append(f"{plan.concurrent_sessions} devices")

        # Effective access window the customer actually gets — single source of
        # truth shared with voucher-redeem expiry + the expiry reconciler. The
        # captive card renders THIS so the displayed validity always matches what
        # is provisioned (e.g. a 5-min package reads "5 min", never "1 Day").
        try:
            window_hours = plan.access_window_hours()
        except Exception:
            window_hours = (plan.validity_days or 0) * 24

        packages.append(PackageResponse(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            price=float(plan.price),
            currency=plan.currency,
            validity_days=plan.validity_days,
            download_speed=plan.download_speed,
            upload_speed=plan.upload_speed,
            data_limit=plan.data_limit,
            time_limit=plan.time_limit,
            is_unlimited_data=plan.is_unlimited_data,
            is_unlimited_time=plan.is_unlimited_time,
            is_popular=plan.is_popular,
            features=features,
            plan_type=plan.plan_type.value if hasattr(plan.plan_type, "value") else str(plan.plan_type),
            concurrent_sessions=plan.concurrent_sessions or 1,
            duration_minutes=plan.duration_minutes,
            access_window_hours=float(window_hours or 0.0),
        ))

    return packages


@router.post("/{org_slug}/login", response_model=HotspotLoginResponse)
async def hotspot_login(
    org_slug: str,
    request: Request,
    data: HotspotLoginRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Hotspot customer login for returning users.

    Validates credentials against voucher codes or subscriptions, checks if the
    associated package is still active, syncs the user to MikroTik with proper
    limits, and returns a login URL for the captive redirect.

    Public endpoint - no authentication required.
    """
    client_ip = request.client.host if request.client else None
    mac_address = data.mac_address

    # ── Strategy 1: Match against voucher hotspot credentials ──────────
    voucher_result = await db.execute(
        select(VoucherCode)
        .where(
            VoucherCode.organization_id == organization.id,
            VoucherCode.hotspot_username == data.username,
            VoucherCode.hotspot_password == data.password,
        )
    )
    voucher = voucher_result.scalar_one_or_none()

    if voucher:
        # Check voucher expiry
        if voucher.status == VoucherStatus.EXPIRED or (
            voucher.expires_at and datetime.utcnow() > voucher.expires_at
        ):
            voucher.status = VoucherStatus.EXPIRED
            await db.commit()
            return HotspotLoginResponse(
                success=False,
                message="Your package has expired. Please purchase a new package.",
                is_active=False,
            )

        # Get associated plan for limits
        plan_result = await db.execute(
            select(ServicePlan).where(ServicePlan.id == voucher.plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            return HotspotLoginResponse(
                success=False,
                message="Associated package not found.",
                is_active=False,
            )

        # Sync to MikroTik router
        login_url = await _sync_hotspot_user_to_router(
            db=db,
            organization=organization,
            username=data.username,
            password=data.password,
            plan=plan,
            mac_address=mac_address,
            comment=f"Login - voucher {voucher.code} - {plan.name}",
        )

        # Create / refresh customer session
        session_token = secrets.token_urlsafe(32)
        validity_hours = plan.validity_days * 24
        if plan.time_limit > 0:
            validity_hours = min(validity_hours, plan.time_limit)
        expires_at = voucher.expires_at or (datetime.utcnow() + timedelta(hours=validity_hours))

        session = CustomerSession(
            organization_id=organization.id,
            session_token=session_token,
            mac_address=mac_address or "00:00:00:00:00:00",
            ip_address=client_ip,
            status=SessionStatus.ACTIVE,
            expires_at=expires_at,
            plan_name=plan.name,
            speed_limit_down=plan.download_speed * 1000,
            speed_limit_up=plan.upload_speed * 1000,
            data_limit=plan.data_limit * 1024 * 1024 * 1024 if plan.data_limit > 0 else None,
        )
        db.add(session)
        await db.commit()

        return HotspotLoginResponse(
            success=True,
            message="Connected successfully.",
            session_token=session_token,
            login_url=login_url,
            plan_name=plan.name,
            expires_at=expires_at,
            is_active=True,
        )

    # ── Strategy 2: Match against subscription credentials ─────────────
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.organization_id == organization.id,
            Subscription.username == data.username,
            Subscription.password == data.password,
            Subscription.subscription_type == SubscriptionType.HOTSPOT,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()

    if subscription:
        if not subscription.is_active:
            return HotspotLoginResponse(
                success=False,
                message="Your subscription has expired. Please renew your package.",
                is_active=False,
            )

        plan = subscription.plan
        if not plan:
            return HotspotLoginResponse(
                success=False,
                message="Associated package not found.",
                is_active=False,
            )

        # Sync to MikroTik
        login_url = await _sync_hotspot_user_to_router(
            db=db,
            organization=organization,
            username=data.username,
            password=data.password,
            plan=plan,
            mac_address=mac_address,
            comment=f"Login - subscription #{subscription.id} - {plan.name}",
        )

        # Update subscription activity
        subscription.last_activity = datetime.utcnow()
        subscription.session_count += 1
        await db.commit()

        return HotspotLoginResponse(
            success=True,
            message="Connected successfully.",
            login_url=login_url,
            plan_name=plan.name,
            expires_at=subscription.end_date,
            is_active=True,
        )

    # ── No match ──────────────────────────────────────────────────────
    return HotspotLoginResponse(
        success=False,
        message="Invalid username or password.",
        is_active=False,
    )


def _build_rate_limit(plan) -> str:
    """MikroTik ``rate-limit`` string for a plan's bandwidth, with optional burst.

    Base form: ``"<down>M/<up>M"`` (Mbps). When the plan enables burst and has
    burst rates configured, the full MikroTik burst form is emitted:

        rxRate/txRate rxBurstRate/txBurstRate rxBurstThreshold/txBurstThreshold rxBurstTime/txBurstTime

    Here rx = client download, tx = client upload (RouterOS orders rx/tx).
    burst_threshold on the plan is a PERCENTAGE of the base rate; MikroTik wants an
    absolute rate for the threshold, so it is computed as base * pct/100 (>=1M).
    Returns "" for an unlimited (0/0) plan — valid RouterOS for "no shaping".
    """
    download = plan.download_speed or 0
    upload = plan.upload_speed or 0
    if not download and not upload:
        return ""
    base = f"{download}M/{upload}M"

    if not getattr(plan, "enable_burst", False):
        return base
    b_down = getattr(plan, "burst_download", None) or 0
    b_up = getattr(plan, "burst_upload", None) or 0
    if not b_down and not b_up:
        # Burst flagged but no rates configured -> nothing meaningful to emit.
        return base

    pct = getattr(plan, "burst_threshold", None) or 0
    if pct and pct > 0:
        thr_down = max(1, int(round(download * pct / 100.0)))
        thr_up = max(1, int(round(upload * pct / 100.0)))
    else:
        # No explicit threshold -> use the base rate as the threshold.
        thr_down = max(1, download)
        thr_up = max(1, upload)
    btime = getattr(plan, "burst_time", None) or 0

    return (
        f"{download}M/{upload}M "
        f"{b_down}M/{b_up}M "
        f"{thr_down}M/{thr_up}M "
        f"{btime}/{btime}"
    )


def _resolve_hotspot_gateway(router_obj: Router) -> str:
    """Hotspot LAN gateway the *client's* browser must POST its login to.

    This is the bridge gateway assigned during provisioning (default 172.31.0.1) —
    NOT router_obj.ip_address, which is the cloud-side management address the
    captive client (sitting on the hotspot LAN) cannot reach. Sourced from the
    stored provisioning config, falling back to the standard /16 gateway.
    """
    import json

    cfg = {}
    if router_obj.config:
        try:
            cfg = json.loads(router_obj.config)
        except (ValueError, TypeError):
            cfg = {}
    gateway = cfg.get("gateway")
    if gateway:
        return str(gateway)
    try:
        from app.modules.provisioning.commands import calculate_network_config

        subnet = cfg.get("subnet_address", "172.31.0.0")
        cidr = int(cfg.get("cidr", 16) or 16)
        return calculate_network_config(subnet, cidr)["gateway"]
    except Exception:
        return "172.31.0.1"


async def _sync_hotspot_user_to_router(
    db: AsyncSession,
    organization: Organization,
    username: str,
    password: str,
    plan: ServicePlan,
    *,
    mac_address: Optional[str] = None,
    comment: Optional[str] = None,
    source: str = "hotspot_login",
    source_id: Optional[str] = None,
) -> Optional[str]:
    """
    Create / update a hotspot user on the org's MikroTik router, NAT-safely.

    Single source of truth for hotspot-user provisioning — shared by the captive
    login, voucher redemption and post-payment flows. Prefers the polling-agent
    command queue (the cloud cannot reach a NATed router directly); only falls
    back to a direct MikroTik API call for routers without the agent (reachable
    LAN/VPN). Returns the MikroTik login URL when the direct path runs, else None
    (the agent path applies it asynchronously on the next poll).
    """
    router_result = await db.execute(
        select(Router).where(
            Router.organization_id == organization.id,
            Router.is_active == True,
        ).limit(1)
    )
    router_obj = router_result.scalar_one_or_none()

    if not router_obj:
        logger.warning(
            f"No active router for org {organization.id}. "
            f"Hotspot user {username} not synced."
        )
        return None

    # Preferred NAT-safe path: queue create_user for the agent's next poll.
    if getattr(router_obj, "agent_installed", False) and getattr(router_obj, "agent_token", None):
        try:
            from app.services.router_agent import RouterAgentService

            rate_limit = _build_rate_limit(plan)
            agent_service = RouterAgentService(db)
            await agent_service.queue_command(
                router_id=router_obj.id,
                action="create_user",
                params={
                    "username": username,
                    "password": password,
                    "type": "hotspot",
                    "profile": f"plan_{plan.id}",
                    "rate_limit": rate_limit,
                },
                priority=2,
                source=source,
                source_id=source_id,
            )
            logger.info(
                f"Queued create_user hotspot {username} -> router {router_obj.name} (agent, {source})"
            )
            # Router-side hard limits (defense-in-depth): queue a set_limits action
            # right after create_user so the router self-enforces time/data caps even
            # if the cloud reconciler is down. limit-uptime is the package's
            # EFFECTIVE access window (per-login-uptime model) derived from the single
            # source of truth ``plan.limit_uptime_str()`` — honours duration_minutes
            # so sub-hour packages (e.g. 5 min -> "300s") DO get a cap. data_limit=GB.
            # Skipped only when the plan is unlimited/duration-less.
            limit_uptime = plan.limit_uptime_str()
            limit_bytes = ""
            if plan.data_limit and plan.data_limit > 0 and not plan.is_unlimited_data:
                limit_bytes = str(plan.data_limit * 1024 * 1024 * 1024)  # GB -> bytes
            if limit_uptime or limit_bytes:
                from app.api.v1.network.routers import _queue_agent_action
                await _queue_agent_action(
                    db, router_obj, "set_limits", None,
                    extra_query={"u": username, "lu": limit_uptime, "lb": limit_bytes},
                )
        except Exception as e:
            logger.error(f"Failed to queue hotspot user {username} for router {router_obj.name}: {e}")
        # Even on the agent (NAT) path, hand back the hotspot gateway login URL so
        # the captive page can authenticate the *client* directly — works whether
        # the page was reached via captive redirect (link-login-only) OR opened
        # manually. The router accepts the credentials once the queued create_user
        # lands on its next poll.
        gateway = _resolve_hotspot_gateway(router_obj)
        login_url = f"http://{gateway}/login?username={username}&password={password}"
        if mac_address:
            login_url += f"&mac={mac_address}"
        return login_url

    try:
        client = get_mikrotik_client()
        connection = await client.connect(
            ip_address=router_obj.ip_address,
            username=router_obj.username,
            password=router_obj.password,
            port=router_obj.port,
        )

        # limit-uptime = the package's EFFECTIVE access window (per-login-uptime
        # model) from the single source of truth; honours duration_minutes so
        # sub-hour packages get a real cap. data_limit=GB.
        limit_uptime = plan.limit_uptime_str() or None
        data_limit_bytes = None
        if plan.data_limit > 0 and not plan.is_unlimited_data:
            data_limit_bytes = plan.data_limit * 1024 * 1024 * 1024  # GB → bytes

        await client.create_hotspot_user(
            connection=connection,
            username=username,
            password=password,
            profile="default",
            **{
                k: v
                for k, v in {
                    "limit-uptime": limit_uptime,
                    "limit-bytes-total": data_limit_bytes,
                    "comment": comment,
                }.items()
                if v is not None
            },
        )

        await client.disconnect(router_obj.ip_address, router_obj.port)

        logger.info(
            f"Synced hotspot user {username} to router {router_obj.name}"
        )

        # Build MikroTik login URL — the client posts to the hotspot LAN gateway,
        # not the cloud-side management ip_address (which the client can't reach).
        gateway = _resolve_hotspot_gateway(router_obj)
        login_url = (
            f"http://{gateway}/login"
            f"?username={username}&password={password}"
        )
        if mac_address:
            login_url += f"&mac={mac_address}"

        return login_url
    except Exception as e:
        logger.error(
            f"Failed to sync hotspot user {username} to router "
            f"{router_obj.name}: {e}"
        )
        return None


async def _purchase_via_treasury(
    *,
    db: AsyncSession,
    request: Request,
    organization: Organization,
    org_slug: str,
    plan: ServicePlan,
    data: "PurchaseRequest",
) -> Optional[PurchaseResponse]:
    """Create a treasury payment intent and return the shared pay-page checkout.

    This is the ONLY customer-payment path: customer hotspot purchases are fully
    centralized on treasury-api. The intent is created under the ISP's tenant
    UUID with source_service="isp", so treasury attributes + settles the revenue
    to that ISP. A local CustomerPurchase snapshot is still written (status
    "pending") with the treasury intent id stored on it, so the payment
    confirmation (NATS consumer primary, treasury get_status poll fallback) can
    run the unchanged voucher + hotspot-user provisioning.

    Returns a PurchaseResponse whose checkout_url is the treasury-ui pay page
    (with redirect back to isp-billing's payment/callback). Returns None ONLY
    when treasury is unusable (not configured / call failed); the caller then
    surfaces an error — there is NO local-gateway fallback anymore.
    """
    from app.services.treasury_client import TreasuryClient, TreasuryError

    client = TreasuryClient()
    if not client.is_configured:
        logger.error(
            "treasury client is not configured (treasury_api_url / "
            "internal_service_key) — cannot process customer payment for org %s",
            organization.id,
        )
        return None

    import uuid

    reference = f"HS-{organization.slug[:6].upper()}-{uuid.uuid4().hex[:8].upper()}"
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Local snapshot first (so the poller can find it by reference even if the
    # browser returns before treasury's webhook/poll confirms).
    purchase = CustomerPurchase(
        organization_id=organization.id,
        phone_number=data.phone_number,
        email=data.email,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        payment_method="treasury",
        payment_reference=reference,
        payment_status="pending",
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.add(purchase)
    await db.commit()

    # Build the isp-billing callback the customer returns to after paying. We
    # pass reference={our payment_reference} so the existing callback poll of
    # /payment/status?reference=... resolves THIS CustomerPurchase (and thus the
    # Phase-0 captive-device login still runs).
    origin = request.headers.get("origin", "") or (app_settings_frontend_url() or "")
    redirect_url = (
        f"{origin}/payment/callback"
        f"?payment_type=hotspot_purchase&org={org_slug}&reference={reference}"
    )

    try:
        intent = await client.create_payment_intent(
            tenant=str(organization.uuid),
            amount=str(plan.price),
            currency=plan.currency,
            reference_id=reference,
            reference_type="hotspot_purchase",
            source_service="isp",
            description=f"{plan.name} - {organization.name}",
            idempotency_key=reference,
            customer_email=data.email,
            customer_phone=data.phone_number or None,
            callback_url=redirect_url,
            metadata={
                "organization_id": organization.id,
                "plan_id": plan.id,
                "purchase_id": purchase.id,
                "payment_reference": reference,
            },
        )
    except TreasuryError as exc:
        logger.error("treasury create_payment_intent failed for %s: %s", reference, exc)
        # Mark the snapshot failed and fall back to direct gateway.
        purchase.payment_status = "failed"
        await db.commit()
        return None

    intent_id = intent.get("intent_id") or intent.get("id")
    if not intent_id:
        logger.error("treasury intent response missing intent_id: %s", intent)
        purchase.payment_status = "failed"
        await db.commit()
        return None

    purchase.treasury_payment_intent_id = str(intent_id)
    purchase.payment_status = "processing"
    await db.commit()

    checkout_url = client.build_pay_page_url(
        tenant=str(organization.uuid),
        intent_id=str(intent_id),
        amount=str(plan.price),
        currency=plan.currency,
        reference_id=reference,
        reference_type="hotspot_purchase",
        redirect_url=redirect_url,
        description=f"{plan.name} - {organization.name}",
        initiate_url=intent.get("initiate_url"),
        button_text="Start Browsing",
    )

    return PurchaseResponse(
        success=True,
        reference=reference,
        message="Choose a payment method to complete your purchase.",
        checkout_url=checkout_url,
        status="pending",
        # Embedded-modal fields (captive buy page opens TreasuryPaymentModal).
        intent_id=str(intent_id),
        initiate_url=intent.get("initiate_url"),
        tenant_id=str(organization.uuid),
        amount=float(plan.price),
        currency=plan.currency,
        reference_type="hotspot_purchase",
    )


def app_settings_frontend_url() -> Optional[str]:
    """Frontend base URL used to build the treasury return/callback URL when the
    request carries no Origin header (e.g. server-initiated). Falls back to the
    configured frontend_url setting."""
    from app.core.config import settings as _s

    return _s.frontend_url


@router.post("/{org_slug}/purchase", response_model=PurchaseResponse)
async def purchase_package(
    org_slug: str,
    request: Request,
    data: PurchaseRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Purchase a hotspot package — payment is centralized on treasury-api.

    Customer payments are NO LONGER processed by isp-billing's own gateways:
    treasury-api is the single source of truth. We always create a treasury
    payment intent and hand the customer the shared treasury pay page; the
    purchase is confirmed via the NATS consumer (primary) or the treasury
    get_status poll (fallback), both of which run the same voucher + hotspot-user
    provisioning so the Phase-0 captive-device login still works.

    Public endpoint.
    """
    # Block end-customer purchases when the PROVIDER's own subscription has fully
    # lapsed (past grace). Neutral, customer-facing message + provider contact —
    # never billing/suspension wording aimed at the customer.
    from app.services.provider_gate import resolve_provider_access
    provider_active, provider_contact = await resolve_provider_access(organization)
    if not provider_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "provider_subscription_inactive",
                "message": (
                    "This hotspot is temporarily unavailable. Please contact the "
                    "provider to restore service."
                ),
                "contact": provider_contact,
            },
        )

    # Get the plan
    result = await db.execute(
        select(ServicePlan)
        .where(
            ServicePlan.id == data.plan_id,
            ServicePlan.organization_id == organization.id,
            ServicePlan.status == PlanStatus.ACTIVE,
        )
    )
    plan = result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Package not found"
        )

    # ── Treasury-api is the ONLY customer-payment path ──────────────────────
    # No config flag, no direct-gateway fallback: the intent is created under the
    # ISP's tenant UUID (source_service="isp") so treasury attributes + settles
    # the revenue to that ISP. If treasury is unusable we surface an error rather
    # than silently falling back to a local gateway.
    treasury_result = await _purchase_via_treasury(
        db=db,
        request=request,
        organization=organization,
        org_slug=org_slug,
        plan=plan,
        data=data,
    )
    if treasury_result is not None:
        return treasury_result

    # _purchase_via_treasury returns None only when treasury is not usable
    # (unconfigured / intent create failed). There is no local-gateway fallback.
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Payment service is temporarily unavailable. Please try again.",
    )


@router.post("/{org_slug}/voucher/redeem", response_model=VoucherRedeemResponse)
async def redeem_voucher(
    org_slug: str,
    request: Request,
    data: VoucherRedeemRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Redeem a voucher code.

    Public endpoint - activates session for the voucher.
    """
    # Find voucher
    result = await db.execute(
        select(VoucherCode)
        .where(
            VoucherCode.organization_id == organization.id,
            VoucherCode.code == data.code.upper().strip(),
        )
    )
    voucher = result.scalar_one_or_none()

    if not voucher:
        return VoucherRedeemResponse(
            success=False,
            message="Invalid voucher code",
        )

    if voucher.status != VoucherStatus.ACTIVE:
        return VoucherRedeemResponse(
            success=False,
            message="Voucher has already been used or expired",
        )

    if voucher.is_used:
        return VoucherRedeemResponse(
            success=False,
            message="Voucher has already been used",
        )

    # Check expiry
    if voucher.expires_at and datetime.utcnow() > voucher.expires_at:
        voucher.status = VoucherStatus.EXPIRED
        await db.commit()
        return VoucherRedeemResponse(
            success=False,
            message="Voucher has expired",
        )

    # Get associated plan
    plan_result = await db.execute(
        select(ServicePlan).where(ServicePlan.id == voucher.plan_id)
    )
    plan = plan_result.scalar_one_or_none()

    if not plan:
        return VoucherRedeemResponse(
            success=False,
            message="Associated package not found",
        )

    # Mark voucher as used
    client_ip = request.client.host if request.client else None

    voucher.is_used = True
    voucher.status = VoucherStatus.USED
    voucher.used_at = datetime.utcnow()
    voucher.used_mac_address = data.mac_address
    voucher.used_ip_address = client_ip

    # Defensive: ensure the voucher has hotspot credentials. Vouchers issued
    # before credential auto-generation (or via legacy paths) may have NULLs,
    # which would otherwise leave the customer unable to authenticate.
    if not voucher.hotspot_username or not voucher.hotspot_password:
        from app.utils.hotspot_username import generate_hotspot_credentials
        gen_user, gen_pass = await generate_hotspot_credentials(db, organization.id)
        voucher.hotspot_username = voucher.hotspot_username or gen_user
        voucher.hotspot_password = voucher.hotspot_password or gen_pass

    # Calculate session expiry — honours BOTH validity_days and time_limit via the
    # shared helper (single source of truth with the expiry reconciler).
    validity_hours = plan.access_window_hours()
    expires_at = datetime.utcnow() + timedelta(hours=validity_hours)

    # Create session
    import secrets
    session_token = secrets.token_urlsafe(32)

    session = CustomerSession(
        organization_id=organization.id,
        session_token=session_token,
        mac_address=data.mac_address or "00:00:00:00:00:00",
        ip_address=client_ip,
        status=SessionStatus.ACTIVE,
        expires_at=expires_at,
        plan_name=plan.name,
        speed_limit_down=plan.download_speed * 1000,  # Convert to kbps
        speed_limit_up=plan.upload_speed * 1000,
        data_limit=plan.data_limit * 1024 * 1024 * 1024 if plan.data_limit > 0 else None,  # Convert to bytes
    )
    db.add(session)
    await db.flush()

    # Sync the hotspot user onto the org's router (NAT-safe; best-effort).
    # Returns the gateway login URL so the client can authenticate itself.
    login_url = None
    if voucher.hotspot_username and voucher.hotspot_password:
        # Router sync is STRICTLY best-effort: a router-sync failure must never
        # fail the redeem (the voucher is already consumed + the session created).
        # _sync_hotspot_user_to_router catches its own errors, but we wrap the call
        # too so any unexpected error still returns login_url=None gracefully.
        try:
            login_url = await _sync_hotspot_user_to_router(
                db,
                organization,
                voucher.hotspot_username,
                voucher.hotspot_password,
                plan,
                mac_address=data.mac_address,
                source="voucher_redeem",
                source_id=str(voucher.id),
                comment=f"Redeemed voucher {voucher.code} - {plan.name}",
            )
        except Exception as exc:  # noqa: BLE001 - redeem must succeed regardless
            logger.error(
                "voucher redeem: router sync failed for voucher %s (non-fatal): %s",
                voucher.code,
                exc,
            )
            login_url = None

    await db.commit()

    # Issue 4 (FOUNDATION): mirror this voucher REDEEM into the dashboard's data
    # model (User + Subscription) so the redeemed customer surfaces on
    # Users/Customers/Expiry/analytics exactly like PPPoE. No Payment is recorded —
    # the revenue was recognized when the voucher was SOLD (recording one here would
    # double-count). Idempotent + fully guarded; runs AFTER the critical
    # voucher/session commit above so a non-fatal bridge failure can never undo the
    # redeem.
    if voucher.hotspot_username and voucher.hotspot_password:
        try:
            from app.services.hotspot_dashboard_bridge import (
                bridge_hotspot_purchase_to_dashboard,
            )

            await bridge_hotspot_purchase_to_dashboard(
                db,
                organization,
                plan,
                hotspot_username=voucher.hotspot_username,
                hotspot_password_hash=voucher.hotspot_password,
                expires_at=expires_at,
                is_voucher_redeem=True,
            )
        except Exception as bridge_exc:  # never break the redeem
            logger.error(
                "hotspot dashboard bridge failed for voucher %s (non-fatal): %s",
                voucher.code,
                bridge_exc,
            )

    return VoucherRedeemResponse(
        success=True,
        message="Voucher redeemed successfully. You can now connect to the internet.",
        plan_name=plan.name,
        validity_hours=validity_hours,
        expires_at=expires_at,
        hotspot_username=voucher.hotspot_username,
        hotspot_password=voucher.hotspot_password,
        login_url=login_url,
    )


@router.get("/{org_slug}/connection-status")
async def get_connection_status(
    org_slug: str,
    username: str = Query(..., description="Hotspot username to check readiness for"),
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """Report whether the hotspot user has actually been created on the router.

    The captive page polls this right after a voucher redeem / confirmed payment
    so it can AUTO-LOGIN the moment the user exists, instead of submitting the
    login form blindly ~600ms later and racing the agent's create_user (which
    only lands on the agent's next poll). For direct-API (non-agent / VPN-reachable)
    routers the user is created synchronously, so there is no queued command and
    we report ready immediately.

    Public endpoint (captive client is unauthenticated).
    """
    from app.models.router_command import RouterCommand, CommandStatus

    router_result = await db.execute(
        select(Router).where(
            Router.organization_id == organization.id,
            Router.is_active == True,
        ).limit(1)
    )
    router_obj = router_result.scalar_one_or_none()
    if not router_obj:
        return {"ready": False, "status": "no_router"}

    # Most recent create_user command for this username on the org's router.
    # params is a JSON column; filter in Python over a bounded recent window to
    # avoid depending on a JSON ->> operator cast.
    cmd_result = await db.execute(
        select(RouterCommand)
        .where(
            RouterCommand.router_id == router_obj.id,
            RouterCommand.action == "create_user",
        )
        .order_by(RouterCommand.created_at.desc())
        .limit(50)
    )
    cmd = next(
        (c for c in cmd_result.scalars().all() if (c.params or {}).get("username") == username),
        None,
    )

    # No queued command => direct path already created the user (or the router
    # has no agent), so there is nothing to wait on.
    if cmd is None:
        return {"ready": True, "status": "ready"}
    if cmd.status == CommandStatus.SUCCESS:
        return {"ready": True, "status": "ready"}
    if cmd.status == CommandStatus.FAILED:
        return {"ready": False, "status": "failed", "message": cmd.result_message}
    return {"ready": False, "status": "pending"}


@router.get("/{org_slug}/session/status", response_model=SessionStatusResponse)
async def get_session_status(
    org_slug: str,
    request: Request,
    mac_address: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get current session status.

    Public endpoint - uses IP or MAC address to find session.
    """
    client_ip = request.client.host if request.client else None

    # Find active session
    query = select(CustomerSession).where(
        CustomerSession.organization_id == organization.id,
        CustomerSession.status == SessionStatus.ACTIVE,
    )

    if mac_address:
        query = query.where(CustomerSession.mac_address == mac_address)
    elif client_ip:
        query = query.where(CustomerSession.ip_address == client_ip)
    else:
        return SessionStatusResponse(is_active=False)

    query = query.order_by(CustomerSession.created_at.desc()).limit(1)

    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        return SessionStatusResponse(is_active=False)

    # Check if session is expired
    now = datetime.utcnow()
    if session.expires_at and now > session.expires_at:
        session.status = SessionStatus.EXPIRED
        session.ended_at = session.expires_at
        await db.commit()
        return SessionStatusResponse(is_active=False)

    # Calculate remaining time
    time_remaining = None
    if session.expires_at:
        time_remaining = int((session.expires_at - now).total_seconds())
        if time_remaining < 0:
            time_remaining = 0

    # Calculate data usage
    data_used_mb = (session.bytes_in + session.bytes_out) / (1024 * 1024)
    data_limit_mb = session.data_limit / (1024 * 1024) if session.data_limit else None

    return SessionStatusResponse(
        is_active=True,
        plan_name=session.plan_name,
        started_at=session.started_at,
        expires_at=session.expires_at,
        time_remaining_seconds=time_remaining,
        data_used_mb=data_used_mb,
        data_limit_mb=data_limit_mb,
    )


@router.post("/{org_slug}/webhooks/payment")
async def payment_webhook(
    org_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    DEPRECATED — direct-gateway payment callback webhook.

    Customer payments are now centralized on treasury-api, so isp-billing no
    longer initiates Paystack/M-PESA gateways for customer purchases and these
    providers no longer call this endpoint. Confirmation now flows via the NATS
    consumer (treasury.payment.succeeded, primary) and the treasury get_status
    poll in GET /payment/status (fallback).

    The endpoint is retained (importable, route preserved) only for backward
    compatibility / any in-flight legacy callbacks; it remains idempotent because
    it delegates to the unchanged _process_successful_payment. New integrations
    must NOT depend on it.
    """
    import json
    from app.core.logging import get_logger

    logger = get_logger(__name__)

    try:
        body = await request.body()
        payload = json.loads(body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract reference from different gateway formats
    reference = None
    payment_status = None

    # M-PESA callback format
    if "Body" in payload and "stkCallback" in payload.get("Body", {}):
        stk = payload["Body"]["stkCallback"]
        reference = stk.get("CheckoutRequestID")
        result_code = stk.get("ResultCode")
        payment_status = "completed" if result_code == 0 else "failed"

    # Paystack callback format
    elif "event" in payload and "data" in payload:
        event_type = payload.get("event", "")
        data = payload.get("data", {})
        reference = data.get("reference")

        if event_type == "charge.success":
            payment_status = "completed"
        elif event_type in ["charge.failed", "transfer.failed"]:
            payment_status = "failed"

    # Generic format (direct reference)
    elif "reference" in payload:
        reference = payload.get("reference")
        payment_status = payload.get("status", "completed")

    if not reference:
        logger.warning(f"No reference found in webhook payload: {payload}")
        return {"status": "received", "message": "No reference found"}

    # Find the purchase record
    result = await db.execute(
        select(CustomerPurchase)
        .where(
            CustomerPurchase.payment_reference == reference,
            CustomerPurchase.organization_id == organization.id,
        )
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        logger.warning(f"Purchase not found for reference: {reference}")
        return {"status": "received", "message": "Purchase not found"}

    # Update purchase status
    if payment_status == "completed":
        await _process_successful_payment(db, purchase, organization)
    elif payment_status == "failed":
        purchase.payment_status = "failed"
        await db.commit()

    logger.info(f"Processed webhook for reference {reference}: status={payment_status}")
    return {"status": "received", "payment_status": payment_status}


@router.get("/{org_slug}/payment/status")
async def get_payment_status(
    org_slug: str,
    reference: str = Query(..., description="Payment reference"),
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Check payment status and get voucher code if payment is complete.

    Used by frontend to poll for payment completion.

    If payment is still processing, this will attempt to verify with the payment
    gateway in case the webhook was not received.
    """
    # Find the purchase record
    result = await db.execute(
        select(CustomerPurchase)
        .where(
            CustomerPurchase.payment_reference == reference,
            CustomerPurchase.organization_id == organization.id,
        )
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        return {
            "status": "not_found",
            "is_completed": False,
            "message": "Payment reference not found",
        }

    # Confirmation is owned by treasury-api. The NATS consumer
    # (treasury.payment.succeeded) is the PRIMARY path; this poll of treasury's
    # get_status is the FALLBACK for when NATS is not yet configured / a delivery
    # was missed. There is NO local-gateway verification anymore. On success we
    # run the SAME voucher + hotspot-user provisioning, so the response still
    # carries the credentials the Phase-0 captive callback needs.
    if (
        purchase.payment_status == "processing"
        and purchase.treasury_payment_intent_id
    ):
        try:
            from app.services.treasury_client import TreasuryClient, TreasuryError

            client = TreasuryClient()
            if client.is_configured:
                intent = await client.get_status(
                    tenant=str(organization.uuid),
                    intent_id=purchase.treasury_payment_intent_id,
                )
                # IMPORTANT: treasury-api's GET-intent (S2S) serializes the Go
                # `PaymentIntent` struct WITHOUT json tags, so the field comes
                # back as "Status" (capitalized) — NOT "status". The create-intent
                # *response* uses tagged DTOs (lowercase), which is why intent
                # CAPTURE works but this poll silently never saw success: it read
                # `intent.get("status")` (always None) so the purchase stayed
                # "processing" forever and only the client-side countdown ever
                # "confirmed" it (issue 4). Read BOTH casings defensively.
                treasury_status = str(
                    intent.get("status")
                    or intent.get("Status")
                    or ""
                ).lower()
                if treasury_status in ("succeeded", "success", "completed", "paid"):
                    logger.info(
                        "treasury intent %s succeeded for reference %s, provisioning",
                        purchase.treasury_payment_intent_id,
                        reference,
                    )
                    await _process_successful_payment(db, purchase, organization)
                elif treasury_status in ("failed", "cancelled", "canceled", "expired"):
                    purchase.payment_status = "failed"
                    await db.commit()
        except TreasuryError as e:
            logger.error("Error verifying treasury intent for %s: %s", reference, e)
            # Keep current status; the customer can retry / the NATS consumer may land.

    # Check if payment is completed
    is_completed = purchase.payment_status in ["completed", "failed"]
    is_success = purchase.payment_status == "completed"

    response = {
        "status": purchase.payment_status,
        "is_completed": is_completed,
        # is_success distinguishes a COMPLETED-success from a COMPLETED-failed
        # (both have is_completed=True). Without it the buy page rendered the
        # "Payment Successful!" screen + auto-connect even on a FAILED payment.
        "is_success": is_success,
        "message": "Payment successful" if is_success else (
            "Payment failed" if purchase.payment_status == "failed" else "Payment pending"
        ),
    }

    # Include voucher and hotspot credentials if payment was successful
    if is_success and purchase.voucher_code_id:
        voucher_result = await db.execute(
            select(VoucherCode).where(VoucherCode.id == purchase.voucher_code_id)
        )
        voucher = voucher_result.scalar_one_or_none()
        if voucher:
            response["voucher_code"] = voucher.code
            response["username"] = voucher.hotspot_username
            response["password"] = voucher.hotspot_password
            # Include hotspot credentials for login
            if voucher.hotspot_username:
                response["hotspot_username"] = voucher.hotspot_username
                response["hotspot_password"] = voucher.hotspot_password
                # Gateway login URL so the captive page can authenticate the
                # client on manual navigation (no captive-redirect param).
                # ALWAYS build login_url when we have credentials: if the router
                # row lookup fails we fall back to the standard hotspot gateway
                # (172.31.0.1) so the frontend never bare-redirects an
                # unauthenticated device (which caused ERR_CONNECTION_CLOSED).
                router_result = await db.execute(
                    select(Router).where(
                        Router.organization_id == organization.id,
                        Router.is_active == True,
                    ).limit(1)
                )
                router_obj = router_result.scalar_one_or_none()
                gw = _resolve_hotspot_gateway(router_obj) if router_obj else "172.31.0.1"
                response["login_url"] = (
                    f"http://{gw}/login"
                    f"?username={voucher.hotspot_username}"
                    f"&password={voucher.hotspot_password}"
                )

    return response


async def _process_successful_payment(
    db: AsyncSession,
    purchase: CustomerPurchase,
    organization: Organization,
):
    """
    Process a successful payment by creating voucher and hotspot user.

    This is extracted from the webhook handler to be reused by manual verification.
    """
    try:
        purchase.payment_status = "completed"
        purchase.completed_at = datetime.utcnow()

        # Get the plan
        plan_result = await db.execute(
            select(ServicePlan).where(ServicePlan.id == purchase.plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            logger.error(f"Plan {purchase.plan_id} not found for purchase {purchase.id}")
            await db.commit()  # Still commit the payment status
            return

        # Generate a voucher code for the customer
        voucher_code = VoucherCode.generate_code(format_pattern="XXXX-XXXX-XXXX")

        # Generate hotspot credentials (username like C029, password like 865)
        hotspot_username, hotspot_password = await generate_hotspot_credentials(
            db=db,
            organization_id=organization.id,
            password_length=3
        )

        # Create voucher with hotspot credentials
        voucher = VoucherCode(
            organization_id=organization.id,
            code=voucher_code,
            plan_id=plan.id,
            # Online purchase: the hotspot user is provisioned immediately below, so
            # the voucher is already "activated" -> mark USED with used_at=now. This
            # unifies expiry handling (the expiry reconciler keys the access window
            # off used_at + plan validity) and prevents it being redeemed again.
            status=VoucherStatus.USED,
            is_used=True,
            used_at=datetime.utcnow(),
            value=purchase.amount,
            expires_at=datetime.utcnow() + timedelta(days=30),  # pre-use deadline (n/a once used)
            hotspot_username=hotspot_username,
            hotspot_password=hotspot_password,
        )
        db.add(voucher)
        await db.flush()

        # Link voucher to purchase
        purchase.voucher_code_id = voucher.id

        # Phase 5 (ADDITIVE): emit domain events via the transactional outbox in
        # the SAME transaction as the voucher/payment write. Best-effort and
        # fully guarded — if anything here raises it must NOT break provisioning,
        # and the rows are inert until NATS is configured. Subjects:
        #   isp.payment.received    — a customer payment completed
        #   isp.subscriber.created  — a hotspot subscriber/user was provisioned
        try:
            from app.events.outbox import record_event
            from app.events import EVT_PAYMENT_RECEIVED, EVT_SUBSCRIBER_CREATED

            tenant_uuid = str(organization.uuid) if organization.uuid else None

            # Customer-facing notification fields consumed by notifications-api.
            # Hotspot purchases collect only phone/email; derive a display name
            # from those (no separate name field on the purchase).
            customer_name = purchase.email or purchase.phone_number or hotspot_username

            # Access window expiry: online purchases are provisioned immediately
            # (voucher.used_at=now), so the access window starts now. Use the
            # plan's canonical access window (validity_days + time_limit aware) to
            # stay consistent with the expiry reconciler.
            try:
                _window_hours = plan.access_window_hours()
            except Exception:
                _window_hours = (plan.validity_days or 0) * 24
            expiry_at = (datetime.utcnow() + timedelta(hours=_window_hours)).isoformat()

            record_event(
                db,
                event_type=EVT_PAYMENT_RECEIVED,
                tenant_id=tenant_uuid,
                aggregate_id=str(purchase.id),
                payload={
                    "purchase_id": purchase.id,
                    "organization_id": organization.id,
                    "organization_slug": organization.slug,
                    "plan_id": plan.id,
                    "plan_name": plan.name,
                    "amount": str(purchase.amount),
                    "currency": purchase.currency,
                    "payment_method": purchase.payment_method,
                    "payment_reference": purchase.payment_reference,
                    "treasury_payment_intent_id": purchase.treasury_payment_intent_id,
                    "phone_number": purchase.phone_number,
                    "email": purchase.email,
                    "voucher_code": voucher_code,
                },
            )
            record_event(
                db,
                event_type=EVT_SUBSCRIBER_CREATED,
                tenant_id=tenant_uuid,
                aggregate_id=str(voucher.id),
                payload={
                    # tenant (ISP org) + identifiers
                    "tenant_id": tenant_uuid,
                    "organization_id": organization.id,
                    "organization_slug": organization.slug,
                    "voucher_id": voucher.id,
                    "voucher_code": voucher_code,
                    "purchase_id": purchase.id,
                    # customer + credentials (plaintext hotspot creds the customer needs)
                    "customer_name": customer_name,
                    "phone": purchase.phone_number,
                    "email": purchase.email,
                    "username": hotspot_username,
                    "password": hotspot_password,
                    # package + lifecycle
                    "plan_id": plan.id,
                    "package_name": plan.name,
                    "package_type": "hotspot",
                    "subscriber_type": "hotspot",
                    "expiry_at": expiry_at,
                    "amount": str(purchase.amount),
                    "currency": purchase.currency,
                },
            )
        except Exception as evt_exc:  # eventing must never break provisioning
            logger.warning("failed to record outbox events for purchase %s: %s", purchase.id, evt_exc)

        # Commit payment status and voucher first (critical data)
        await db.commit()

        logger.info(f"Generated voucher {voucher_code} with hotspot credentials {hotspot_username} for purchase {purchase.id}")

        # Create the hotspot user on the router (NAT-safe + best-effort; shared
        # helper queues via the agent for NATed routers, falls back to direct).
        # FAST CONNECT (Issue 1): this QUEUES create_user at payment-confirm time
        # (here), not at the connect screen, so the hotspot user exists on the
        # router before the device attempts to log in.
        await _sync_hotspot_user_to_router(
            db,
            organization,
            hotspot_username,
            hotspot_password,
            plan,
            source="voucher_purchase",
            source_id=str(purchase.id),
            comment=f"Purchased {plan.name} - Voucher {voucher_code}",
        )

        # Persist the queued create_user/set_limits commands NOW (queue_command only
        # flushes — it never commits). Doing this BEFORE the dashboard bridge means a
        # non-fatal bridge failure (which rolls back its own session) can never undo
        # the customer's router provisioning.
        await db.commit()

        # Issue 4 (FOUNDATION): mirror this hotspot PURCHASE into the dashboard's
        # data model (User + Subscription + Payment), so it surfaces on
        # Users/Customers/Expiry/analytics exactly like PPPoE. Idempotent + fully
        # guarded; runs for BOTH the NATS consumer and the poll fallback because
        # both call this shared routine. This is a DIRECT purchase (money moved via
        # treasury) so a Payment IS recorded.
        try:
            from app.services.hotspot_dashboard_bridge import (
                bridge_hotspot_purchase_to_dashboard,
            )

            _window_hours = plan.access_window_hours()
            await bridge_hotspot_purchase_to_dashboard(
                db,
                organization,
                plan,
                hotspot_username=hotspot_username,
                hotspot_password_hash=hotspot_password,
                expires_at=datetime.utcnow() + timedelta(hours=_window_hours),
                phone=purchase.phone_number,
                email=purchase.email,
                amount=purchase.amount,
                currency=purchase.currency,
                payment_reference=purchase.payment_reference,
                payment_method=purchase.payment_method or "treasury",
                is_voucher_redeem=False,
            )
        except Exception as bridge_exc:  # never break provisioning
            logger.error(
                "hotspot dashboard bridge failed for purchase %s (non-fatal): %s",
                purchase.id, bridge_exc,
            )

    except Exception as e:
        logger.error(f"Error processing successful payment for purchase {purchase.id}: {e}")
        # Still try to mark as completed so frontend stops polling
        try:
            purchase.payment_status = "completed"
            purchase.completed_at = datetime.utcnow()
            await db.commit()
        except Exception as commit_error:
            logger.error(f"Failed to commit payment status: {commit_error}")
            raise


@router.get("/{org_slug}/terms")
async def get_terms_and_conditions(
    org_slug: str,
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get organization's terms of service and privacy policy.

    Public endpoint - no authentication required.
    """
    return {
        "terms_of_service": organization.terms_of_service or "Terms of service not configured.",
        "privacy_policy": organization.privacy_policy or "Privacy policy not configured.",
    }
