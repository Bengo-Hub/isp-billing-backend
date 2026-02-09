"""
Public Payment Gateway Endpoints.

Public endpoints for retrieving available payment gateways.
Used by buy packages page to show payment options.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.payment_gateway import PaymentGatewayConfig, GatewayStatus
from app.utils.tenant import get_org_slug_from_request

router = APIRouter(prefix="/payment-gateways", tags=["Public - Payment Gateways"])


# =========================================================================
# Schemas
# =========================================================================

class AvailableGatewayResponse(BaseModel):
    """Schema for available payment gateway."""

    id: int
    gateway_type: str
    name: str
    display_name: str
    is_active: bool
    is_primary: bool
    environment: str

    # M-PESA specific fields
    paybill_number: Optional[str] = None
    till_number: Optional[str] = None

    # Bank specific fields
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None

    # Transaction limits
    min_amount: float
    max_amount: float


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/available", response_model=List[AvailableGatewayResponse])
async def get_available_payment_gateways(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all active payment gateway integrations for the organization.

    Public endpoint - no authentication required.
    Uses org slug from request headers or falls back to first org.

    Returns all configured and active payment gateways including:
    - M-PESA (Paybill, Till, with/without API)
    - Paystack
    - Pesapal
    - Kopo Kopo
    - PayPal
    - Bank Accounts
    """
    # Get org slug from request headers or fallback
    org_slug = await get_org_slug_from_request(request, db)

    # Get organization ID
    from app.models.organization import Organization
    result = await db.execute(
        select(Organization).where(Organization.slug == org_slug)
    )
    organization = result.scalar_one_or_none()

    if not organization:
        return []

    # All payments go through the platform-level gateway (organization_id IS NULL).
    # ISPs don't configure their own payment collection gateways.
    gateways_result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.organization_id.is_(None),
            PaymentGatewayConfig.is_active == True,
        ).order_by(
            PaymentGatewayConfig.is_primary.desc(),
            PaymentGatewayConfig.name.asc()
        )
    )
    configured_gateways = list(gateways_result.scalars().all())

    # Build response with all active gateways
    available_gateways = []

    for gateway in configured_gateways:
        available_gateways.append(
            AvailableGatewayResponse(
                id=gateway.id,
                gateway_type=gateway.gateway_type.value,
                name=gateway.name,
                display_name=gateway.get_display_name(),
                is_active=gateway.is_active,
                is_primary=gateway.is_primary,
                environment=gateway.environment,
                paybill_number=gateway.paybill_number,
                till_number=gateway.till_number,
                bank_name=gateway.bank_name,
                bank_account_number=gateway.bank_account_number,
                bank_account_name=gateway.bank_account_name,
                min_amount=float(gateway.min_amount),
                max_amount=float(gateway.max_amount),
            )
        )

    return available_gateways
