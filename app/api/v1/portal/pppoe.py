"""
PPPoE Customer Portal API.

Endpoints for PPPoE customers to:
- Login to their dashboard
- View usage statistics
- View payment history
- Renew subscriptions
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.api.deps_tenant import get_organization_by_slug
from app.core.security import create_access_token, verify_password
from app.models.organization import Organization
from app.models.user import User, UserRole, UserStatus
from app.models.plan import ServicePlan, PlanType
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionUsageLog
from app.models.billing import Payment, PaymentStatus

router = APIRouter(prefix="/pppoe", tags=["Portal - PPPoE"])


# =========================================================================
# Schemas
# =========================================================================

class CustomerLoginRequest(BaseModel):
    """Schema for customer login."""

    username: str
    password: str


class CustomerLoginResponse(BaseModel):
    """Schema for login response."""

    access_token: str
    token_type: str = "bearer"
    customer: dict


class CustomerDashboard(BaseModel):
    """Schema for customer dashboard."""

    customer_name: str
    email: Optional[str]
    phone: Optional[str]
    current_plan: Optional[dict]
    subscription_status: Optional[str]
    expires_at: Optional[datetime]
    days_remaining: Optional[int]
    usage_this_month: dict
    quick_stats: dict


class UsageData(BaseModel):
    """Schema for usage data."""

    date: str
    download_gb: float
    upload_gb: float
    total_gb: float


class UsageResponse(BaseModel):
    """Schema for usage response."""

    current_month_download_gb: float
    current_month_upload_gb: float
    current_month_total_gb: float
    data_limit_gb: Optional[float]
    usage_percentage: Optional[float]
    daily_usage: List[UsageData]


class PaymentHistory(BaseModel):
    """Schema for payment history."""

    id: int
    payment_number: str
    amount: float
    currency: str
    payment_method: str
    status: str
    payment_date: Optional[datetime]
    created_at: datetime


class AvailablePackage(BaseModel):
    """Schema for available package."""

    id: int
    name: str
    description: Optional[str]
    price: float
    currency: str
    validity_days: int
    download_speed: int
    upload_speed: int
    data_limit: Optional[int]
    is_current: bool


class RenewalRequest(BaseModel):
    """Schema for renewal request."""

    plan_id: int
    phone_number: str = Field(..., pattern=r"^(\+?254|0)?[17]\d{8}$")


class RenewalResponse(BaseModel):
    """Schema for renewal response."""

    success: bool
    reference: str
    message: str
    checkout_url: Optional[str] = None


# =========================================================================
# Endpoints
# =========================================================================

@router.post("/{org_slug}/login", response_model=CustomerLoginResponse)
async def customer_login(
    org_slug: str,
    data: CustomerLoginRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
):
    """
    Customer login for PPPoE dashboard.

    Returns access token for authenticated requests.
    """
    # Find user by username within organization
    result = await db.execute(
        select(User).where(
            User.organization_id == organization.id,
            User.role == UserRole.CUSTOMER,
            User.username == data.username,
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active"
        )

    # Create access token
    token = create_access_token(
        data={
            "sub": str(user.id),
            "organization_id": organization.id,
            "role": user.role.value,
        }
    )

    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()

    return CustomerLoginResponse(
        access_token=token,
        customer={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
        },
    )


@router.get("/{org_slug}/dashboard")
async def get_dashboard(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
):
    """
    Get customer dashboard data.

    Includes current plan, subscription status, and quick stats.
    """
    # Get user
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization.id,
            User.role == UserRole.CUSTOMER,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Get active subscription
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.user_id == user.id,
            Subscription.organization_id == organization.id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING]),
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()

    current_plan = None
    subscription_status = None
    expires_at = None
    days_remaining = None

    if subscription:
        subscription_status = subscription.status.value
        expires_at = subscription.end_date

        if subscription.end_date:
            days_remaining = max(0, (subscription.end_date - datetime.utcnow()).days)

        if subscription.plan:
            current_plan = {
                "id": subscription.plan.id,
                "name": subscription.plan.name,
                "price": float(subscription.plan.price),
                "download_speed": subscription.plan.download_speed,
                "upload_speed": subscription.plan.upload_speed,
                "data_limit": subscription.plan.data_limit,
            }

    # Get usage this month
    first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    usage_result = await db.execute(
        select(
            func.sum(SubscriptionUsageLog.bytes_downloaded),
            func.sum(SubscriptionUsageLog.bytes_uploaded),
        ).where(
            SubscriptionUsageLog.subscription_id == subscription.id if subscription else -1,
            SubscriptionUsageLog.log_date >= first_of_month,
        )
    )
    usage_row = usage_result.one()

    download_bytes = usage_row[0] or 0
    upload_bytes = usage_row[1] or 0

    usage_this_month = {
        "download_gb": round(download_bytes / (1024 ** 3), 2),
        "upload_gb": round(upload_bytes / (1024 ** 3), 2),
        "total_gb": round((download_bytes + upload_bytes) / (1024 ** 3), 2),
    }

    # Quick stats
    payment_count = await db.execute(
        select(func.count(Payment.id)).where(
            Payment.user_id == user.id,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    total_payments = payment_count.scalar() or 0

    total_spent = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.user_id == user.id,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    spent = total_spent.scalar() or 0

    quick_stats = {
        "total_payments": total_payments,
        "total_spent": float(spent),
        "member_since": user.created_at.strftime("%B %Y") if user.created_at else None,
    }

    return CustomerDashboard(
        customer_name=user.full_name,
        email=user.email,
        phone=user.phone,
        current_plan=current_plan,
        subscription_status=subscription_status,
        expires_at=expires_at,
        days_remaining=days_remaining,
        usage_this_month=usage_this_month,
        quick_stats=quick_stats,
    )


@router.get("/{org_slug}/usage", response_model=UsageResponse)
async def get_usage(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
    days: int = Query(30, ge=7, le=90),
):
    """
    Get detailed usage data.

    Includes daily breakdown and current month totals.
    """
    # Get active subscription
    sub_result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(
            Subscription.user_id == user_id,
            Subscription.organization_id == organization.id,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found"
        )

    # Get usage logs
    start_date = datetime.utcnow() - timedelta(days=days)

    usage_result = await db.execute(
        select(
            func.date(SubscriptionUsageLog.log_date),
            func.sum(SubscriptionUsageLog.bytes_downloaded),
            func.sum(SubscriptionUsageLog.bytes_uploaded),
        )
        .where(
            SubscriptionUsageLog.subscription_id == subscription.id,
            SubscriptionUsageLog.log_date >= start_date,
        )
        .group_by(func.date(SubscriptionUsageLog.log_date))
        .order_by(func.date(SubscriptionUsageLog.log_date))
    )

    daily_usage = []
    for row in usage_result.all():
        download_gb = (row[1] or 0) / (1024 ** 3)
        upload_gb = (row[2] or 0) / (1024 ** 3)
        daily_usage.append(UsageData(
            date=row[0].isoformat() if row[0] else "",
            download_gb=round(download_gb, 2),
            upload_gb=round(upload_gb, 2),
            total_gb=round(download_gb + upload_gb, 2),
        ))

    # Current month totals
    first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_result = await db.execute(
        select(
            func.sum(SubscriptionUsageLog.bytes_downloaded),
            func.sum(SubscriptionUsageLog.bytes_uploaded),
        ).where(
            SubscriptionUsageLog.subscription_id == subscription.id,
            SubscriptionUsageLog.log_date >= first_of_month,
        )
    )
    month_row = month_result.one()

    download_gb = (month_row[0] or 0) / (1024 ** 3)
    upload_gb = (month_row[1] or 0) / (1024 ** 3)
    total_gb = download_gb + upload_gb

    # Calculate usage percentage
    data_limit_gb = None
    usage_percentage = None

    if subscription.plan and subscription.plan.data_limit > 0:
        data_limit_gb = subscription.plan.data_limit
        usage_percentage = (total_gb / data_limit_gb) * 100

    return UsageResponse(
        current_month_download_gb=round(download_gb, 2),
        current_month_upload_gb=round(upload_gb, 2),
        current_month_total_gb=round(total_gb, 2),
        data_limit_gb=data_limit_gb,
        usage_percentage=round(usage_percentage, 1) if usage_percentage else None,
        daily_usage=daily_usage,
    )


@router.get("/{org_slug}/payments", response_model=List[PaymentHistory])
async def get_payments(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get payment history.
    """
    result = await db.execute(
        select(Payment)
        .where(
            Payment.user_id == user_id,
            Payment.organization_id == organization.id,
        )
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    payments = list(result.scalars().all())

    return [
        PaymentHistory(
            id=p.id,
            payment_number=p.payment_number,
            amount=float(p.amount),
            currency=p.currency,
            payment_method=p.payment_method.value if p.payment_method else "unknown",
            status=p.status.value if p.status else "unknown",
            payment_date=p.payment_date,
            created_at=p.created_at,
        )
        for p in payments
    ]


@router.get("/{org_slug}/packages", response_model=List[AvailablePackage])
async def get_available_packages(
    org_slug: str,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: Optional[int] = Query(None, description="Customer user ID"),
):
    """
    Get available PPPoE packages.
    """
    # Get current subscription plan ID
    current_plan_id = None
    if user_id:
        sub_result = await db.execute(
            select(Subscription.plan_id)
            .where(
                Subscription.user_id == user_id,
                Subscription.organization_id == organization.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .limit(1)
        )
        row = sub_result.one_or_none()
        if row:
            current_plan_id = row[0]

    # Get available plans
    result = await db.execute(
        select(ServicePlan)
        .where(
            ServicePlan.organization_id == organization.id,
            ServicePlan.plan_type.in_([PlanType.PPPOE, PlanType.BOTH]),
            ServicePlan.status == "active",
        )
        .order_by(ServicePlan.sort_order, ServicePlan.price)
    )
    plans = list(result.scalars().all())

    return [
        AvailablePackage(
            id=p.id,
            name=p.name,
            description=p.description,
            price=float(p.price),
            currency=p.currency,
            validity_days=p.validity_days,
            download_speed=p.download_speed,
            upload_speed=p.upload_speed,
            data_limit=p.data_limit if p.data_limit > 0 else None,
            is_current=p.id == current_plan_id,
        )
        for p in plans
    ]


@router.post("/{org_slug}/renew", response_model=RenewalResponse)
async def renew_subscription(
    org_slug: str,
    data: RenewalRequest,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_by_slug),
    user_id: int = Query(..., description="Customer user ID"),
):
    """
    Renew subscription with a new or same plan.

    Initiates payment via M-PESA.
    """
    # Get plan
    plan_result = await db.execute(
        select(ServicePlan).where(
            ServicePlan.id == data.plan_id,
            ServicePlan.organization_id == organization.id,
        )
    )
    plan = plan_result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Package not found"
        )

    # Get payment gateway
    from app.models.payment_gateway import PaymentGatewayConfig

    gateway_result = await db.execute(
        select(PaymentGatewayConfig)
        .where(
            PaymentGatewayConfig.organization_id == organization.id,
            PaymentGatewayConfig.is_active == True,
        )
        .order_by(PaymentGatewayConfig.is_primary.desc())
        .limit(1)
    )
    gateway_config = gateway_result.scalar_one_or_none()

    if not gateway_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No payment method available"
        )

    # Create gateway and initiate payment
    from app.integrations.payment_gateways import PaymentGatewayFactory
    import uuid

    gateway = PaymentGatewayFactory.create(gateway_config)
    reference = f"PPP-{organization.slug[:6].upper()}-{uuid.uuid4().hex[:8].upper()}"

    result = await gateway.initiate_payment(
        amount=Decimal(str(plan.price)),
        phone_number=data.phone_number,
        reference=reference,
        description=f"Renewal - {plan.name}",
        metadata={
            "organization_id": organization.id,
            "user_id": user_id,
            "plan_id": plan.id,
            "type": "renewal",
        },
    )

    return RenewalResponse(
        success=result.success,
        reference=reference,
        message=result.message or ("Payment request sent" if result.success else "Payment failed"),
        checkout_url=result.checkout_url,
    )
