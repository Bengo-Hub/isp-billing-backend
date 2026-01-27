"""
Tenant Payment Gateway Configuration API.

Endpoints for ISP providers to configure their payment gateways.

Access Control:
- Platform Owner: Full access to secrets, URLs, enable/disable gateways
- ISP Admin: Select gateway, configure payout accounts, view activated providers
- ISP Technician: Read-only access to gateway status
- Customer: No access
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import (
    get_current_organization, 
    require_isp_admin,
    require_platform_integration_access,
    require_tenant_integration_access,
    require_platform_owner,
)
from app.models.organization import Organization
from app.models.payment_gateway import (
    PaymentGatewayConfig, GatewayType,
    PayoutConfig, PayoutScheduleType, PayoutRecipientType, PayoutStatus
)
from app.models.user import User, UserRole
from app.integrations.payment_gateways import PaymentGatewayFactory

router = APIRouter(prefix="/payment-gateways", tags=["Tenant - Payment Gateways"])


# =========================================================================
# Schemas
# =========================================================================

class GatewayCredentials(BaseModel):
    """Schema for gateway credentials."""

    # M-PESA fields
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = None
    passkey: Optional[str] = None
    shortcode: Optional[str] = None
    till_number: Optional[str] = None
    callback_url: Optional[str] = None
    environment: Optional[str] = "sandbox"

    # Paystack fields
    secret_key: Optional[str] = None
    public_key: Optional[str] = None

    # PayPal fields
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    mode: Optional[str] = "sandbox"

    # Manual gateway fields
    paybill_number: Optional[str] = None
    account_number_format: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None


class PaymentGatewayCreate(BaseModel):
    """Schema for creating a payment gateway."""

    gateway_type: GatewayType
    name: str = Field(..., min_length=1, max_length=100)
    is_active: bool = True
    is_primary: bool = False
    credentials: GatewayCredentials
    transaction_fee_type: Optional[str] = None  # percentage, fixed, hybrid
    transaction_fee_value: Optional[float] = None
    transaction_fee_percentage: Optional[float] = None


class PaymentGatewayUpdate(BaseModel):
    """Schema for updating a payment gateway."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    is_primary: Optional[bool] = None
    credentials: Optional[GatewayCredentials] = None
    transaction_fee_type: Optional[str] = None
    transaction_fee_value: Optional[float] = None
    transaction_fee_percentage: Optional[float] = None


class PaymentGatewayResponse(BaseModel):
    """Schema for payment gateway response (Platform Owner - includes sensitive data)."""

    id: int
    gateway_type: str
    name: str
    is_active: bool
    is_primary: bool
    requires_manual_reconciliation: bool
    paybill_number: Optional[str] = None
    till_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    transaction_fee_type: Optional[str] = None
    transaction_fee_value: Optional[float] = None
    transaction_fee_percentage: Optional[float] = None
    has_credentials: bool

    model_config = {"from_attributes": True}


class PaymentGatewayPublicResponse(BaseModel):
    """Schema for payment gateway response (ISP Admin - no sensitive data)."""

    id: int
    gateway_type: str
    name: str
    is_active: bool
    is_primary: bool
    requires_manual_reconciliation: bool
    # Non-sensitive fields only
    paybill_number: Optional[str] = None  # Public facing
    till_number: Optional[str] = None  # Public facing
    bank_name: Optional[str] = None  # For display only
    transaction_fee_type: Optional[str] = None
    transaction_fee_percentage: Optional[float] = None
    is_configured: bool = False  # Whether gateway has been configured by platform

    model_config = {"from_attributes": True}


class ActivatedGatewayInfo(BaseModel):
    """Schema for listing activated gateways available to ISP tenants."""
    
    gateway_type: str
    name: str
    description: str
    is_available: bool  # Available for tenant to select
    is_selected: bool  # Currently selected by this tenant
    supports_payout: bool
    supported_currencies: List[str]


class GatewayTypeInfo(BaseModel):
    """Schema for gateway type information."""

    type: str
    name: str
    description: str
    requires_api: bool
    required_fields: List[str]
    optional_fields: List[str]


class TestConnectionResponse(BaseModel):
    """Schema for test connection response."""

    success: bool
    message: str
    details: Optional[dict] = None


# =========================================================================
# Payout Configuration Schemas
# =========================================================================

class PayoutRecipientTypeInfo(BaseModel):
    """Schema for payout recipient type information."""
    
    type: str
    name: str
    description: str
    currency: str
    supported_countries: List[str]
    is_paystack_supported: bool
    is_enabled: bool  # Can be disabled by system for non-Paystack providers
    required_fields: List[str]


class PayoutConfigCreate(BaseModel):
    """Schema for creating payout configuration."""
    
    schedule_type: PayoutScheduleType
    payout_day: Optional[int] = Field(None, ge=1, le=28, description="1-7 for weekly (Monday=1), 1-28 for monthly")
    payout_time: str = Field("17:00", pattern=r"^\d{2}:\d{2}$", description="Time in HH:MM format")
    
    # Recipient details
    recipient_type: PayoutRecipientType
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_name: Optional[str] = None
    mobile_number: Optional[str] = None
    currency: str = "KES"
    
    # Thresholds
    min_payout_amount: float = Field(1000, ge=0, description="Minimum amount before payout triggers")


class PayoutConfigUpdate(BaseModel):
    """Schema for updating payout configuration."""
    
    schedule_type: Optional[PayoutScheduleType] = None
    payout_day: Optional[int] = Field(None, ge=1, le=28)
    payout_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    
    recipient_type: Optional[PayoutRecipientType] = None
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_name: Optional[str] = None
    mobile_number: Optional[str] = None
    currency: Optional[str] = None
    
    min_payout_amount: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class PayoutConfigResponse(BaseModel):
    """Schema for payout configuration response."""
    
    id: int
    schedule_type: str
    schedule_description: str
    payout_day: Optional[int] = None
    payout_time: str
    
    recipient_type: str
    recipient_code: Optional[str] = None
    recipient_name: Optional[str] = None
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_name: Optional[str] = None
    mobile_number: Optional[str] = None
    currency: str
    
    is_active: bool
    is_verified: bool
    min_payout_amount: float
    
    total_payouts: int
    total_payout_amount: float
    last_payout_at: Optional[str] = None
    last_payout_amount: Optional[float] = None
    
    model_config = {"from_attributes": True}


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/types", response_model=List[GatewayTypeInfo])
async def get_gateway_types():
    """
    Get available payment gateway types and their requirements.
    """
    gateway_info = PaymentGatewayFactory.get_gateway_info()

    types = [
        GatewayTypeInfo(
            type=GatewayType.MPESA_PAYBILL.value,
            name="M-PESA Paybill (with API)",
            description="Accept M-PESA payments via STK Push with automatic reconciliation",
            requires_api=True,
            required_fields=["consumer_key", "consumer_secret", "passkey", "shortcode"],
            optional_fields=["callback_url", "environment"],
        ),
        GatewayTypeInfo(
            type=GatewayType.MPESA_TILL.value,
            name="M-PESA Till (Buy Goods)",
            description="Accept M-PESA payments via Till Number with STK Push",
            requires_api=True,
            required_fields=["consumer_key", "consumer_secret", "passkey", "till_number"],
            optional_fields=["callback_url", "environment"],
        ),
        GatewayTypeInfo(
            type=GatewayType.MPESA_PAYBILL_NO_API.value,
            name="M-PESA Paybill (Manual)",
            description="Accept M-PESA payments with manual reconciliation",
            requires_api=False,
            required_fields=["paybill_number"],
            optional_fields=["account_number_format"],
        ),
        GatewayTypeInfo(
            type=GatewayType.MPESA_TILL_NO_API.value,
            name="M-PESA Till (Manual)",
            description="Accept M-PESA payments to Till with manual reconciliation",
            requires_api=False,
            required_fields=["till_number"],
            optional_fields=[],
        ),
        GatewayTypeInfo(
            type=GatewayType.BANK_ACCOUNT.value,
            name="Bank Account",
            description="Accept bank transfers with manual reconciliation",
            requires_api=False,
            required_fields=["bank_name", "bank_account_number", "bank_account_name"],
            optional_fields=["paybill_number"],
        ),
        GatewayTypeInfo(
            type=GatewayType.PAYSTACK.value,
            name="Paystack",
            description="Accept card payments and bank transfers via Paystack",
            requires_api=True,
            required_fields=["secret_key", "public_key"],
            optional_fields=[],
        ),
        GatewayTypeInfo(
            type=GatewayType.PAYPAL.value,
            name="PayPal",
            description="Accept PayPal payments",
            requires_api=True,
            required_fields=["client_id", "client_secret"],
            optional_fields=["mode"],
        ),
        GatewayTypeInfo(
            type=GatewayType.PESAPAL.value,
            name="PesaPal",
            description="Accept multiple payment methods via PesaPal",
            requires_api=True,
            required_fields=["consumer_key", "consumer_secret"],
            optional_fields=[],
        ),
        GatewayTypeInfo(
            type=GatewayType.KOPO_KOPO.value,
            name="Kopo Kopo",
            description="Accept M-PESA payments via Kopo Kopo",
            requires_api=True,
            required_fields=["client_id", "client_secret"],
            optional_fields=[],
        ),
    ]

    return types


@router.get("/", response_model=List[PaymentGatewayResponse])
async def list_payment_gateways(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    List all payment gateways for the organization.

    ISP Admin only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.organization_id == organization.id)
        .order_by(PaymentGatewayConfig.is_primary.desc(), PaymentGatewayConfig.name)
    )
    gateways = list(result.scalars().all())

    return [
        PaymentGatewayResponse(
            id=g.id,
            gateway_type=g.gateway_type.value,
            name=g.name,
            is_active=g.is_active,
            is_primary=g.is_primary,
            requires_manual_reconciliation=g.requires_manual_reconciliation,
            paybill_number=g.paybill_number,
            till_number=g.till_number,
            bank_name=g.bank_name,
            bank_account_number=g.bank_account_number,
            transaction_fee_type=g.transaction_fee_type,
            transaction_fee_value=float(g.transaction_fee_value) if g.transaction_fee_value else None,
            transaction_fee_percentage=float(g.transaction_fee_percentage) if g.transaction_fee_percentage else None,
            has_credentials=bool(g.credentials),
        )
        for g in gateways
    ]


# =========================================================================
# Tenant-Safe Endpoints (ISP Admin - no secrets access)
# =========================================================================

@router.get("/available", response_model=List[ActivatedGatewayInfo])
async def get_available_gateways(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_integration_access),
    organization: Organization = Depends(get_current_organization),
):
    """
    List payment gateways available for this tenant to use.
    
    **ISP Admin access** - Returns only activated gateways without secrets.
    
    Shows which gateways have been enabled by the platform owner
    and are available for the ISP to select for their customers.
    """
    # Get gateways configured for this organization
    result = await db.execute(
        select(PaymentGatewayConfig)
        .where(
            PaymentGatewayConfig.organization_id == organization.id,
            PaymentGatewayConfig.is_active == True,
        )
        .order_by(PaymentGatewayConfig.is_primary.desc(), PaymentGatewayConfig.name)
    )
    gateways = list(result.scalars().all())
    
    # Build response with gateway info
    gateway_info = []
    for g in gateways:
        info = ActivatedGatewayInfo(
            gateway_type=g.gateway_type.value,
            name=g.name,
            description=f"{g.get_display_name()} - {'Primary' if g.is_primary else 'Secondary'}",
            is_available=g.is_active and bool(g.credentials),
            is_selected=g.is_primary,
            supports_payout=g.gateway_type in [GatewayType.PAYSTACK, GatewayType.MPESA_PAYBILL],
            supported_currencies=["KES"] if "MPESA" in g.gateway_type.value.upper() else ["KES", "NGN", "GHS", "ZAR"],
        )
        gateway_info.append(info)
    
    return gateway_info


@router.get("/tenant-view", response_model=List[PaymentGatewayPublicResponse])
async def get_tenant_gateways(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_integration_access),
    organization: Organization = Depends(get_current_organization),
):
    """
    List payment gateways for tenant view (no sensitive data).
    
    **ISP Admin access** - Shows gateway status without API keys/secrets.
    
    Use this endpoint to display gateway options in tenant settings.
    """
    result = await db.execute(
        select(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.organization_id == organization.id)
        .order_by(PaymentGatewayConfig.is_primary.desc(), PaymentGatewayConfig.name)
    )
    gateways = list(result.scalars().all())
    
    return [
        PaymentGatewayPublicResponse(
            id=g.id,
            gateway_type=g.gateway_type.value,
            name=g.name,
            is_active=g.is_active,
            is_primary=g.is_primary,
            requires_manual_reconciliation=g.requires_manual_reconciliation,
            paybill_number=g.paybill_number,  # Public facing info
            till_number=g.till_number,  # Public facing info
            bank_name=g.bank_name,
            transaction_fee_type=g.transaction_fee_type,
            transaction_fee_percentage=float(g.transaction_fee_percentage) if g.transaction_fee_percentage else None,
            is_configured=bool(g.credentials),
        )
        for g in gateways
    ]


@router.post("/select-primary/{gateway_id}")
async def select_primary_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_integration_access),
    organization: Organization = Depends(get_current_organization),
):
    """
    Select a gateway as primary for this tenant.
    
    **ISP Admin access** - Can only select from already configured gateways.
    
    Does not modify gateway credentials, only changes which gateway is primary.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id == organization.id,
            PaymentGatewayConfig.is_active == True,
        )
    )
    gateway = result.scalar_one_or_none()
    
    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment gateway not found or not active"
        )
    
    if not gateway.credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gateway not fully configured. Contact platform administrator."
        )
    
    # Unset other primary gateways
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.organization_id == organization.id,
            PaymentGatewayConfig.is_primary == True,
        )
    )
    for existing in result.scalars().all():
        existing.is_primary = False
    
    gateway.is_primary = True
    await db.commit()
    
    return {"message": f"'{gateway.name}' selected as primary payment gateway"}


# =========================================================================
# Platform Owner Endpoints (Full access including secrets)
# =========================================================================

@router.post("/", response_model=PaymentGatewayResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_gateway(
    data: PaymentGatewayCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_integration_access),
    organization: Organization = Depends(get_current_organization),
):
    """
    Create a new payment gateway configuration.

    **Platform Owner only** - requires access to integration secrets.
    
    This endpoint creates gateway configurations with API credentials.
    ISP Admins should use the gateway selection endpoint instead.
    """
    # Determine if gateway requires manual reconciliation
    manual_gateways = [
        GatewayType.MPESA_PAYBILL_NO_API,
        GatewayType.MPESA_TILL_NO_API,
        GatewayType.BANK_ACCOUNT,
    ]
    requires_manual = data.gateway_type in manual_gateways

    # Encrypt credentials
    credentials_dict = data.credentials.model_dump(exclude_none=True) if data.credentials else {}
    encrypted_credentials = PaymentGatewayFactory.encrypt_credentials(credentials_dict)

    # Create gateway
    gateway = PaymentGatewayConfig(
        organization_id=organization.id,
        gateway_type=data.gateway_type,
        name=data.name,
        is_active=data.is_active,
        is_primary=data.is_primary,
        requires_manual_reconciliation=requires_manual,
        credentials=encrypted_credentials,
        paybill_number=credentials_dict.get("paybill_number"),
        till_number=credentials_dict.get("till_number"),
        bank_name=credentials_dict.get("bank_name"),
        bank_account_number=credentials_dict.get("bank_account_number"),
        transaction_fee_type=data.transaction_fee_type,
        transaction_fee_value=data.transaction_fee_value,
        transaction_fee_percentage=data.transaction_fee_percentage,
    )

    # If setting as primary, unset other primary gateways
    if data.is_primary:
        await db.execute(
            select(PaymentGatewayConfig)
            .where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.is_primary == True,
            )
        )
        result = await db.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.is_primary == True,
            )
        )
        for existing in result.scalars().all():
            existing.is_primary = False

    db.add(gateway)
    await db.commit()
    await db.refresh(gateway)

    return PaymentGatewayResponse(
        id=gateway.id,
        gateway_type=gateway.gateway_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        requires_manual_reconciliation=gateway.requires_manual_reconciliation,
        paybill_number=gateway.paybill_number,
        till_number=gateway.till_number,
        bank_name=gateway.bank_name,
        bank_account_number=gateway.bank_account_number,
        transaction_fee_type=gateway.transaction_fee_type,
        transaction_fee_value=float(gateway.transaction_fee_value) if gateway.transaction_fee_value else None,
        transaction_fee_percentage=float(gateway.transaction_fee_percentage) if gateway.transaction_fee_percentage else None,
        has_credentials=bool(gateway.credentials),
    )


@router.get("/{gateway_id}", response_model=PaymentGatewayResponse)
async def get_payment_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get a payment gateway by ID.

    ISP Admin only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id == organization.id,
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment gateway not found"
        )

    return PaymentGatewayResponse(
        id=gateway.id,
        gateway_type=gateway.gateway_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        requires_manual_reconciliation=gateway.requires_manual_reconciliation,
        paybill_number=gateway.paybill_number,
        till_number=gateway.till_number,
        bank_name=gateway.bank_name,
        bank_account_number=gateway.bank_account_number,
        transaction_fee_type=gateway.transaction_fee_type,
        transaction_fee_value=float(gateway.transaction_fee_value) if gateway.transaction_fee_value else None,
        transaction_fee_percentage=float(gateway.transaction_fee_percentage) if gateway.transaction_fee_percentage else None,
        has_credentials=bool(gateway.credentials),
    )


@router.patch("/{gateway_id}", response_model=PaymentGatewayResponse)
async def update_payment_gateway(
    gateway_id: int,
    data: PaymentGatewayUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update a payment gateway.

    ISP Admin only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id == organization.id,
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment gateway not found"
        )

    # Update fields
    if data.name is not None:
        gateway.name = data.name
    if data.is_active is not None:
        gateway.is_active = data.is_active
    if data.transaction_fee_type is not None:
        gateway.transaction_fee_type = data.transaction_fee_type
    if data.transaction_fee_value is not None:
        gateway.transaction_fee_value = data.transaction_fee_value
    if data.transaction_fee_percentage is not None:
        gateway.transaction_fee_percentage = data.transaction_fee_percentage

    # Handle primary flag
    if data.is_primary is not None and data.is_primary and not gateway.is_primary:
        # Unset other primary gateways
        result = await db.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.organization_id == organization.id,
                PaymentGatewayConfig.is_primary == True,
                PaymentGatewayConfig.id != gateway_id,
            )
        )
        for existing in result.scalars().all():
            existing.is_primary = False
        gateway.is_primary = True
    elif data.is_primary is not None:
        gateway.is_primary = data.is_primary

    # Update credentials if provided
    if data.credentials is not None:
        credentials_dict = data.credentials.model_dump(exclude_none=True)
        gateway.credentials = PaymentGatewayFactory.encrypt_credentials(credentials_dict)
        gateway.paybill_number = credentials_dict.get("paybill_number", gateway.paybill_number)
        gateway.till_number = credentials_dict.get("till_number", gateway.till_number)
        gateway.bank_name = credentials_dict.get("bank_name", gateway.bank_name)
        gateway.bank_account_number = credentials_dict.get("bank_account_number", gateway.bank_account_number)

    await db.commit()
    await db.refresh(gateway)

    return PaymentGatewayResponse(
        id=gateway.id,
        gateway_type=gateway.gateway_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        requires_manual_reconciliation=gateway.requires_manual_reconciliation,
        paybill_number=gateway.paybill_number,
        till_number=gateway.till_number,
        bank_name=gateway.bank_name,
        bank_account_number=gateway.bank_account_number,
        transaction_fee_type=gateway.transaction_fee_type,
        transaction_fee_value=float(gateway.transaction_fee_value) if gateway.transaction_fee_value else None,
        transaction_fee_percentage=float(gateway.transaction_fee_percentage) if gateway.transaction_fee_percentage else None,
        has_credentials=bool(gateway.credentials),
    )


@router.delete("/{gateway_id}")
async def delete_payment_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Delete a payment gateway.

    ISP Admin only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id == organization.id,
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment gateway not found"
        )

    await db.delete(gateway)
    await db.commit()

    return {"message": "Payment gateway deleted"}


@router.post("/{gateway_id}/test", response_model=TestConnectionResponse)
async def test_gateway_connection(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Test payment gateway connection.

    ISP Admin only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id == organization.id,
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment gateway not found"
        )

    if gateway.requires_manual_reconciliation:
        return TestConnectionResponse(
            success=True,
            message="Manual gateway does not require connection testing",
        )

    try:
        gateway_instance = PaymentGatewayFactory.create(gateway)
        balance_result = await gateway_instance.get_balance()

        if balance_result.success:
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                details={"balance": balance_result.balance, "currency": balance_result.currency},
            )
        else:
            return TestConnectionResponse(
                success=False,
                message=balance_result.error or "Connection failed",
            )
    except Exception as e:
        return TestConnectionResponse(
            success=False,
            message=str(e),
        )


@router.post("/{gateway_id}/set-primary")
async def set_primary_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Set a payment gateway as primary.

    ISP Admin only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id == organization.id,
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment gateway not found"
        )

    # Unset other primary gateways
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.organization_id == organization.id,
            PaymentGatewayConfig.is_primary == True,
        )
    )
    for existing in result.scalars().all():
        existing.is_primary = False

    gateway.is_primary = True
    await db.commit()

    return {"message": f"'{gateway.name}' set as primary payment gateway"}


# =========================================================================
# Payout Configuration Endpoints
# =========================================================================

@router.get("/payout/recipient-types", response_model=List[PayoutRecipientTypeInfo])
async def get_payout_recipient_types():
    """
    Get available payout recipient types and their requirements.
    
    Paystack-supported types are enabled by default.
    Non-Paystack types are available but disabled unless enabled by system admin.
    """
    # Paystack-supported recipient types
    recipient_types = [
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.KEPSS.value,
            name="Kenya Bank Account (KEPSS)",
            description="Bank account payout via Kenya Electronic Payment and Settlement System",
            currency="KES",
            supported_countries=["Kenya"],
            is_paystack_supported=True,
            is_enabled=True,
            required_fields=["bank_code", "account_number", "account_name"],
        ),
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.MOBILE_MONEY.value,
            name="Mobile Money (M-PESA)",
            description="Payout to mobile money account (M-PESA for Kenya, MTN/Vodafone for Ghana)",
            currency="KES",
            supported_countries=["Kenya", "Ghana"],
            is_paystack_supported=True,
            is_enabled=True,
            required_fields=["bank_code", "mobile_number", "account_name"],
        ),
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.MOBILE_MONEY_BUSINESS.value,
            name="Mobile Money Business (Paybill/Till)",
            description="Payout to business Paybill or Till number",
            currency="KES",
            supported_countries=["Kenya"],
            is_paystack_supported=True,
            is_enabled=True,
            required_fields=["bank_code", "account_number", "account_name"],
        ),
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.NUBAN.value,
            name="Nigeria Bank Account (NUBAN)",
            description="Bank account payout via Nigerian Uniform Bank Account Number",
            currency="NGN",
            supported_countries=["Nigeria"],
            is_paystack_supported=True,
            is_enabled=True,
            required_fields=["bank_code", "account_number", "account_name"],
        ),
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.GHIPSS.value,
            name="Ghana Bank Account (GHIPSS)",
            description="Bank account payout via Ghana Interbank Payment and Settlement Systems",
            currency="GHS",
            supported_countries=["Ghana"],
            is_paystack_supported=True,
            is_enabled=True,
            required_fields=["bank_code", "account_number", "account_name"],
        ),
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.BASA.value,
            name="South Africa Bank Account (BASA)",
            description="Bank account payout via Banking Association South Africa",
            currency="ZAR",
            supported_countries=["South Africa"],
            is_paystack_supported=True,
            is_enabled=True,
            required_fields=["bank_code", "account_number", "account_name"],
        ),
        PayoutRecipientTypeInfo(
            type=PayoutRecipientType.AUTHORIZATION.value,
            name="Card Payout (Authorization)",
            description="Payout to a previously authorized card",
            currency="ALL",
            supported_countries=["Nigeria", "Ghana", "South Africa", "Kenya"],
            is_paystack_supported=True,
            is_enabled=False,  # Requires card authorization first
            required_fields=["authorization_code"],
        ),
    ]
    
    return recipient_types


@router.get("/payout/schedule-types")
async def get_payout_schedule_types():
    """Get available payout schedule types."""
    return [
        {
            "type": PayoutScheduleType.INSTANT.value,
            "name": "Instant",
            "description": "Payout immediately when payment is received on Paystack",
            "requires_day": False,
        },
        {
            "type": PayoutScheduleType.DAILY.value,
            "name": "Daily (COB)",
            "description": "Payout at end of business day",
            "requires_day": False,
        },
        {
            "type": PayoutScheduleType.WEEKLY.value,
            "name": "Weekly",
            "description": "Payout on a specific day each week",
            "requires_day": True,
            "day_options": [
                {"value": 1, "label": "Monday"},
                {"value": 2, "label": "Tuesday"},
                {"value": 3, "label": "Wednesday"},
                {"value": 4, "label": "Thursday"},
                {"value": 5, "label": "Friday"},
                {"value": 6, "label": "Saturday"},
                {"value": 7, "label": "Sunday"},
            ],
        },
        {
            "type": PayoutScheduleType.MONTHLY.value,
            "name": "Monthly",
            "description": "Payout on a specific date each month",
            "requires_day": True,
            "day_options": [{"value": i, "label": f"{i}"} for i in range(1, 29)],
        },
    ]


@router.get("/payout/config", response_model=Optional[PayoutConfigResponse])
async def get_payout_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Get current payout configuration for the organization.
    
    ISP Admin only.
    """
    result = await db.execute(
        select(PayoutConfig).where(PayoutConfig.organization_id == organization.id)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        return None
    
    return PayoutConfigResponse(
        id=config.id,
        schedule_type=config.schedule_type.value,
        schedule_description=config.get_schedule_description(),
        payout_day=config.payout_day,
        payout_time=config.payout_time,
        recipient_type=config.recipient_type.value,
        recipient_code=config.recipient_code,
        recipient_name=config.recipient_name,
        bank_code=config.bank_code,
        bank_name=config.bank_name,
        account_number=config.account_number,
        account_name=config.account_name,
        mobile_number=config.mobile_number,
        currency=config.currency,
        is_active=config.is_active,
        is_verified=config.is_verified,
        min_payout_amount=float(config.min_payout_amount),
        total_payouts=config.total_payouts,
        total_payout_amount=float(config.total_payout_amount),
        last_payout_at=config.last_payout_at.isoformat() if config.last_payout_at else None,
        last_payout_amount=float(config.last_payout_amount) if config.last_payout_amount else None,
    )


@router.post("/payout/config", response_model=PayoutConfigResponse)
async def create_payout_config(
    config_data: PayoutConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Create payout configuration for the organization.
    
    ISP Admin only. Only one payout config per organization.
    """
    # Check if config already exists
    result = await db.execute(
        select(PayoutConfig).where(PayoutConfig.organization_id == organization.id)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payout configuration already exists. Use PUT to update."
        )
    
    # Validate schedule type requirements
    if config_data.schedule_type == PayoutScheduleType.WEEKLY and not config_data.payout_day:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payout_day is required for weekly schedule (1-7, Monday=1)"
        )
    
    if config_data.schedule_type == PayoutScheduleType.MONTHLY and not config_data.payout_day:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payout_day is required for monthly schedule (1-28)"
        )
    
    config = PayoutConfig(
        organization_id=organization.id,
        schedule_type=config_data.schedule_type,
        payout_day=config_data.payout_day,
        payout_time=config_data.payout_time,
        recipient_type=config_data.recipient_type,
        bank_code=config_data.bank_code,
        bank_name=config_data.bank_name,
        account_number=config_data.account_number,
        account_name=config_data.account_name,
        mobile_number=config_data.mobile_number,
        currency=config_data.currency,
        min_payout_amount=config_data.min_payout_amount,
        is_active=True,
        is_verified=False,
    )
    
    db.add(config)
    await db.commit()
    await db.refresh(config)
    
    return PayoutConfigResponse(
        id=config.id,
        schedule_type=config.schedule_type.value,
        schedule_description=config.get_schedule_description(),
        payout_day=config.payout_day,
        payout_time=config.payout_time,
        recipient_type=config.recipient_type.value,
        recipient_code=config.recipient_code,
        recipient_name=config.recipient_name,
        bank_code=config.bank_code,
        bank_name=config.bank_name,
        account_number=config.account_number,
        account_name=config.account_name,
        mobile_number=config.mobile_number,
        currency=config.currency,
        is_active=config.is_active,
        is_verified=config.is_verified,
        min_payout_amount=float(config.min_payout_amount),
        total_payouts=config.total_payouts,
        total_payout_amount=float(config.total_payout_amount),
        last_payout_at=None,
        last_payout_amount=None,
    )


@router.put("/payout/config", response_model=PayoutConfigResponse)
async def update_payout_config(
    config_data: PayoutConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Update payout configuration for the organization.
    
    ISP Admin only.
    """
    result = await db.execute(
        select(PayoutConfig).where(PayoutConfig.organization_id == organization.id)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout configuration not found. Use POST to create."
        )
    
    # Update fields if provided
    if config_data.schedule_type is not None:
        config.schedule_type = config_data.schedule_type
        # Reset verification when schedule changes
        config.is_verified = False
    
    if config_data.payout_day is not None:
        config.payout_day = config_data.payout_day
    
    if config_data.payout_time is not None:
        config.payout_time = config_data.payout_time
    
    if config_data.recipient_type is not None:
        config.recipient_type = config_data.recipient_type
        config.is_verified = False
    
    if config_data.bank_code is not None:
        config.bank_code = config_data.bank_code
        config.is_verified = False
    
    if config_data.bank_name is not None:
        config.bank_name = config_data.bank_name
    
    if config_data.account_number is not None:
        config.account_number = config_data.account_number
        config.is_verified = False
    
    if config_data.account_name is not None:
        config.account_name = config_data.account_name
    
    if config_data.mobile_number is not None:
        config.mobile_number = config_data.mobile_number
        config.is_verified = False
    
    if config_data.currency is not None:
        config.currency = config_data.currency
    
    if config_data.min_payout_amount is not None:
        config.min_payout_amount = config_data.min_payout_amount
    
    if config_data.is_active is not None:
        config.is_active = config_data.is_active
    
    await db.commit()
    await db.refresh(config)
    
    return PayoutConfigResponse(
        id=config.id,
        schedule_type=config.schedule_type.value,
        schedule_description=config.get_schedule_description(),
        payout_day=config.payout_day,
        payout_time=config.payout_time,
        recipient_type=config.recipient_type.value,
        recipient_code=config.recipient_code,
        recipient_name=config.recipient_name,
        bank_code=config.bank_code,
        bank_name=config.bank_name,
        account_number=config.account_number,
        account_name=config.account_name,
        mobile_number=config.mobile_number,
        currency=config.currency,
        is_active=config.is_active,
        is_verified=config.is_verified,
        min_payout_amount=float(config.min_payout_amount),
        total_payouts=config.total_payouts,
        total_payout_amount=float(config.total_payout_amount),
        last_payout_at=config.last_payout_at.isoformat() if config.last_payout_at else None,
        last_payout_amount=float(config.last_payout_amount) if config.last_payout_amount else None,
    )


@router.delete("/payout/config")
async def delete_payout_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_isp_admin),
    organization: Organization = Depends(get_current_organization),
):
    """
    Delete payout configuration for the organization.
    
    ISP Admin only.
    """
    result = await db.execute(
        select(PayoutConfig).where(PayoutConfig.organization_id == organization.id)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout configuration not found"
        )
    
    await db.delete(config)
    await db.commit()
    
    return {"message": "Payout configuration deleted successfully"}

