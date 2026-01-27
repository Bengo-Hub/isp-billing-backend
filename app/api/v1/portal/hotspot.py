"""
Hotspot Customer Portal API.

Public endpoints for hotspot customers to:
- View available packages
- Purchase packages via M-PESA
- Redeem voucher codes
- Check session status
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import get_organization_by_slug
from app.models.organization import Organization
from app.models.plan import ServicePlan, PlanType, PlanStatus
from app.models.customer_portal import VoucherCode, CustomerSession, CustomerPurchase, VoucherStatus, SessionStatus
from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
from app.integrations.payment_gateways import PaymentGatewayFactory

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
    phone_number: str = Field(..., pattern=r"^(\+?254|0)?[17]\d{8}$")
    email: Optional[str] = None


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


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/{org_slug}/config", response_model=PortalConfigResponse)
async def get_portal_config(
    org_slug: str,
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get portal configuration for an organization.

    Public endpoint - no authentication required.
    """
    # Get organization settings
    show_packages = True
    allow_guest = True

    if organization.settings:
        show_packages = organization.settings.show_packages_on_portal
        allow_guest = organization.settings.allow_guest_purchases

    return PortalConfigResponse(
        organization_name=organization.name,
        logo_url=organization.logo_url,
        primary_color=organization.primary_color,
        portal_title=organization.portal_title or organization.name,
        portal_description=organization.portal_description,
        show_packages=show_packages,
        allow_guest_purchases=allow_guest,
    )


@router.get("/{org_slug}/packages", response_model=List[PackageResponse])
async def get_packages(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Get available hotspot packages.

    Public endpoint - no authentication required.
    """
    result = await db.execute(
        select(ServicePlan)
        .where(
            ServicePlan.organization_id == organization.id,
            ServicePlan.plan_type.in_([PlanType.HOTSPOT, PlanType.BOTH]),
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


@router.post("/{org_slug}/purchase", response_model=PurchaseResponse)
async def purchase_package(
    org_slug: str,
    request: Request,
    data: PurchaseRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Purchase a hotspot package via M-PESA.

    Public endpoint - initiates STK push to customer's phone.
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

    # Get primary payment gateway
    gateway_result = await db.execute(
        select(PaymentGatewayConfig)
        .where(
            PaymentGatewayConfig.organization_id == organization.id,
            PaymentGatewayConfig.is_active == True,
            PaymentGatewayConfig.is_primary == True,
        )
    )
    gateway_config = gateway_result.scalar_one_or_none()

    if not gateway_config:
        # Try to get any active gateway
        gateway_result = await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.is_active == True,
            )
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

    # Initiate payment
    payment_result = await gateway.initiate_payment(
        amount=Decimal(str(plan.price)),
        phone_number=data.phone_number,
        reference=reference,
        description=f"{plan.name} - {organization.name}",
        metadata={
            "organization_id": organization.id,
            "plan_id": plan.id,
            "email": data.email,
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

    await db.commit()

    return VoucherRedeemResponse(
        success=True,
        message="Voucher redeemed successfully",
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
    payload: dict,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Payment callback webhook.

    Receives payment notifications from payment gateways.
    """
    # This would be called by the payment gateway
    # Process the callback and activate the customer's session

    # For now, return acknowledgment
    return {"status": "received"}
