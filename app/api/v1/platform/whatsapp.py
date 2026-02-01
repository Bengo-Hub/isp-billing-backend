"""
Platform WhatsApp Management API.

Endpoints for platform administrators to manage APIWAP gateway configuration,
view subscriptions, and monitor WhatsApp usage across all organizations.
"""

from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import require_platform_owner
from app.core.config import settings
from app.integrations.payment_gateways.factory import PaymentGatewayFactory
from app.models.user import User
from app.models.whatsapp import (
    WhatsAppGatewayConfig,
    WhatsAppProviderType,
    WhatsAppGatewayStatus,
    WhatsAppOrganizationSubscription,
    WhatsAppSubscriptionPackage,
    WhatsAppMessage,
    WhatsAppSubscriptionStatus,
    PlatformWhatsAppSettings,
)
from app.integrations.whatsapp import WhatsAppProviderFactory

router = APIRouter(prefix="/whatsapp", tags=["Platform - WhatsApp"])


# =========================================================================
# Schemas
# =========================================================================

class WhatsAppGatewayConfigResponse(BaseModel):
    """Schema for WhatsApp gateway configuration response."""

    id: int
    provider_type: str
    name: str
    description: Optional[str]
    status: str
    is_active: bool
    is_primary: bool
    environment: str
    webhook_url: Optional[str]
    total_messages: int
    total_cost: float
    last_message_at: Optional[str]
    last_error: Optional[str]
    created_at: str
    verified_at: Optional[str]

    # Don't expose credentials
    has_credentials: bool

    model_config = {"from_attributes": True}


class WhatsAppGatewayConfigCreate(BaseModel):
    """Schema for creating/updating WhatsApp gateway configuration."""

    api_key: str = Field(..., min_length=10, description="APIWAP API key")
    environment: str = Field(default="production", pattern="^(sandbox|production)$")
    webhook_url: Optional[str] = Field(None, max_length=500)


class WhatsAppGatewayTestRequest(BaseModel):
    """Schema for testing WhatsApp gateway."""

    phone_number: str = Field(default="+254743793901", pattern=r"^\+?[1-9]\d{1,14}$")
    test_message: str = Field(default="Test message from ISP Billing Platform")


class WhatsAppSubscriptionResponse(BaseModel):
    """Schema for WhatsApp subscription response."""

    id: int
    organization_id: int
    organization_name: str
    status: str
    provider_type: str
    start_date: str
    end_date: str
    next_billing_date: str
    is_trial: bool
    trial_end_date: Optional[str]
    messages_sent_this_month: int
    total_messages_sent: int
    monthly_fee: float = 500.00
    currency: str = "KES"

    model_config = {"from_attributes": True}


class WhatsAppAnalyticsResponse(BaseModel):
    """Schema for WhatsApp analytics response."""

    total_subscriptions: int
    active_subscriptions: int
    trial_subscriptions: int
    total_messages_this_month: int
    total_messages_all_time: int
    total_revenue_this_month: float
    total_revenue_all_time: float
    top_organizations: list
    messages_by_day: list


# =========================================================================
# Gateway Configuration Endpoints
# =========================================================================

@router.get("/gateway", response_model=Optional[WhatsAppGatewayConfigResponse])
async def get_whatsapp_gateway(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get platform-level APIWAP gateway configuration.

    Platform Admin only.
    """
    # Get platform-level gateway (organization_id = NULL)
    result = await db.execute(
        select(WhatsAppGatewayConfig).where(
            WhatsAppGatewayConfig.organization_id == None,
            WhatsAppGatewayConfig.provider_type == WhatsAppProviderType.APIWAP
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        return None

    return WhatsAppGatewayConfigResponse(
        id=gateway.id,
        provider_type=gateway.provider_type.value,
        name=gateway.name,
        description=gateway.description,
        status=gateway.status.value,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        environment=gateway.environment,
        webhook_url=gateway.webhook_url,
        total_messages=gateway.total_messages,
        total_cost=float(gateway.total_cost),
        last_message_at=gateway.last_message_at.isoformat() if gateway.last_message_at else None,
        last_error=gateway.last_error,
        created_at=gateway.created_at.isoformat(),
        verified_at=gateway.verified_at.isoformat() if gateway.verified_at else None,
        has_credentials=gateway.credentials is not None,
    )


@router.post("/gateway", response_model=WhatsAppGatewayConfigResponse)
async def save_whatsapp_gateway(
    data: WhatsAppGatewayConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create or update platform-level APIWAP gateway configuration.

    Platform Admin only.
    """
    import json
    from cryptography.fernet import Fernet
    import os

    # Get or create gateway
    result = await db.execute(
        select(WhatsAppGatewayConfig).where(
            WhatsAppGatewayConfig.organization_id == None,
            WhatsAppGatewayConfig.provider_type == WhatsAppProviderType.APIWAP
        )
    )
    gateway = result.scalar_one_or_none()

    # Encrypt credentials
    # Note: In production, use a proper encryption key from environment
    encryption_key = os.getenv("ENCRYPTION_KEY", Fernet.generate_key())
    if isinstance(encryption_key, str):
        encryption_key = encryption_key.encode()

    fernet = Fernet(encryption_key)
    credentials = {
        "api_key": data.api_key,
    }
    encrypted_credentials = fernet.encrypt(json.dumps(credentials).encode()).decode()

    if gateway:
        # Update existing
        gateway.credentials = encrypted_credentials
        gateway.environment = data.environment
        gateway.webhook_url = data.webhook_url
        gateway.status = WhatsAppGatewayStatus.PENDING_VERIFICATION
    else:
        # Create new
        gateway = WhatsAppGatewayConfig(
            organization_id=None,  # Platform-level
            provider_type=WhatsAppProviderType.APIWAP,
            name="APIWAP WhatsApp Gateway",
            description="Platform-managed APIWAP WhatsApp messaging for all ISP providers",
            status=WhatsAppGatewayStatus.PENDING_VERIFICATION,
            is_active=False,
            is_primary=True,
            environment=data.environment,
            credentials=encrypted_credentials,
            webhook_url=data.webhook_url,
            total_messages=0,
            total_cost=0,
        )
        db.add(gateway)

    await db.commit()
    await db.refresh(gateway)

    return WhatsAppGatewayConfigResponse(
        id=gateway.id,
        provider_type=gateway.provider_type.value,
        name=gateway.name,
        description=gateway.description,
        status=gateway.status.value,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        environment=gateway.environment,
        webhook_url=gateway.webhook_url,
        total_messages=gateway.total_messages,
        total_cost=float(gateway.total_cost),
        last_message_at=gateway.last_message_at.isoformat() if gateway.last_message_at else None,
        last_error=gateway.last_error,
        created_at=gateway.created_at.isoformat(),
        verified_at=gateway.verified_at.isoformat() if gateway.verified_at else None,
        has_credentials=True,
    )


@router.post("/gateway/test")
async def test_whatsapp_gateway(
    data: WhatsAppGatewayTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Test APIWAP gateway connection by sending a test message.

    Platform Admin only.
    """
    import json
    from cryptography.fernet import Fernet
    import os

    # Get gateway
    result = await db.execute(
        select(WhatsAppGatewayConfig).where(
            WhatsAppGatewayConfig.organization_id == None,
            WhatsAppGatewayConfig.provider_type == WhatsAppProviderType.APIWAP
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp gateway not configured"
        )

    if not gateway.credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gateway credentials not set"
        )

    # Decrypt credentials using the same method as SMS gateways
    encryption_key = getattr(settings, 'encryption_key', None)
    if encryption_key:
        try:
            credentials = PaymentGatewayFactory._decrypt_credentials(
                gateway.credentials, encryption_key
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt credentials: {str(e)}"
            )
    else:
        # Development mode - try plain JSON
        try:
            credentials = json.loads(gateway.credentials)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid credentials format: {str(e)}"
            )

    # Create provider instance and test
    try:
        provider = await WhatsAppProviderFactory.create(
            provider_type=WhatsAppProviderType.APIWAP.value,
            credentials=credentials
        )

        # Send test message
        result = await provider.send_message(
            to=data.phone_number,
            message=data.test_message,
            message_type="text"
        )

        if result.success:
            # Update gateway status
            gateway.status = WhatsAppGatewayStatus.ACTIVE
            gateway.is_active = True
            gateway.verified_at = datetime.utcnow()
            gateway.last_error = None
            await db.commit()

            return {
                "success": True,
                "message": "Test message sent successfully",
                "message_id": result.message_id,
                "recipient": result.recipient,
            }
        else:
            # Update error
            gateway.status = WhatsAppGatewayStatus.ERROR
            gateway.is_active = False
            gateway.last_error = result.message
            gateway.last_error_at = datetime.utcnow()
            await db.commit()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to send test message: {result.message}"
            )

    except Exception as e:
        # Update error
        gateway.status = WhatsAppGatewayStatus.ERROR
        gateway.is_active = False
        gateway.last_error = str(e)
        gateway.last_error_at = datetime.utcnow()
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gateway test failed: {str(e)}"
        )


@router.delete("/gateway")
async def delete_whatsapp_gateway(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Delete platform-level APIWAP gateway configuration.

    Platform Admin only.
    """
    # Get gateway
    result = await db.execute(
        select(WhatsAppGatewayConfig).where(
            WhatsAppGatewayConfig.organization_id == None,
            WhatsAppGatewayConfig.provider_type == WhatsAppProviderType.APIWAP
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp gateway not found"
        )

    await db.delete(gateway)
    await db.commit()

    return {
        "success": True,
        "message": "WhatsApp gateway deleted successfully"
    }


# =========================================================================
# Subscription Management Endpoints
# =========================================================================

@router.get("/subscriptions", response_model=list[WhatsAppSubscriptionResponse])
async def get_whatsapp_subscriptions(
    status: Optional[WhatsAppSubscriptionStatus] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get all WhatsApp subscriptions across all organizations.

    Platform Admin only.
    """
    from app.models.organization import Organization

    # Build query
    query = select(WhatsAppOrganizationSubscription, Organization).join(
        Organization,
        WhatsAppOrganizationSubscription.organization_id == Organization.id
    )

    if status:
        query = query.where(WhatsAppOrganizationSubscription.status == status)

    query = query.offset(skip).limit(limit).order_by(WhatsAppOrganizationSubscription.created_at.desc())

    result = await db.execute(query)
    subscriptions_with_orgs = result.all()

    return [
        WhatsAppSubscriptionResponse(
            id=sub.id,
            organization_id=sub.organization_id,
            organization_name=org.name,
            status=sub.status.value,
            provider_type=sub.provider_type.value,
            start_date=sub.start_date.isoformat(),
            end_date=sub.end_date.isoformat(),
            next_billing_date=sub.next_billing_date.isoformat(),
            is_trial=sub.is_trial,
            trial_end_date=sub.trial_end_date.isoformat() if sub.trial_end_date else None,
            messages_sent_this_month=sub.messages_sent_this_month,
            total_messages_sent=sub.total_messages_sent,
        )
        for sub, org in subscriptions_with_orgs
    ]


# =========================================================================
# Analytics Endpoints
# =========================================================================

@router.get("/analytics", response_model=WhatsAppAnalyticsResponse)
async def get_whatsapp_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get WhatsApp usage analytics across all organizations.

    Platform Admin only.
    """
    from app.models.organization import Organization

    # Total subscriptions
    total_subs_result = await db.execute(
        select(func.count(WhatsAppOrganizationSubscription.id))
    )
    total_subscriptions = total_subs_result.scalar() or 0

    # Active subscriptions
    active_subs_result = await db.execute(
        select(func.count(WhatsAppOrganizationSubscription.id)).where(
            WhatsAppOrganizationSubscription.status == WhatsAppSubscriptionStatus.ACTIVE
        )
    )
    active_subscriptions = active_subs_result.scalar() or 0

    # Trial subscriptions
    trial_subs_result = await db.execute(
        select(func.count(WhatsAppOrganizationSubscription.id)).where(
            WhatsAppOrganizationSubscription.is_trial == True,
            WhatsAppOrganizationSubscription.status == WhatsAppSubscriptionStatus.ACTIVE
        )
    )
    trial_subscriptions = trial_subs_result.scalar() or 0

    # Messages this month
    this_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    messages_this_month_result = await db.execute(
        select(func.count(WhatsAppMessage.id)).where(
            WhatsAppMessage.created_at >= this_month_start
        )
    )
    total_messages_this_month = messages_this_month_result.scalar() or 0

    # Messages all time
    messages_all_time_result = await db.execute(
        select(func.count(WhatsAppMessage.id))
    )
    total_messages_all_time = messages_all_time_result.scalar() or 0

    # Revenue this month (500 KES per active subscription)
    total_revenue_this_month = float(active_subscriptions * 500)

    # Revenue all time (estimate based on total subscriptions)
    total_revenue_all_time = float(total_subscriptions * 500)

    # Top organizations by message count
    top_orgs_result = await db.execute(
        select(
            Organization.name,
            func.count(WhatsAppMessage.id).label("message_count")
        ).join(
            WhatsAppMessage,
            Organization.id == WhatsAppMessage.organization_id
        ).group_by(
            Organization.id, Organization.name
        ).order_by(
            func.count(WhatsAppMessage.id).desc()
        ).limit(5)
    )
    top_organizations = [
        {"name": name, "message_count": count}
        for name, count in top_orgs_result.all()
    ]

    # Messages by day (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    messages_by_day_result = await db.execute(
        select(
            func.date(WhatsAppMessage.created_at).label("date"),
            func.count(WhatsAppMessage.id).label("count")
        ).where(
            WhatsAppMessage.created_at >= thirty_days_ago
        ).group_by(
            func.date(WhatsAppMessage.created_at)
        ).order_by(
            func.date(WhatsAppMessage.created_at)
        )
    )
    messages_by_day = [
        {"date": str(date), "count": count}
        for date, count in messages_by_day_result.all()
    ]

    return WhatsAppAnalyticsResponse(
        total_subscriptions=total_subscriptions,
        active_subscriptions=active_subscriptions,
        trial_subscriptions=trial_subscriptions,
        total_messages_this_month=total_messages_this_month,
        total_messages_all_time=total_messages_all_time,
        total_revenue_this_month=total_revenue_this_month,
        total_revenue_all_time=total_revenue_all_time,
        top_organizations=top_organizations,
        messages_by_day=messages_by_day,
    )


# =========================================================================
# WhatsApp Pricing & Payment Settings Endpoints
# =========================================================================

class PlatformWhatsAppSettingsCreate(BaseModel):
    """Schema for creating/updating platform WhatsApp pricing settings."""
    monthly_subscription_fee: float = Field(500.00, ge=0, description="Monthly subscription fee in platform currency")
    currency: str = Field("KES", max_length=3)
    minimum_subscription_months: int = Field(1, ge=1, description="Minimum subscription duration in months")
    payment_method: str = Field("paystack", description="Payment method for ISP subscriptions: mpesa, paystack, bank")
    mpesa_paybill: Optional[str] = None
    mpesa_till_number: Optional[str] = None
    mpesa_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    bank_swift_code: Optional[str] = None
    paystack_subaccount_code: Optional[str] = None
    trial_enabled: bool = Field(True, description="Enable trial period for new subscriptions")
    trial_days: int = Field(7, ge=0, description="Trial period duration in days")
    trial_message_limit: int = Field(50, ge=0, description="Message limit during trial")
    default_message_limit_per_month: Optional[int] = Field(None, description="Default monthly message limit (null = unlimited)")
    auto_renewal_enabled: bool = Field(True, description="Enable automatic renewal of subscriptions")
    auto_renewal_grace_days: int = Field(3, ge=0, description="Grace period for renewal in days")


class PlatformWhatsAppSettingsResponse(BaseModel):
    """Schema for platform WhatsApp settings response."""
    id: int
    monthly_subscription_fee: float
    currency: str
    minimum_subscription_months: int
    payment_method: str
    mpesa_paybill: Optional[str] = None
    mpesa_till_number: Optional[str] = None
    mpesa_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    bank_swift_code: Optional[str] = None
    paystack_subaccount_code: Optional[str] = None
    trial_enabled: bool
    trial_days: int
    trial_message_limit: int
    default_message_limit_per_month: Optional[int]
    auto_renewal_enabled: bool
    auto_renewal_grace_days: int
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("/settings/pricing", response_model=PlatformWhatsAppSettingsResponse)
async def get_platform_whatsapp_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get platform WhatsApp subscription pricing and payment settings.

    **Platform Owner only**.

    Returns the current WhatsApp subscription pricing configuration,
    including monthly fee and payment collection settings.
    """
    result = await db.execute(
        select(PlatformWhatsAppSettings).where(PlatformWhatsAppSettings.is_active == True)
    )
    settings_obj = result.scalar_one_or_none()

    if not settings_obj:
        # Return default settings if none exist
        return PlatformWhatsAppSettingsResponse(
            id=0,
            monthly_subscription_fee=500.00,
            currency="KES",
            minimum_subscription_months=1,
            payment_method="paystack",
            mpesa_paybill=None,
            mpesa_till_number=None,
            mpesa_account_name=None,
            bank_account_number=None,
            bank_name=None,
            bank_branch=None,
            bank_swift_code=None,
            paystack_subaccount_code=None,
            trial_enabled=True,
            trial_days=7,
            trial_message_limit=50,
            default_message_limit_per_month=None,
            auto_renewal_enabled=True,
            auto_renewal_grace_days=3,
            is_active=True,
        )

    return PlatformWhatsAppSettingsResponse(
        id=settings_obj.id,
        monthly_subscription_fee=float(settings_obj.monthly_subscription_fee),
        currency=settings_obj.currency,
        minimum_subscription_months=settings_obj.minimum_subscription_months,
        payment_method=settings_obj.payment_method,
        mpesa_paybill=settings_obj.mpesa_paybill,
        mpesa_till_number=settings_obj.mpesa_till_number,
        mpesa_account_name=settings_obj.mpesa_account_name,
        bank_account_number=settings_obj.bank_account_number,
        bank_name=settings_obj.bank_name,
        bank_branch=settings_obj.bank_branch,
        bank_swift_code=settings_obj.bank_swift_code,
        paystack_subaccount_code=settings_obj.paystack_subaccount_code,
        trial_enabled=settings_obj.trial_enabled,
        trial_days=settings_obj.trial_days,
        trial_message_limit=settings_obj.trial_message_limit,
        default_message_limit_per_month=settings_obj.default_message_limit_per_month,
        auto_renewal_enabled=settings_obj.auto_renewal_enabled,
        auto_renewal_grace_days=settings_obj.auto_renewal_grace_days,
        is_active=settings_obj.is_active,
    )


@router.post("/settings/pricing", response_model=PlatformWhatsAppSettingsResponse)
async def create_or_update_platform_whatsapp_settings(
    data: PlatformWhatsAppSettingsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create or update platform WhatsApp subscription pricing and payment settings.

    **Platform Owner only**.

    This defines how much ISP providers pay for WhatsApp subscription
    and where their payments are collected (M-PESA, Bank, or Paystack).
    """
    from decimal import Decimal

    # Check for existing settings
    result = await db.execute(
        select(PlatformWhatsAppSettings).where(PlatformWhatsAppSettings.is_active == True)
    )
    settings_obj = result.scalar_one_or_none()

    if settings_obj:
        # Update existing settings
        settings_obj.monthly_subscription_fee = Decimal(str(data.monthly_subscription_fee))
        settings_obj.currency = data.currency
        settings_obj.minimum_subscription_months = data.minimum_subscription_months
        settings_obj.payment_method = data.payment_method
        settings_obj.mpesa_paybill = data.mpesa_paybill
        settings_obj.mpesa_till_number = data.mpesa_till_number
        settings_obj.mpesa_account_name = data.mpesa_account_name
        settings_obj.bank_account_number = data.bank_account_number
        settings_obj.bank_name = data.bank_name
        settings_obj.bank_branch = data.bank_branch
        settings_obj.bank_swift_code = data.bank_swift_code
        settings_obj.paystack_subaccount_code = data.paystack_subaccount_code
        settings_obj.trial_enabled = data.trial_enabled
        settings_obj.trial_days = data.trial_days
        settings_obj.trial_message_limit = data.trial_message_limit
        settings_obj.default_message_limit_per_month = data.default_message_limit_per_month
        settings_obj.auto_renewal_enabled = data.auto_renewal_enabled
        settings_obj.auto_renewal_grace_days = data.auto_renewal_grace_days
    else:
        # Create new settings
        settings_obj = PlatformWhatsAppSettings(
            monthly_subscription_fee=Decimal(str(data.monthly_subscription_fee)),
            currency=data.currency,
            minimum_subscription_months=data.minimum_subscription_months,
            payment_method=data.payment_method,
            mpesa_paybill=data.mpesa_paybill,
            mpesa_till_number=data.mpesa_till_number,
            mpesa_account_name=data.mpesa_account_name,
            bank_account_number=data.bank_account_number,
            bank_name=data.bank_name,
            bank_branch=data.bank_branch,
            bank_swift_code=data.bank_swift_code,
            paystack_subaccount_code=data.paystack_subaccount_code,
            trial_enabled=data.trial_enabled,
            trial_days=data.trial_days,
            trial_message_limit=data.trial_message_limit,
            default_message_limit_per_month=data.default_message_limit_per_month,
            auto_renewal_enabled=data.auto_renewal_enabled,
            auto_renewal_grace_days=data.auto_renewal_grace_days,
            is_active=True,
        )
        db.add(settings_obj)

    await db.commit()
    await db.refresh(settings_obj)

    return PlatformWhatsAppSettingsResponse(
        id=settings_obj.id,
        monthly_subscription_fee=float(settings_obj.monthly_subscription_fee),
        currency=settings_obj.currency,
        minimum_subscription_months=settings_obj.minimum_subscription_months,
        payment_method=settings_obj.payment_method,
        mpesa_paybill=settings_obj.mpesa_paybill,
        mpesa_till_number=settings_obj.mpesa_till_number,
        mpesa_account_name=settings_obj.mpesa_account_name,
        bank_account_number=settings_obj.bank_account_number,
        bank_name=settings_obj.bank_name,
        bank_branch=settings_obj.bank_branch,
        bank_swift_code=settings_obj.bank_swift_code,
        paystack_subaccount_code=settings_obj.paystack_subaccount_code,
        trial_enabled=settings_obj.trial_enabled,
        trial_days=settings_obj.trial_days,
        trial_message_limit=settings_obj.trial_message_limit,
        default_message_limit_per_month=settings_obj.default_message_limit_per_month,
        auto_renewal_enabled=settings_obj.auto_renewal_enabled,
        auto_renewal_grace_days=settings_obj.auto_renewal_grace_days,
        is_active=settings_obj.is_active,
    )
