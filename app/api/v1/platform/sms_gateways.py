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
from app.models.sms_credit import SMSGatewayConfig, SMSProviderType, SMSGatewayStatus
from app.integrations.payment_gateways import PaymentGatewayFactory  # For encryption/decryption
from app.integrations.sms.factory import SMSProviderFactory

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
    encrypted_credentials = PaymentGatewayFactory.encrypt_credentials(credentials_dict)

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
            gateway.credentials = PaymentGatewayFactory.encrypt_credentials(credentials_dict)
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
        # Decrypt credentials using the same method as payment gateways
        encryption_key = getattr(settings, 'encryption_key', None)
        if encryption_key:
            credentials = PaymentGatewayFactory._decrypt_credentials(gateway.credentials, encryption_key)
        else:
            # Development mode - try plain JSON
            import json
            credentials = json.loads(gateway.credentials)

        # Create SMS provider instance
        provider = await SMSProviderFactory.create(
            provider_type=gateway.provider_type,
            credentials=credentials,
            is_active=gateway.is_active,
        )

        # Test connection by getting account balance
        balance, currency = await provider.get_account_balance()

        # Update gateway status
        gateway.status = SMSGatewayStatus.ACTIVE
        gateway.last_error = None
        gateway.last_error_at = None
        await db.commit()

        return TestConnectionResponse(
            success=True,
            message="Connection successful",
            details={
                "balance": float(balance),
                "currency": currency,
            },
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
