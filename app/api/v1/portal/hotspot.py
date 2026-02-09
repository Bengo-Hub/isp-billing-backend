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
from decimal import Decimal
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
from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
from app.models.router import Router
from app.integrations.payment_gateways import PaymentGatewayFactory
from app.integrations.mikrotik import get_mikrotik_client
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


class VoucherRedeemRequest(BaseModel):
    """Schema for voucher redemption."""

    code: str = Field(..., min_length=4, max_length=50)
    mac_address: Optional[str] = None


class VoucherRedeemResponse(BaseModel):
    """Schema for voucher redemption response."""

    success: bool
    message: str
    plan_name: Optional[str] = None
    validity_hours: Optional[int] = None
    expires_at: Optional[datetime] = None


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

    return PortalConfigResponse(
        organization_name=organization.name,
        logo_url=organization.logo_url,
        primary_color=organization.primary_color,
        portal_title=organization.portal_title or organization.name,
        portal_description=organization.portal_description,
        show_packages=show_packages,
        allow_guest_purchases=allow_guest,
        redirect_url=redirect_url,
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


async def _sync_hotspot_user_to_router(
    db: AsyncSession,
    organization: Organization,
    username: str,
    password: str,
    plan: ServicePlan,
    mac_address: Optional[str],
    comment: str,
) -> Optional[str]:
    """
    Create / update a hotspot user on the org's MikroTik router with proper
    bandwidth, data and time limits derived from the plan.

    Returns the MikroTik login URL if sync succeeded, None otherwise.
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

    try:
        client = get_mikrotik_client()
        connection = await client.connect(
            ip_address=router_obj.ip_address,
            username=router_obj.username,
            password=router_obj.password,
            port=router_obj.port,
        )

        time_limit_seconds = plan.time_limit if plan.time_limit > 0 else None
        data_limit_bytes = None
        if plan.data_limit > 0 and not plan.is_unlimited_data:
            data_limit_bytes = plan.data_limit * 1024 * 1024  # MB → bytes

        await client.create_hotspot_user(
            connection=connection,
            username=username,
            password=password,
            profile="default",
            **{
                k: v
                for k, v in {
                    "limit-uptime": f"{time_limit_seconds}s" if time_limit_seconds else None,
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

        # Build MikroTik login URL
        login_url = (
            f"http://{router_obj.ip_address}/login"
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


@router.post("/{org_slug}/purchase", response_model=PurchaseResponse)
async def purchase_package(
    org_slug: str,
    request: Request,
    data: PurchaseRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Purchase a hotspot package via M-PESA or Paystack.

    Public endpoint - initiates payment based on selected method.
    """
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

    # Determine gateway type based on payment method
    requested_gateway_type = None
    if data.payment_method == "paystack":
        requested_gateway_type = GatewayType.PAYSTACK
    elif data.payment_method == "mpesa":
        requested_gateway_type = GatewayType.MPESA

    # Get payment gateway based on requested method
    gateway_config = None
    if requested_gateway_type:
        gateway_result = await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.gateway_type == requested_gateway_type,
                PaymentGatewayConfig.is_active == True,
            )
            .limit(1)
        )
        gateway_config = gateway_result.scalar_one_or_none()

    # Fallback to primary gateway if requested gateway not found
    if not gateway_config:
        gateway_result = await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.is_active == True,
                PaymentGatewayConfig.is_primary == True,
            )
        )
        gateway_config = gateway_result.scalar_one_or_none()

    # Try any active gateway for this organization as last resort
    if not gateway_config:
        gateway_result = await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.is_active == True,
            )
            .limit(1)
        )
        gateway_config = gateway_result.scalar_one_or_none()

    # Fallback to platform-level gateway if no org-level gateway found
    if not gateway_config and requested_gateway_type:
        gateway_result = await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id.is_(None),
                PaymentGatewayConfig.gateway_type == requested_gateway_type,
                PaymentGatewayConfig.is_active == True,
            )
            .limit(1)
        )
        gateway_config = gateway_result.scalar_one_or_none()

    # Fallback to any active platform-level gateway
    if not gateway_config:
        gateway_result = await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id.is_(None),
                PaymentGatewayConfig.is_active == True,
            )
            .order_by(PaymentGatewayConfig.is_primary.desc())
            .limit(1)
        )
        gateway_config = gateway_result.scalar_one_or_none()

    if not gateway_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No payment method configured"
        )

    # Create payment gateway
    try:
        gateway = PaymentGatewayFactory.create(gateway_config)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment gateway configuration error"
        )

    # Generate reference
    import uuid
    reference = f"HS-{organization.slug[:6].upper()}-{uuid.uuid4().hex[:8].upper()}"

    # Get client IP and user agent
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Create purchase record
    purchase = CustomerPurchase(
        organization_id=organization.id,
        phone_number=data.phone_number,
        email=data.email,
        plan_id=plan.id,
        amount=plan.price,
        currency=plan.currency,
        payment_method=gateway_config.gateway_type.value,
        payment_reference=reference,
        payment_status="pending",
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.add(purchase)
    await db.commit()

    # Build callback URL for Paystack with payment type context
    callback_url = None
    if gateway_config.gateway_type == GatewayType.PAYSTACK:
        # Use the request origin for callback
        origin = request.headers.get("origin", "")
        if origin:
            callback_url = f"{origin}/payment/callback?payment_type=hotspot_purchase&org={org_slug}"

    # Initiate payment
    payment_result = await gateway.initiate_payment(
        amount=Decimal(str(plan.price)),
        phone_number=data.phone_number or "",
        reference=reference,
        description=f"{plan.name} - {organization.name}",
        callback_url=callback_url,
        metadata={
            "organization_id": organization.id,
            "plan_id": plan.id,
            "purchase_id": purchase.id,
            "email": data.email,
            "phone_number": data.phone_number,
        },
    )

    # Update purchase with gateway response
    purchase.payment_status = "processing" if payment_result.success else "failed"
    await db.commit()

    if payment_result.success:
        return PurchaseResponse(
            success=True,
            reference=reference,
            message=payment_result.message or "Payment request sent",
            instructions=payment_result.instructions,
            checkout_url=payment_result.checkout_url,
            status="pending",
        )
    else:
        return PurchaseResponse(
            success=False,
            reference=reference,
            message=payment_result.message or "Payment failed",
            status="failed",
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

    # Calculate session expiry
    validity_hours = plan.validity_days * 24
    if plan.time_limit > 0:
        validity_hours = min(validity_hours, plan.time_limit)

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

    # Sync user to MikroTik router if available
    from app.models.router import Router
    from app.modules.routers.mikrotik import get_mikrotik_client

    router_result = await db.execute(
        select(Router).where(
            Router.organization_id == organization.id,
            Router.is_active == True,
        ).limit(1)
    )
    router = router_result.scalar_one_or_none()

    if router and voucher.hotspot_username and voucher.hotspot_password:
        try:
            # Connect to router
            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )

            # Use plan's time_limit (in seconds) if set, otherwise unlimited
            time_limit_seconds = plan.time_limit if plan.time_limit > 0 else None

            # Calculate data limit in bytes (plan.data_limit is in MB)
            data_limit_bytes = None
            if plan.data_limit > 0 and not plan.is_unlimited_data:
                data_limit_bytes = plan.data_limit * 1024 * 1024  # MB to bytes

            # Create or update hotspot user with limits
            await client.create_hotspot_user(
                connection=connection,
                username=voucher.hotspot_username,
                password=voucher.hotspot_password,
                profile="default",
                **{
                    "limit-uptime": f"{time_limit_seconds}s" if time_limit_seconds else None,
                    "limit-bytes-total": data_limit_bytes if data_limit_bytes else None,
                    "comment": f"Redeemed voucher {voucher.code} - {plan.name}",
                }
            )

            await client.disconnect(router.ip_address, router.port)

            logger.info(
                f"Synced hotspot user {voucher.hotspot_username} to router {router.name} "
                f"on voucher redemption {voucher.code}"
            )
        except Exception as e:
            logger.error(
                f"Failed to sync hotspot user {voucher.hotspot_username} to router {router.name}: {e}. "
                f"User may need to reconnect or authenticate manually."
            )
            # Don't fail voucher redemption if router sync fails
    else:
        if not router:
            logger.warning(
                f"No active router found for organization {organization.id}. "
                f"Hotspot user not synced to router."
            )
        else:
            logger.warning(
                f"Voucher {voucher.code} missing hotspot credentials. "
                f"Cannot sync to router."
            )

    await db.commit()

    return VoucherRedeemResponse(
        success=True,
        message="Voucher redeemed successfully. You can now connect to the internet.",
        plan_name=plan.name,
        validity_hours=validity_hours,
        expires_at=expires_at,
    )


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
    Payment callback webhook.

    Receives payment notifications from payment gateways and activates customer sessions.
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

    # If payment is still processing, try to verify with gateway (webhook fallback)
    if purchase.payment_status == "processing":
        try:
            # Get the gateway that was used for this purchase
            gateway_result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
                    PaymentGatewayConfig.is_active == True,
                )
            )
            gateway_config = gateway_result.scalar_one_or_none()

            if gateway_config:
                gateway = PaymentGatewayFactory.create(gateway_config)
                verification = await gateway.verify_payment(reference)

                if verification.success and verification.status == "success":
                    # Payment was successful! Process it now
                    logger.info(f"Manual verification successful for reference {reference}, processing payment")
                    await _process_successful_payment(db, purchase, organization)

                elif verification.status in ["failed", "abandoned"]:
                    purchase.payment_status = "failed"
                    await db.commit()

        except Exception as e:
            logger.error(f"Error verifying payment {reference}: {e}")
            # Continue with current status if verification fails

    # Check if payment is completed
    is_completed = purchase.payment_status in ["completed", "failed"]
    is_success = purchase.payment_status == "completed"

    response = {
        "status": purchase.payment_status,
        "is_completed": is_completed,
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
            status=VoucherStatus.ACTIVE,
            value=purchase.amount,
            expires_at=datetime.utcnow() + timedelta(days=30),  # Voucher valid for 30 days
            hotspot_username=hotspot_username,
            hotspot_password=hotspot_password,
        )
        db.add(voucher)
        await db.flush()

        # Link voucher to purchase
        purchase.voucher_code_id = voucher.id

        # Commit payment status and voucher first (critical data)
        await db.commit()

        logger.info(f"Generated voucher {voucher_code} with hotspot credentials {hotspot_username} for purchase {purchase.id}")

        # Create MikroTik hotspot user on the router (non-critical, best effort)
        try:
            router_result = await db.execute(
                select(Router).where(
                    Router.organization_id == organization.id,
                    Router.is_active == True,
                ).limit(1)
            )
            router = router_result.scalar_one_or_none()

            if router:
                # Connect to router and create hotspot user
                client = get_mikrotik_client()
                connection = await client.connect(
                    ip_address=router.ip_address,
                    username=router.username,
                    password=router.password,
                    port=router.port,
                )

                # Calculate time limit in seconds (validity_days * 24 hours * 3600 seconds)
                time_limit_seconds = plan.validity_days * 24 * 3600 if plan.validity_days > 0 else 0

                # Create hotspot user with bandwidth and time limits
                await client.create_hotspot_user(
                    connection=connection,
                    username=hotspot_username,
                    password=hotspot_password,
                    profile="default",
                    **{
                        "limit-uptime": f"{time_limit_seconds}s" if time_limit_seconds > 0 else None,
                        "limit-bytes-total": plan.data_limit * 1024 * 1024 * 1024 if plan.data_limit > 0 and not plan.is_unlimited_data else None,
                        "comment": f"Purchased {plan.name} - Voucher {voucher_code}",
                    }
                )

                await client.disconnect(router.ip_address, router.port)

                logger.info(
                    f"Created MikroTik hotspot user {hotspot_username} on router {router.name} "
                    f"for purchase {purchase.id}"
                )
            else:
                logger.warning(
                    f"No active router found for organization {organization.id}. "
                    f"Hotspot user {hotspot_username} not created on router."
                )
        except Exception as e:
            logger.error(
                f"Failed to create hotspot user {hotspot_username} on router: {e}. "
                f"User can still redeem voucher manually."
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
