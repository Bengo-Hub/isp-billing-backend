"""SMS Credit management API endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_technician_or_admin, PaginationParams
from app.models.user import User
from app.models.sms_credit import SMSCreditAccount, SMSTransaction
from app.modules.notifications import SMSCreditService
from app.schemas.sms_credit import (
    SMSCreditAccountCreate,
    SMSCreditAccountResponse,
    SMSTopUpRequest,
    SMSTopUpResponse,
    SMSAccountBalanceResponse,
    SMSTransactionList,
    SMSAnalyticsResponse,
    ValidatePhoneRequest,
    ValidatePhoneResponse,
    SMSTransactionItem,
)


router = APIRouter()


@router.post("/accounts", response_model=SMSCreditAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_sms_account(
    account_data: SMSCreditAccountCreate,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> SMSCreditAccountResponse:
    """Create a new SMS credit account (admin only)."""
    service = SMSCreditService(db)
    account = await service.create_sms_account(account_data.dict(), created_by=current_user.id)
    return SMSCreditAccountResponse.model_validate(account)


@router.get("/accounts", response_model=List[SMSCreditAccountResponse])
async def list_sms_accounts(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[SMSCreditAccountResponse]:
    """List SMS credit accounts (admin only)."""
    result = await db.execute(SMSCreditAccount.__table__.select())
    accounts = result.fetchall()
    # Convert Row objects to ORM via second query to preserve from_attributes
    result_models = (await db.execute(SMSCreditAccount.__table__.select())).scalars().all() if hasattr(result, 'scalars') else []
    return [SMSCreditAccountResponse.model_validate(a) for a in result_models]


@router.post("/accounts/{account_id}/top-up", response_model=SMSTopUpResponse)
async def create_top_up(
    account_id: int,
    top_up: SMSTopUpRequest,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> SMSTopUpResponse:
    """Create an SMS credit top-up (admin only)."""
    service = SMSCreditService(db)
    record = await service.top_up_sms_credit(
        account_id=account_id,
        amount=Decimal(top_up.amount),
        payment_method=top_up.payment_method,
        requested_by=current_user.id,
        sms_credits=top_up.sms_credits,
        payment_reference=top_up.payment_reference,
    )
    return SMSTopUpResponse.model_validate(record)


@router.post("/top-ups/{top_up_id}/process")
async def process_top_up(
    top_up_id: int,
    external_transaction_id: str,
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Mark a top-up as completed and apply balance."""
    service = SMSCreditService(db)
    ok = await service.process_top_up(top_up_id, external_transaction_id, approved_by=current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Top-up not found or failed to process")
    return {"message": "Top-up processed successfully"}


@router.get("/accounts/{account_id}/balance", response_model=SMSAccountBalanceResponse)
async def get_account_balance(
    account_id: int,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SMSAccountBalanceResponse:
    service = SMSCreditService(db)
    result = await service.get_account_balance(account_id)
    if not result:
        raise HTTPException(status_code=404, detail="Account not found")
    return SMSAccountBalanceResponse(**result)


@router.get("/accounts/{account_id}/transactions", response_model=SMSTransactionList)
async def get_transactions(
    account_id: int,
    pagination: PaginationParams = Depends(),
    transaction_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SMSTransactionList:
    service = SMSCreditService(db)
    from app.models.sms_credit import SMSTransactionType, SMSTransactionStatus
    t_type = SMSTransactionType(transaction_type) if transaction_type else None
    t_status = SMSTransactionStatus(status_filter) if status_filter else None
    result = await service.get_sms_transaction_history(account_id, pagination, t_type, t_status)
    items = [SMSTransactionItem.model_validate(tx) for tx in result["items"]]
    return SMSTransactionList(items=items, total=result["total"], page=result["page"], size=result["size"], pages=result["pages"])


@router.get("/accounts/{account_id}/analytics", response_model=SMSAnalyticsResponse)
async def get_analytics(
    account_id: int,
    period_type: str = Query("daily"),
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> SMSAnalyticsResponse:
    service = SMSCreditService(db)
    data = await service.get_sms_usage_analytics(account_id, period_type=period_type, days=days)
    return SMSAnalyticsResponse(**data)


@router.post("/validate-phone", response_model=ValidatePhoneResponse)
async def validate_phone(
    req: ValidatePhoneRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> ValidatePhoneResponse:
    service = SMSCreditService(db)
    result = await service.validate_phone_number(req.phone_number, country_code=req.country_code, validation_method=req.validation_method)
    return ValidatePhoneResponse(**result)


# =============================================================================
# Paystack SMS Top-Up Flow
# =============================================================================

from pydantic import BaseModel, Field


class PaystackSMSTopUpRequest(BaseModel):
    """Request to initiate SMS top-up via Paystack."""
    amount: float = Field(..., gt=0, description="Amount to top up in KES")
    email: str = Field(..., description="Customer email for Paystack")
    callback_url: Optional[str] = Field(None, description="Override callback URL")


class PaystackSMSTopUpResponse(BaseModel):
    """Response from Paystack SMS top-up initiation."""
    success: bool
    message: str
    checkout_url: Optional[str] = None
    reference: Optional[str] = None
    top_up_id: Optional[int] = None
    sms_credits: Optional[int] = None


@router.post("/accounts/{account_id}/paystack-top-up", response_model=PaystackSMSTopUpResponse)
async def initiate_paystack_sms_topup(
    account_id: int,
    request: PaystackSMSTopUpRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> PaystackSMSTopUpResponse:
    """
    Initiate SMS credit top-up via Paystack.

    This endpoint:
    1. Gets the platform SMS pricing settings
    2. Calculates SMS credits based on amount
    3. Creates a pending SMS top-up record
    4. Initializes a Paystack payment
    5. Returns the Paystack checkout URL
    """
    import uuid
    from sqlalchemy import select
    from app.models.sms_credit import PlatformSMSSettings, SMSTopUp, SMSTransactionStatus
    from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
    from app.integrations.payment_gateways import PaymentGatewayFactory

    # 1. Get platform SMS pricing settings
    result = await db.execute(
        select(PlatformSMSSettings).where(PlatformSMSSettings.is_active == True)
    )
    pricing = result.scalar_one_or_none()

    if not pricing:
        return PaystackSMSTopUpResponse(
            success=False,
            message="SMS pricing not configured. Please contact platform administrator.",
        )

    # Check minimum top-up amount
    if request.amount < float(pricing.minimum_top_up_amount):
        return PaystackSMSTopUpResponse(
            success=False,
            message=f"Minimum top-up amount is {pricing.currency} {pricing.minimum_top_up_amount}",
        )

    # 2. Calculate SMS credits
    amount_decimal = Decimal(str(request.amount))
    sms_credits = int(amount_decimal / pricing.cost_per_sms) * pricing.sms_per_unit

    if sms_credits <= 0:
        return PaystackSMSTopUpResponse(
            success=False,
            message="Amount too low to purchase any SMS credits",
        )

    # 3. Get active Paystack gateway (platform-level)
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
            PaymentGatewayConfig.is_active == True,
            PaymentGatewayConfig.organization_id.is_(None),  # Platform-level gateway
        ).limit(1)
    )
    gateway_config = result.scalar_one_or_none()

    if not gateway_config:
        return PaystackSMSTopUpResponse(
            success=False,
            message="Paystack payment gateway not configured",
        )

    # 4. Generate unique reference
    reference = f"SMS-{account_id}-{uuid.uuid4().hex[:12].upper()}"

    # 5. Get SMS account balance for recording
    result = await db.execute(
        select(SMSCreditAccount).where(SMSCreditAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        return PaystackSMSTopUpResponse(
            success=False,
            message="SMS account not found",
        )

    # 6. Create pending top-up record
    top_up = SMSTopUp(
        top_up_reference=reference,
        account_id=account_id,
        amount=amount_decimal,
        currency=pricing.currency,
        sms_credits=sms_credits,
        cost_per_sms=pricing.cost_per_sms,
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

        # Determine callback URL
        callback_url = request.callback_url
        if not callback_url:
            # Use platform default callback
            callback_url = gateway_config.callback_url or ""

        payment_result = await gateway.initiate_payment(
            amount=amount_decimal,
            phone_number="",  # Not needed for Paystack
            reference=reference,
            description=f"SMS Credit Top-up - {sms_credits} SMS",
            callback_url=callback_url,
            metadata={
                "email": request.email,
                "top_up_id": top_up.id,
                "account_id": account_id,
                "sms_credits": sms_credits,
                "type": "sms_top_up",
            },
        )

        if payment_result.success:
            return PaystackSMSTopUpResponse(
                success=True,
                message="Payment initialized. Redirecting to Paystack...",
                checkout_url=payment_result.checkout_url,
                reference=reference,
                top_up_id=top_up.id,
                sms_credits=sms_credits,
            )
        else:
            # Rollback top-up record
            await db.delete(top_up)
            await db.commit()
            return PaystackSMSTopUpResponse(
                success=False,
                message=payment_result.message or "Failed to initialize payment",
            )

    except Exception as e:
        # Rollback top-up record
        await db.delete(top_up)
        await db.commit()
        return PaystackSMSTopUpResponse(
            success=False,
            message=f"Payment initialization failed: {str(e)}",
        )


class VerifyPaystackPaymentRequest(BaseModel):
    """Request to verify a Paystack payment."""
    reference: str = Field(..., description="Payment reference from Paystack")


class VerifyPaystackPaymentResponse(BaseModel):
    """Response from payment verification."""
    success: bool
    message: str
    sms_credits: Optional[int] = None
    new_balance: Optional[float] = None


@router.post("/verify-paystack-payment", response_model=VerifyPaystackPaymentResponse)
async def verify_paystack_sms_payment(
    request: VerifyPaystackPaymentRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> VerifyPaystackPaymentResponse:
    """
    Verify a Paystack SMS top-up payment and process the credits.

    This endpoint is called after Paystack redirects back to verify
    the payment was successful and apply the SMS credits.
    """
    from sqlalchemy import select
    from app.models.sms_credit import SMSTopUp, SMSTransactionStatus, SMSCreditAccount
    from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
    from app.integrations.payment_gateways import PaymentGatewayFactory

    # 1. Find the top-up record by reference
    result = await db.execute(
        select(SMSTopUp).where(SMSTopUp.payment_reference == request.reference)
    )
    top_up = result.scalar_one_or_none()

    if not top_up:
        return VerifyPaystackPaymentResponse(
            success=False,
            message="Top-up record not found for this reference",
        )

    # 2. Check if already processed
    if top_up.status == SMSTransactionStatus.COMPLETED:
        # Get current balance
        account_result = await db.execute(
            select(SMSCreditAccount).where(SMSCreditAccount.id == top_up.account_id)
        )
        account = account_result.scalar_one_or_none()

        return VerifyPaystackPaymentResponse(
            success=True,
            message="Payment already processed",
            sms_credits=top_up.sms_credits,
            new_balance=float(account.current_balance) if account else None,
        )

    # 3. Get Paystack gateway to verify payment
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.gateway_type == GatewayType.PAYSTACK,
            PaymentGatewayConfig.is_active == True,
            PaymentGatewayConfig.organization_id.is_(None),
        ).limit(1)
    )
    gateway_config = result.scalar_one_or_none()

    if not gateway_config:
        return VerifyPaystackPaymentResponse(
            success=False,
            message="Paystack gateway not configured",
        )

    # 4. Verify payment with Paystack
    try:
        gateway = PaymentGatewayFactory.create(gateway_config)
        verification = await gateway.verify_payment(request.reference)

        if not verification.success:
            top_up.status = SMSTransactionStatus.FAILED
            await db.commit()
            return VerifyPaystackPaymentResponse(
                success=False,
                message=verification.message or "Payment verification failed",
            )

        # 5. Update top-up record and apply credits
        top_up.status = SMSTransactionStatus.COMPLETED
        top_up.external_transaction_id = verification.gateway_reference
        top_up.processed_at = datetime.utcnow()
        top_up.approved_by = current_user.id

        # 6. Update account balance
        account_result = await db.execute(
            select(SMSCreditAccount).where(SMSCreditAccount.id == top_up.account_id)
        )
        account = account_result.scalar_one_or_none()

        if account:
            top_up.balance_before = account.current_balance
            account.current_balance += top_up.sms_credits
            top_up.balance_after = account.current_balance

        await db.commit()

        return VerifyPaystackPaymentResponse(
            success=True,
            message="Payment verified and SMS credits added",
            sms_credits=top_up.sms_credits,
            new_balance=float(account.current_balance) if account else None,
        )

    except Exception as e:
        return VerifyPaystackPaymentResponse(
            success=False,
            message=f"Payment verification error: {str(e)}",
        )


