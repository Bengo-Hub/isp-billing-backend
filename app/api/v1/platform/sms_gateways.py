"""
Platform SMS Gateway Configuration API.

Endpoints for Platform Owners to configure platform-level SMS gateways.
These gateways handle SMS sending for the entire platform (notifications,
verification codes, alerts, etc.).

Access Control:
- Platform Owner only: Full access to create, update, delete, and test gateways
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_active_user
from app.core.config import settings
from app.models.user import User, UserRole
from app.models.sms_credit import SMSGatewayConfig, SMSProviderType, SMSGatewayStatus, PlatformSMSSettings
from app.utils.credentials import encrypt_credentials, decrypt_credentials

router = APIRouter(prefix="/sms-gateways", tags=["Platform - SMS Gateways"])


# =========================================================================
# Dependencies
# =========================================================================

async def require_platform_owner(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Require platform owner role."""
    if current_user.role != UserRole.PLATFORM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform owner access required",
        )
    return current_user


# =========================================================================
# Schemas
# =========================================================================

class TwilioCredentials(BaseModel):
    """Schema for Twilio credentials."""
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None  # Phone number in E.164 format
    messaging_service_sid: Optional[str] = None  # Optional for advanced routing


class AfricasTalkingCredentials(BaseModel):
    """Schema for Africa's Talking credentials."""
    username: Optional[str] = None
    api_key: Optional[str] = None
    sender_id: Optional[str] = None  # Alphanumeric sender ID


class SMSGatewayCredentials(BaseModel):
    """Schema for SMS gateway credentials."""
    # Twilio fields
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None
    messaging_service_sid: Optional[str] = None

    # Africa's Talking fields
    username: Optional[str] = None
    api_key: Optional[str] = None
    sender_id: Optional[str] = None

    # Common field for sandbox mode
    is_sandbox: Optional[bool] = False


class PlatformSMSGatewayCreate(BaseModel):
    """Schema for creating a platform SMS gateway."""
    provider_type: SMSProviderType
    name: str = Field(..., min_length=1, max_length=100)
    is_active: bool = True
    is_primary: bool = False
    environment: str = "sandbox"  # sandbox or production
    credentials: SMSGatewayCredentials


class PlatformSMSGatewayUpdate(BaseModel):
    """Schema for updating a platform SMS gateway."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    is_primary: Optional[bool] = None
    environment: Optional[str] = None
    credentials: Optional[SMSGatewayCredentials] = None


class PlatformSMSGatewayResponse(BaseModel):
    """Schema for platform SMS gateway response."""
    id: int
    provider_type: str
    name: str
    is_active: bool
    is_primary: bool
    environment: str
    has_credentials: bool
    status: str
    last_error: Optional[str] = None

    model_config = {"from_attributes": True}


class TestConnectionResponse(BaseModel):
    """Schema for test connection response."""
    success: bool
    message: str
    details: Optional[dict] = None


class PlatformSMSBalanceResponse(BaseModel):
    """Response for platform SMS gateway balance."""
    success: bool
    balance: float
    currency: str
    provider: str
    environment: str
    message: Optional[str] = None


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/", response_model=List[PlatformSMSGatewayResponse])
async def list_platform_sms_gateways(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    List all platform-level SMS gateways.

    Platform Owner only. These gateways handle SMS for the entire platform.
    """
    # Platform-level gateways have organization_id = NULL
    result = await db.execute(
        select(SMSGatewayConfig)
        .where(SMSGatewayConfig.organization_id.is_(None))
        .order_by(SMSGatewayConfig.is_primary.desc(), SMSGatewayConfig.name)
    )
    gateways = list(result.scalars().all())

    return [
        PlatformSMSGatewayResponse(
            id=g.id,
            provider_type=g.provider_type.value,
            name=g.name,
            is_active=g.is_active,
            is_primary=g.is_primary,
            environment=g.environment or "sandbox",
            has_credentials=bool(g.credentials),
            status=g.status.value if g.status else "pending_verification",
            last_error=g.last_error,
        )
        for g in gateways
    ]


@router.get("/balance", response_model=PlatformSMSBalanceResponse)
async def get_platform_sms_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get the actual SMS provider account balance.

    Platform Owner only. Returns the real-time balance from the primary
    SMS gateway (e.g., Africa's Talking account balance).
    """
    # Get primary active gateway
    result = await db.execute(
        select(SMSGatewayConfig).where(
            SMSGatewayConfig.organization_id.is_(None),
            SMSGatewayConfig.is_active == True,
            SMSGatewayConfig.is_primary == True,
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        # Try any active gateway
        result = await db.execute(
            select(SMSGatewayConfig).where(
                SMSGatewayConfig.organization_id.is_(None),
                SMSGatewayConfig.is_active == True,
            )
        )
        gateway = result.scalar_one_or_none()

    if not gateway:
        return PlatformSMSBalanceResponse(
            success=False,
            balance=0,
            currency="KES",
            provider="none",
            environment="unknown",
            message="No SMS gateway configured",
        )

    if not gateway.credentials:
        return PlatformSMSBalanceResponse(
            success=False,
            balance=0,
            currency="KES",
            provider=gateway.provider_type.value,
            environment=gateway.environment or "sandbox",
            message="Gateway credentials not configured",
        )

    # SMS DELIVERY (and provider balance) is owned by the central notifications-api.
    # isp-billing no longer ships a local SMS provider, so a live provider balance
    # lookup is not available here. We validate that the stored credentials are
    # well-formed and report that balance lives upstream.
    try:
        decrypt_credentials(gateway.credentials)
    except Exception as e:
        return PlatformSMSBalanceResponse(
            success=False,
            balance=0,
            currency="KES",
            provider=gateway.provider_type.value,
            environment=gateway.environment or "sandbox",
            message=f"Invalid stored credentials: {e}",
        )

    return PlatformSMSBalanceResponse(
        success=True,
        balance=0,
        currency="KES",
        provider=gateway.provider_type.value,
        environment=gateway.environment or "sandbox",
        message="SMS delivery and balance are managed by the central notifications-api",
    )


@router.get("/providers")
async def list_sms_providers(
    current_user: User = Depends(require_platform_owner),
):
    """
    Get list of supported SMS providers and their required fields.

    Platform Owner only.
    """
    return {
        "providers": [
            {
                "type": "twilio",
                "name": "Twilio",
                "description": "Global SMS coverage with excellent deliverability",
                "required_fields": ["account_sid", "auth_token", "from_number"],
                "optional_fields": ["messaging_service_sid"],
                "supports_sandbox": True,
            },
            {
                "type": "africastalking",
                "name": "Africa's Talking",
                "description": "SMS coverage across African markets with local numbers",
                "required_fields": ["username", "api_key"],
                "optional_fields": ["sender_id"],
                "supports_sandbox": True,
            },
        ]
    }


@router.post("/", response_model=PlatformSMSGatewayResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_sms_gateway(
    data: PlatformSMSGatewayCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create or update a platform-level SMS gateway.

    Platform Owner only. This gateway will handle SMS for the entire platform.
    If a gateway of this provider type already exists, it will be updated (upsert).
    """
    # Check if gateway of this provider type already exists at platform level
    result = await db.execute(
        select(SMSGatewayConfig).where(
            SMSGatewayConfig.organization_id.is_(None),
            SMSGatewayConfig.provider_type == data.provider_type,
        )
    )
    existing = result.scalar_one_or_none()

    # Build credentials dict and add is_sandbox based on environment
    credentials_dict = data.credentials.model_dump(exclude_none=True) if data.credentials else {}
    credentials_dict["is_sandbox"] = data.environment == "sandbox"

    # Encrypt credentials
    encrypted_credentials = encrypt_credentials(credentials_dict)

    if existing:
        # Update existing gateway (upsert behavior)
        existing.name = data.name
        existing.is_active = data.is_active
        existing.environment = data.environment
        existing.credentials = encrypted_credentials
        existing.status = SMSGatewayStatus.PENDING_VERIFICATION

        if data.is_primary and not existing.is_primary:
            # Unset other primary gateways
            result = await db.execute(
                select(SMSGatewayConfig).where(
                    SMSGatewayConfig.organization_id.is_(None),
                    SMSGatewayConfig.is_primary == True,
                    SMSGatewayConfig.id != existing.id,
                )
            )
            for g in result.scalars().all():
                g.is_primary = False
            existing.is_primary = True

        await db.commit()
        await db.refresh(existing)
        gateway = existing
    else:
        # Create new gateway (organization_id = None for platform-level)
        gateway = SMSGatewayConfig(
            organization_id=None,  # Platform-level gateway
            provider_type=data.provider_type,
            name=data.name,
            is_active=data.is_active,
            is_primary=data.is_primary,
            environment=data.environment,
            credentials=encrypted_credentials,
            status=SMSGatewayStatus.PENDING_VERIFICATION,
        )

        # If setting as primary, unset other primary gateways
        if data.is_primary:
            result = await db.execute(
                select(SMSGatewayConfig).where(
                    SMSGatewayConfig.organization_id.is_(None),
                    SMSGatewayConfig.is_primary == True,
                )
            )
            for existing_gateway in result.scalars().all():
                existing_gateway.is_primary = False

        db.add(gateway)
        await db.commit()
        await db.refresh(gateway)

    return PlatformSMSGatewayResponse(
        id=gateway.id,
        provider_type=gateway.provider_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        environment=gateway.environment or "sandbox",
        has_credentials=bool(gateway.credentials),
        status=gateway.status.value if gateway.status else "pending_verification",
        last_error=gateway.last_error,
    )


# =========================================================================
# ISP SMS Purchases Overview (Platform Admin View)
# =========================================================================

class ISPSMSPurchaseItem(BaseModel):
    """Single ISP SMS purchase record."""
    id: int
    organization_id: int
    organization_name: str
    amount: float
    sms_credits: int
    status: str
    payment_reference: Optional[str] = None
    purchased_at: str
    current_balance: float


class ISPSMSPurchasesResponse(BaseModel):
    """Response for ISP SMS purchases list."""
    purchases: List[ISPSMSPurchaseItem]
    total: int
    total_revenue: float
    total_sms_sold: int


@router.get("/isp-purchases", response_model=ISPSMSPurchasesResponse)
async def get_isp_sms_purchases(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
) -> ISPSMSPurchasesResponse:
    """
    Get all ISP SMS purchases across the platform.

    Returns a list of SMS top-up purchases made by ISPs, including
    organization details, amounts, and current balances.
    """
    from sqlalchemy import func
    from app.models.sms_credit import SMSTopUp, SMSTransactionStatus, SMSCreditAccount
    from app.models.organization import Organization

    # Query top-ups with organization info
    query = (
        select(SMSTopUp, SMSCreditAccount, Organization)
        .join(SMSCreditAccount, SMSTopUp.account_id == SMSCreditAccount.id)
        .join(Organization, SMSCreditAccount.organization_id == Organization.id)
        .where(SMSTopUp.status == SMSTransactionStatus.COMPLETED)
        .order_by(SMSTopUp.created_at.desc())
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    purchases = []
    total_revenue = 0.0
    total_sms_sold = 0

    for top_up, account, org in rows:
        purchases.append(ISPSMSPurchaseItem(
            id=top_up.id,
            organization_id=org.id,
            organization_name=org.name,
            amount=float(top_up.amount),
            sms_credits=top_up.sms_credits,
            status=top_up.status.value if hasattr(top_up.status, 'value') else str(top_up.status),
            payment_reference=top_up.payment_reference,
            purchased_at=top_up.created_at.strftime("%Y-%m-%d %H:%M") if top_up.created_at else "",
            current_balance=float(account.current_balance),
        ))
        total_revenue += float(top_up.amount)
        total_sms_sold += top_up.sms_credits

    # Get total count
    count_query = (
        select(func.count(SMSTopUp.id))
        .join(SMSCreditAccount, SMSTopUp.account_id == SMSCreditAccount.id)
        .where(
            SMSTopUp.status == SMSTransactionStatus.COMPLETED,
            SMSCreditAccount.organization_id.isnot(None),
        )
    )
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return ISPSMSPurchasesResponse(
        purchases=purchases,
        total=total,
        total_revenue=total_revenue,
        total_sms_sold=total_sms_sold,
    )


@router.get("/{gateway_id}", response_model=PlatformSMSGatewayResponse)
async def get_platform_sms_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get a platform SMS gateway by ID.

    Platform Owner only.
    """
    result = await db.execute(
        select(SMSGatewayConfig).where(
            SMSGatewayConfig.id == gateway_id,
            SMSGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform SMS gateway not found",
        )

    return PlatformSMSGatewayResponse(
        id=gateway.id,
        provider_type=gateway.provider_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        environment=gateway.environment or "sandbox",
        has_credentials=bool(gateway.credentials),
        status=gateway.status.value if gateway.status else "pending_verification",
        last_error=gateway.last_error,
    )


@router.patch("/{gateway_id}", response_model=PlatformSMSGatewayResponse)
async def update_platform_sms_gateway(
    gateway_id: int,
    data: PlatformSMSGatewayUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Update a platform SMS gateway.

    Platform Owner only.
    """
    result = await db.execute(
        select(SMSGatewayConfig).where(
            SMSGatewayConfig.id == gateway_id,
            SMSGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform SMS gateway not found",
        )

    # Update fields
    if data.name is not None:
        gateway.name = data.name
    if data.is_active is not None:
        gateway.is_active = data.is_active
    if data.environment is not None:
        gateway.environment = data.environment

    # Handle primary flag
    if data.is_primary is not None and data.is_primary and not gateway.is_primary:
        # Unset other primary gateways
        result = await db.execute(
            select(SMSGatewayConfig).where(
                SMSGatewayConfig.organization_id.is_(None),
                SMSGatewayConfig.is_primary == True,
                SMSGatewayConfig.id != gateway_id,
            )
        )
        for existing in result.scalars().all():
            existing.is_primary = False
        gateway.is_primary = True
    elif data.is_primary is not None:
        gateway.is_primary = data.is_primary

    # Update credentials if provided and not empty
    if data.credentials is not None:
        credentials_dict = data.credentials.model_dump(exclude_none=True)
        if credentials_dict:
            # Add is_sandbox based on environment
            env = data.environment or gateway.environment or "sandbox"
            credentials_dict["is_sandbox"] = env == "sandbox"
            gateway.credentials = encrypt_credentials(credentials_dict)
            gateway.status = SMSGatewayStatus.PENDING_VERIFICATION

    await db.commit()
    await db.refresh(gateway)

    return PlatformSMSGatewayResponse(
        id=gateway.id,
        provider_type=gateway.provider_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        environment=gateway.environment or "sandbox",
        has_credentials=bool(gateway.credentials),
        status=gateway.status.value if gateway.status else "pending_verification",
        last_error=gateway.last_error,
    )


@router.delete("/{gateway_id}")
async def delete_platform_sms_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Delete a platform SMS gateway.

    Platform Owner only.
    """
    result = await db.execute(
        select(SMSGatewayConfig).where(
            SMSGatewayConfig.id == gateway_id,
            SMSGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform SMS gateway not found",
        )

    await db.delete(gateway)
    await db.commit()

    return {"message": "Platform SMS gateway deleted"}


@router.post("/{gateway_id}/test", response_model=TestConnectionResponse)
async def test_platform_sms_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Test platform SMS gateway connection.

    Platform Owner only. Tests the gateway by checking account balance.
    """
    result = await db.execute(
        select(SMSGatewayConfig).where(
            SMSGatewayConfig.id == gateway_id,
            SMSGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform SMS gateway not found",
        )

    if not gateway.credentials:
        return TestConnectionResponse(
            success=False,
            message="No credentials configured",
        )

    try:
        # SMS delivery is owned by the central notifications-api. We can no longer
        # do a live provider balance check locally; instead validate that the
        # stored credentials decrypt to a well-formed blob and mark active.
        credentials = decrypt_credentials(gateway.credentials)
        if not isinstance(credentials, dict) or not credentials:
            raise ValueError("stored credentials are empty or malformed")

        gateway.status = SMSGatewayStatus.ACTIVE
        gateway.last_error = None
        gateway.last_error_at = None
        await db.commit()

        return TestConnectionResponse(
            success=True,
            message="Credentials valid. SMS delivery is handled by the central notifications-api.",
        )

    except Exception as e:
        # Update gateway with error
        gateway.status = SMSGatewayStatus.ERROR
        gateway.last_error = str(e)
        from datetime import datetime
        gateway.last_error_at = datetime.utcnow()
        await db.commit()

        return TestConnectionResponse(
            success=False,
            message=str(e),
        )


# =========================================================================
# Platform SMS Settings Schemas
# =========================================================================

class PlatformSMSSettingsCreate(BaseModel):
    """Schema for creating/updating platform SMS settings."""
    cost_per_sms: float = Field(0.50, ge=0, description="Cost per SMS in platform currency")
    currency: str = Field("KES", max_length=3)
    minimum_top_up_amount: float = Field(100, ge=0)
    payment_method: str = Field("mpesa", description="Payment method for ISP top-ups")
    mpesa_paybill: Optional[str] = None
    mpesa_till_number: Optional[str] = None
    mpesa_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    paystack_subaccount_code: Optional[str] = None
    sms_per_unit: int = Field(1, ge=1, description="Number of SMS credits per unit")


class PlatformSMSSettingsResponse(BaseModel):
    """Schema for platform SMS settings response."""
    id: int
    cost_per_sms: float
    currency: str
    minimum_top_up_amount: float
    payment_method: str
    mpesa_paybill: Optional[str] = None
    mpesa_till_number: Optional[str] = None
    mpesa_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    paystack_subaccount_code: Optional[str] = None
    sms_per_unit: int
    is_active: bool

    model_config = {"from_attributes": True}


# =========================================================================
# Platform SMS Settings Endpoints
# =========================================================================

@router.get("/settings/pricing", response_model=PlatformSMSSettingsResponse)
async def get_platform_sms_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get platform SMS pricing and payment settings.

    Platform Owner only.
    """
    result = await db.execute(
        select(PlatformSMSSettings).where(PlatformSMSSettings.is_active == True)
    )
    settings_obj = result.scalar_one_or_none()

    if not settings_obj:
        # Return default settings if none exist
        return PlatformSMSSettingsResponse(
            id=0,
            cost_per_sms=0.50,
            currency="KES",
            minimum_top_up_amount=100,
            payment_method="mpesa",
            mpesa_paybill=None,
            mpesa_till_number=None,
            mpesa_account_name=None,
            bank_account_number=None,
            bank_name=None,
            bank_branch=None,
            paystack_subaccount_code=None,
            sms_per_unit=1,
            is_active=True,
        )

    return PlatformSMSSettingsResponse(
        id=settings_obj.id,
        cost_per_sms=float(settings_obj.cost_per_sms),
        currency=settings_obj.currency,
        minimum_top_up_amount=float(settings_obj.minimum_top_up_amount),
        payment_method=settings_obj.payment_method,
        mpesa_paybill=settings_obj.mpesa_paybill,
        mpesa_till_number=settings_obj.mpesa_till_number,
        mpesa_account_name=settings_obj.mpesa_account_name,
        bank_account_number=settings_obj.bank_account_number,
        bank_name=settings_obj.bank_name,
        bank_branch=settings_obj.bank_branch,
        paystack_subaccount_code=settings_obj.paystack_subaccount_code,
        sms_per_unit=settings_obj.sms_per_unit,
        is_active=settings_obj.is_active,
    )


@router.post("/settings/pricing", response_model=PlatformSMSSettingsResponse)
async def create_or_update_platform_sms_settings(
    data: PlatformSMSSettingsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create or update platform SMS pricing and payment settings.

    Platform Owner only. This defines how much ISPs pay per SMS
    and where their payments are collected.
    """
    from decimal import Decimal

    # Check for existing settings
    result = await db.execute(
        select(PlatformSMSSettings).where(PlatformSMSSettings.is_active == True)
    )
    settings_obj = result.scalar_one_or_none()

    if settings_obj:
        # Update existing settings
        settings_obj.cost_per_sms = Decimal(str(data.cost_per_sms))
        settings_obj.currency = data.currency
        settings_obj.minimum_top_up_amount = Decimal(str(data.minimum_top_up_amount))
        settings_obj.payment_method = data.payment_method
        settings_obj.mpesa_paybill = data.mpesa_paybill
        settings_obj.mpesa_till_number = data.mpesa_till_number
        settings_obj.mpesa_account_name = data.mpesa_account_name
        settings_obj.bank_account_number = data.bank_account_number
        settings_obj.bank_name = data.bank_name
        settings_obj.bank_branch = data.bank_branch
        settings_obj.paystack_subaccount_code = data.paystack_subaccount_code
        settings_obj.sms_per_unit = data.sms_per_unit
    else:
        # Create new settings
        settings_obj = PlatformSMSSettings(
            cost_per_sms=Decimal(str(data.cost_per_sms)),
            currency=data.currency,
            minimum_top_up_amount=Decimal(str(data.minimum_top_up_amount)),
            payment_method=data.payment_method,
            mpesa_paybill=data.mpesa_paybill,
            mpesa_till_number=data.mpesa_till_number,
            mpesa_account_name=data.mpesa_account_name,
            bank_account_number=data.bank_account_number,
            bank_name=data.bank_name,
            bank_branch=data.bank_branch,
            paystack_subaccount_code=data.paystack_subaccount_code,
            sms_per_unit=data.sms_per_unit,
            is_active=True,
        )
        db.add(settings_obj)

    await db.commit()
    await db.refresh(settings_obj)

    return PlatformSMSSettingsResponse(
        id=settings_obj.id,
        cost_per_sms=float(settings_obj.cost_per_sms),
        currency=settings_obj.currency,
        minimum_top_up_amount=float(settings_obj.minimum_top_up_amount),
        payment_method=settings_obj.payment_method,
        mpesa_paybill=settings_obj.mpesa_paybill,
        mpesa_till_number=settings_obj.mpesa_till_number,
        mpesa_account_name=settings_obj.mpesa_account_name,
        bank_account_number=settings_obj.bank_account_number,
        bank_name=settings_obj.bank_name,
        bank_branch=settings_obj.bank_branch,
        paystack_subaccount_code=settings_obj.paystack_subaccount_code,
        sms_per_unit=settings_obj.sms_per_unit,
        is_active=settings_obj.is_active,
    )
