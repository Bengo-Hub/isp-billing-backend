"""SMS Messages API endpoints for ISP admins."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.sms_credit import (
    SMSTransaction, SMSTransactionStatus, SMSTransactionType,
    SMSCreditAccount, SMSTopUp, SMSProviderType
)
from app.models.user import User


router = APIRouter(prefix="/messages", tags=["Messages"])


class SMSBalanceResponse(BaseModel):
    """Response model for SMS balance."""
    account_id: int
    account_name: str
    current_balance: float
    currency: str
    is_low_balance: bool
    today_usage: dict
    recent_transactions: List[dict]


@router.get("/sms-balance", response_model=SMSBalanceResponse)
async def get_tenant_sms_balance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get SMS balance for the current user's organization.

    Returns the SMS credit account balance, usage stats, and recent transactions.
    """
    from datetime import date

    # Get organization ID from current user
    organization_id = current_user.organization_id

    if not organization_id:
        # Return default/empty balance for users without organization
        return SMSBalanceResponse(
            account_id=0,
            account_name="No Account",
            current_balance=0,
            currency="KES",
            is_low_balance=True,
            today_usage={"sent": 0, "failed": 0},
            recent_transactions=[],
        )

    # Find SMS account for this organization
    query = select(SMSCreditAccount).where(
        SMSCreditAccount.organization_id == organization_id,
        SMSCreditAccount.is_active == True,
    )
    result = await db.execute(query)
    account = result.scalar_one_or_none()

    if not account:
        # Return default balance if no account exists
        return SMSBalanceResponse(
            account_id=0,
            account_name="No SMS Account",
            current_balance=0,
            currency="KES",
            is_low_balance=True,
            today_usage={"sent": 0, "failed": 0},
            recent_transactions=[],
        )

    # Get today's usage stats
    today = date.today()
    usage_query = select(
        func.count(SMSTransaction.id).filter(
            SMSTransaction.status == SMSTransactionStatus.COMPLETED
        ).label("sent"),
        func.count(SMSTransaction.id).filter(
            SMSTransaction.status == SMSTransactionStatus.FAILED
        ).label("failed"),
    ).where(
        SMSTransaction.account_id == account.id,
        SMSTransaction.transaction_type == SMSTransactionType.USAGE,
        func.date(SMSTransaction.created_at) == today,
    )
    usage_result = await db.execute(usage_query)
    usage = usage_result.first()

    # Get recent transactions (last 5)
    recent_query = select(SMSTransaction).where(
        SMSTransaction.account_id == account.id,
        SMSTransaction.transaction_type == SMSTransactionType.TOP_UP,
    ).order_by(SMSTransaction.created_at.desc()).limit(5)
    recent_result = await db.execute(recent_query)
    recent_txs = recent_result.scalars().all()

    recent_transactions = [
        {
            "id": tx.id,
            "amount": float(tx.amount) if tx.amount else 0,
            "method": "topup",
            "date": tx.created_at.isoformat() if tx.created_at else "",
        }
        for tx in recent_txs
    ]

    return SMSBalanceResponse(
        account_id=account.id,
        account_name=account.account_name,
        current_balance=float(account.current_balance),
        currency=account.currency,
        is_low_balance=account.is_low_balance,
        today_usage={"sent": usage.sent if usage else 0, "failed": usage.failed if usage else 0},
        recent_transactions=recent_transactions,
    )


# =============================================================================
# Tenant SMS Top-Up (Paystack)
# =============================================================================

class TenantSMSTopUpRequest(BaseModel):
    """Request to initiate SMS top-up for tenant."""
    amount: float = Field(..., gt=0, description="Amount to top up in KES")
    email: str = Field(..., description="Email for payment receipt")
    callback_url: Optional[str] = Field(None, description="Callback URL after payment")


class TenantSMSTopUpResponse(BaseModel):
    """Response from SMS top-up initiation."""
    success: bool
    message: str
    checkout_url: Optional[str] = None
    reference: Optional[str] = None
    sms_credits: Optional[int] = None


@router.post("/sms-topup", response_model=TenantSMSTopUpResponse)
async def tenant_sms_topup(
    request: TenantSMSTopUpRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantSMSTopUpResponse:
    """
    Initiate SMS credit top-up for the current user's organization.

    This endpoint automatically finds or creates an SMS account for the
    organization and initiates a Paystack payment.
    """
    from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
    from app.models.sms_credit import PlatformSMSSettings
    from app.integrations.payment_gateways import PaymentGatewayFactory

    # 1. Get organization ID
    organization_id = current_user.organization_id
    if not organization_id:
        return TenantSMSTopUpResponse(
            success=False,
            message="No organization associated with your account",
        )

    # 2. Get platform SMS pricing settings
    result = await db.execute(
        select(PlatformSMSSettings).where(PlatformSMSSettings.is_active == True).limit(1)
    )
    pricing = result.scalar_one_or_none()

    if not pricing:
        return TenantSMSTopUpResponse(
            success=False,
            message="SMS pricing not configured. Contact platform administrator.",
        )

    # 3. Calculate SMS credits
    cost_per_sms = float(pricing.cost_per_sms)
    if cost_per_sms <= 0:
        return TenantSMSTopUpResponse(
            success=False,
            message="Invalid SMS pricing configuration",
        )

    sms_credits = int(request.amount / cost_per_sms)
    if sms_credits < 1:
        return TenantSMSTopUpResponse(
            success=False,
            message=f"Minimum amount is KES {cost_per_sms} for 1 SMS",
        )

    # 4. Find or create SMS account for this organization
    result = await db.execute(
        select(SMSCreditAccount).where(
            SMSCreditAccount.organization_id == organization_id,
            SMSCreditAccount.is_active == True,
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        # Create new SMS account for this organization
        account = SMSCreditAccount(
            organization_id=organization_id,
            account_name=f"SMS Account - Org {organization_id}",
            account_code=f"SMS-ORG-{organization_id}-{uuid.uuid4().hex[:8].upper()}",
            provider_type=SMSProviderType.AFRICASTALKING,
            phone_number=current_user.phone or "",
            current_balance=Decimal("0"),
            currency="KES",
            is_active=True,
            created_by=current_user.id,
        )
        db.add(account)
        await db.flush()

    # 5. Get Paystack gateway
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
            PaymentGatewayConfig.is_active == True,
            PaymentGatewayConfig.organization_id.is_(None),  # Platform-level gateway
        ).limit(1)
    )
    gateway_config = result.scalar_one_or_none()

    if not gateway_config:
        return TenantSMSTopUpResponse(
            success=False,
            message="Payment gateway not configured",
        )

    # 6. Create top-up record
    reference = f"SMS-{account.id}-{uuid.uuid4().hex[:12].upper()}"
    top_up = SMSTopUp(
        top_up_reference=reference,
        account_id=account.id,
        amount=Decimal(str(request.amount)),
        currency="KES",
        sms_credits=sms_credits,
        cost_per_sms=Decimal(str(cost_per_sms)),
        payment_method="paystack",
        payment_reference=reference,
        status=SMSTransactionStatus.PENDING,
        requested_by=current_user.id,
        balance_before=account.current_balance,
    )
    db.add(top_up)
    await db.commit()
    await db.refresh(top_up)

    # 7. Initialize Paystack payment
    try:
        gateway = PaymentGatewayFactory.create(gateway_config)

        callback_url = request.callback_url or gateway_config.callback_url or ""

        payment_result = await gateway.initiate_payment(
            amount=Decimal(str(request.amount)),
            phone_number="",
            reference=reference,
            description=f"SMS Credit Top-up - {sms_credits} SMS",
            callback_url=callback_url,
            metadata={
                "email": request.email,
                "top_up_id": top_up.id,
                "account_id": account.id,
                "organization_id": organization_id,
                "sms_credits": sms_credits,
                "type": "sms_top_up",
            },
        )

        if payment_result.success:
            return TenantSMSTopUpResponse(
                success=True,
                message="Redirecting to payment...",
                checkout_url=payment_result.checkout_url,
                reference=reference,
                sms_credits=sms_credits,
            )
        else:
            await db.delete(top_up)
            await db.commit()
            return TenantSMSTopUpResponse(
                success=False,
                message=payment_result.message or "Failed to initiate payment",
            )

    except Exception as e:
        await db.delete(top_up)
        await db.commit()
        return TenantSMSTopUpResponse(
            success=False,
            message=f"Payment error: {str(e)}",
        )


class MessageResponse(BaseModel):
    """Response model for a single message."""
    id: int
    user: Optional[str] = None
    phone: str
    channel: str = "SMS"
    message: str
    delivered: bool
    cost: float
    sent: str

    class Config:
        from_attributes = True


class MessagesListResponse(BaseModel):
    """Response model for messages list."""
    messages: List[MessageResponse]
    total: int
    page: int
    page_size: int


@router.get("", response_model=MessagesListResponse)
async def get_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    channel: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get paginated list of SMS messages/transactions.

    - **page**: Page number (default: 1)
    - **page_size**: Number of items per page (default: 20, max: 100)
    - **search**: Search by phone number, username, or message content
    - **channel**: Filter by channel (currently only 'sms' supported)
    """
    # Base query - only get USAGE type transactions (actual SMS sends)
    query = select(SMSTransaction).where(
        SMSTransaction.transaction_type == SMSTransactionType.USAGE
    )

    # Add search filter
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                SMSTransaction.recipient_phone.ilike(search_term),
                SMSTransaction.message_content.ilike(search_term),
            )
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Add pagination and ordering
    offset = (page - 1) * page_size
    query = query.options(selectinload(SMSTransaction.user)).order_by(
        SMSTransaction.created_at.desc()
    ).offset(offset).limit(page_size)

    result = await db.execute(query)
    transactions = result.scalars().all()

    # Transform to response format
    messages = []
    for tx in transactions:
        username = None
        if tx.user:
            username = tx.user.username or tx.user.email

        messages.append(MessageResponse(
            id=tx.id,
            user=username,
            phone=tx.recipient_phone or "",
            channel="SMS",
            message=tx.message_content or "",
            delivered=tx.status == SMSTransactionStatus.COMPLETED or tx.delivery_status == "delivered",
            cost=float(tx.amount) if tx.amount else 0.0,
            sent=tx.created_at.strftime("%d.%m.%Y %H:%M") if tx.created_at else "",
        ))

    return MessagesListResponse(
        messages=messages,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single message by ID."""
    query = select(SMSTransaction).where(
        SMSTransaction.id == message_id
    ).options(selectinload(SMSTransaction.user))

    result = await db.execute(query)
    tx = result.scalar_one_or_none()

    if not tx:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Message not found")

    username = None
    if tx.user:
        username = tx.user.username or tx.user.email

    return MessageResponse(
        id=tx.id,
        user=username,
        phone=tx.recipient_phone or "",
        channel="SMS",
        message=tx.message_content or "",
        delivered=tx.status == SMSTransactionStatus.COMPLETED or tx.delivery_status == "delivered",
        cost=float(tx.amount) if tx.amount else 0.0,
        sent=tx.created_at.strftime("%d.%m.%Y %H:%M:%S") if tx.created_at else "",
    )
