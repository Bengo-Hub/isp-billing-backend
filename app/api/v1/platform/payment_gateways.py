"""
Platform Payment Gateway Configuration API.

Endpoints for Platform Owners to configure platform-level payment gateways.
These gateways collect ALL customer payments (WiFi users paying for service).
ISPs then receive payouts from this collected pool.

Access Control:
- Platform Owner only: Full access to create, update, delete, and test gateways
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_active_user
from app.models.user import User, UserRole
from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
from app.integrations.payment_gateways import PaymentGatewayFactory

router = APIRouter(prefix="/payment-gateways", tags=["Platform - Payment Gateways"])


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

class GatewayCredentials(BaseModel):
    """Schema for gateway credentials."""

    # Paystack fields
    secret_key: Optional[str] = None
    public_key: Optional[str] = None
    webhook_secret: Optional[str] = None

    # M-PESA fields
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = None
    passkey: Optional[str] = None
    shortcode: Optional[str] = None
    till_number: Optional[str] = None
    callback_url: Optional[str] = None
    environment: Optional[str] = "sandbox"

    # PayPal fields
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    mode: Optional[str] = "sandbox"


class PlatformGatewayCreate(BaseModel):
    """Schema for creating a platform payment gateway."""

    gateway_type: GatewayType
    name: str = Field(..., min_length=1, max_length=100)
    is_active: bool = True
    is_primary: bool = False
    credentials: GatewayCredentials


class PlatformGatewayUpdate(BaseModel):
    """Schema for updating a platform payment gateway."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    is_primary: Optional[bool] = None
    credentials: Optional[GatewayCredentials] = None


class PlatformGatewayResponse(BaseModel):
    """Schema for platform gateway response."""

    id: int
    gateway_type: str
    name: str
    is_active: bool
    is_primary: bool
    has_credentials: bool

    model_config = {"from_attributes": True}


class TestConnectionResponse(BaseModel):
    """Schema for test connection response."""

    success: bool
    message: str
    details: Optional[dict] = None


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/", response_model=List[PlatformGatewayResponse])
async def list_platform_gateways(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    List all platform-level payment gateways.

    Platform Owner only. These gateways collect all customer payments
    (WiFi users paying for service). ISPs receive payouts from this pool.
    """
    # Platform-level gateways have organization_id = NULL
    result = await db.execute(
        select(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.organization_id.is_(None))
        .order_by(PaymentGatewayConfig.is_primary.desc(), PaymentGatewayConfig.name)
    )
    gateways = list(result.scalars().all())

    return [
        PlatformGatewayResponse(
            id=g.id,
            gateway_type=g.gateway_type.value,
            name=g.name,
            is_active=g.is_active,
            is_primary=g.is_primary,
            has_credentials=bool(g.credentials),
        )
        for g in gateways
    ]


@router.post("/", response_model=PlatformGatewayResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_gateway(
    data: PlatformGatewayCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Create or update a platform-level payment gateway.

    Platform Owner only. This gateway will collect all customer payments.
    If a gateway of this type already exists, it will be updated (upsert).
    """
    # Check if gateway of this type already exists at platform level
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.organization_id.is_(None),
            PaymentGatewayConfig.gateway_type == data.gateway_type,
        )
    )
    existing = result.scalar_one_or_none()

    # Encrypt credentials
    credentials_dict = data.credentials.model_dump(exclude_none=True) if data.credentials else {}
    encrypted_credentials = PaymentGatewayFactory.encrypt_credentials(credentials_dict)

    if existing:
        # Update existing gateway (upsert behavior)
        existing.name = data.name
        existing.is_active = data.is_active
        existing.credentials = encrypted_credentials
        if data.is_primary and not existing.is_primary:
            # Unset other primary gateways
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.organization_id.is_(None),
                    PaymentGatewayConfig.is_primary == True,
                    PaymentGatewayConfig.id != existing.id,
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
        gateway = PaymentGatewayConfig(
            organization_id=None,  # Platform-level gateway
            gateway_type=data.gateway_type,
            name=data.name,
            is_active=data.is_active,
            is_primary=data.is_primary,
            requires_manual_reconciliation=False,
            credentials=encrypted_credentials,
        )

        # If setting as primary, unset other primary gateways
        if data.is_primary:
            result = await db.execute(
                select(PaymentGatewayConfig).where(
                    PaymentGatewayConfig.organization_id.is_(None),
                    PaymentGatewayConfig.is_primary == True,
                )
            )
            for existing_gateway in result.scalars().all():
                existing_gateway.is_primary = False

        db.add(gateway)
        await db.commit()
        await db.refresh(gateway)

    return PlatformGatewayResponse(
        id=gateway.id,
        gateway_type=gateway.gateway_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        has_credentials=bool(gateway.credentials),
    )


@router.get("/{gateway_id}", response_model=PlatformGatewayResponse)
async def get_platform_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get a platform payment gateway by ID.

    Platform Owner only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform payment gateway not found",
        )

    return PlatformGatewayResponse(
        id=gateway.id,
        gateway_type=gateway.gateway_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        has_credentials=bool(gateway.credentials),
    )


@router.patch("/{gateway_id}", response_model=PlatformGatewayResponse)
async def update_platform_gateway(
    gateway_id: int,
    data: PlatformGatewayUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Update a platform payment gateway.

    Platform Owner only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform payment gateway not found",
        )

    # Update fields
    if data.name is not None:
        gateway.name = data.name
    if data.is_active is not None:
        gateway.is_active = data.is_active

    # Handle primary flag
    if data.is_primary is not None and data.is_primary and not gateway.is_primary:
        # Unset other primary gateways
        result = await db.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.organization_id.is_(None),
                PaymentGatewayConfig.is_primary == True,
                PaymentGatewayConfig.id != gateway_id,
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
        # Only update if there are actual credentials to update
        if credentials_dict:
            gateway.credentials = PaymentGatewayFactory.encrypt_credentials(credentials_dict)

    await db.commit()
    await db.refresh(gateway)

    return PlatformGatewayResponse(
        id=gateway.id,
        gateway_type=gateway.gateway_type.value,
        name=gateway.name,
        is_active=gateway.is_active,
        is_primary=gateway.is_primary,
        has_credentials=bool(gateway.credentials),
    )


@router.delete("/{gateway_id}")
async def delete_platform_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Delete a platform payment gateway.

    Platform Owner only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform payment gateway not found",
        )

    await db.delete(gateway)
    await db.commit()

    return {"message": "Platform payment gateway deleted"}


@router.post("/{gateway_id}/test", response_model=TestConnectionResponse)
async def test_platform_gateway(
    gateway_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Test platform payment gateway connection.

    Platform Owner only.
    """
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.id == gateway_id,
            PaymentGatewayConfig.organization_id.is_(None),
        )
    )
    gateway = result.scalar_one_or_none()

    if not gateway:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform payment gateway not found",
        )

    if not gateway.credentials:
        return TestConnectionResponse(
            success=False,
            message="No credentials configured",
        )

    try:
        gateway_instance = PaymentGatewayFactory.create(gateway)
        balance_result = await gateway_instance.get_balance()

        if balance_result.success:
            return TestConnectionResponse(
                success=True,
                message="Connection successful",
                details={
                    "balance": float(balance_result.available_balance) if balance_result.available_balance else 0,
                    "currency": balance_result.currency
                },
            )
        else:
            return TestConnectionResponse(
                success=False,
                message=balance_result.message or "Connection failed",
            )
    except Exception as e:
        return TestConnectionResponse(
            success=False,
            message=str(e),
        )
