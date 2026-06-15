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


async def _resolve_topup_tenant_uuid(db: AsyncSession, account: SMSCreditAccount) -> Optional[str]:
    """Resolve the treasury tenant UUID for an SMS-credit top-up.

    Uses the account's organization UUID when the account belongs to an ISP;
    falls back to the platform tenant id configured for notifications/treasury.
    """
    from app.models.organization import Organization

    if account.organization_id:
        org = await db.get(Organization, account.organization_id)
        if org and getattr(org, "uuid", None):
            return str(org.uuid)
    from app.core.config import settings as _s
    return getattr(_s, "notifications_tenant_id", None)


@router.post("/accounts/{account_id}/paystack-top-up", response_model=PaystackSMSTopUpResponse)
async def initiate_paystack_sms_topup(
    account_id: int,
    request: PaystackSMSTopUpRequest,
    current_user: User = Depends(require_technician_or_admin()),
    db: AsyncSession = Depends(get_db),
) -> PaystackSMSTopUpResponse:
    """
    Initiate an SMS credit top-up via treasury-api (the single payment path).

    Calculates SMS credits, creates a pending SMS top-up record, then creates a
    treasury payment intent and returns the shared treasury pay-page checkout URL.
    Confirmation is by polling ``verify-paystack-payment`` (treasury get_status).
    The response field name ``checkout_url`` is unchanged for the UI.
    """
    import uuid
    from sqlalchemy import select
    from app.models.sms_credit import PlatformSMSSettings, SMSTopUp, SMSTransactionStatus
    from app.services.treasury_topup import create_topup_intent

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

    # 3. Get SMS account
    result = await db.execute(
        select(SMSCreditAccount).where(SMSCreditAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        return PaystackSMSTopUpResponse(
            success=False,
            message="SMS account not found",
        )

    tenant_uuid = await _resolve_topup_tenant_uuid(db, account)
    if not tenant_uuid:
        return PaystackSMSTopUpResponse(
            success=False,
            message="Unable to resolve billing tenant for this SMS account",
        )

    # 4. Create pending top-up record (treasury intent id stored on provider_order_id)
    reference = f"SMS-{account_id}-{uuid.uuid4().hex[:12].upper()}"
    top_up = SMSTopUp(
        top_up_reference=reference,
        account_id=account_id,
        amount=amount_decimal,
        currency=pricing.currency,
        sms_credits=sms_credits,
        cost_per_sms=pricing.cost_per_sms,
        payment_method="treasury",
        payment_reference=reference,
        status=SMSTransactionStatus.PENDING,
        requested_by=current_user.id,
        balance_before=account.current_balance,
    )
    db.add(top_up)
    await db.commit()
    await db.refresh(top_up)

    # 5. Create treasury intent + pay-page checkout
    intent = await create_topup_intent(
        tenant_uuid=tenant_uuid,
        amount=str(amount_decimal),
        currency=pricing.currency,
        reference=reference,
        reference_type="sms_credit_topup",
        description=f"SMS Credit Top-up - {sms_credits} SMS",
        redirect_url=request.callback_url or "",
        customer_email=request.email,
        metadata={
            "top_up_id": top_up.id,
            "account_id": account_id,
            "sms_credits": sms_credits,
            "type": "sms_top_up",
        },
        button_text="Add SMS Credits",
    )

    if intent is None:
        await db.delete(top_up)
        await db.commit()
        return PaystackSMSTopUpResponse(
            success=False,
            message="Payment service is temporarily unavailable. Please try again.",
        )

    top_up.provider_order_id = intent.intent_id
    await db.commit()

    return PaystackSMSTopUpResponse(
        success=True,
        message="Choose a payment method to complete your top-up.",
        checkout_url=intent.checkout_url,
        reference=reference,
        top_up_id=top_up.id,
        sms_credits=sms_credits,
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
    Verify an SMS top-up payment via treasury-api and apply the credits.

    Polls the treasury payment intent (get_status) for the top-up's stored intent
    id; on success applies the SMS credits. Confirmation is owned by treasury-api
    (the NATS consumer is the primary path; this is the fallback poll). Endpoint
    name retained for the existing UI callback.
    """
    from sqlalchemy import select
    from app.models.sms_credit import SMSTopUp, SMSTransactionStatus, SMSCreditAccount
    from app.services.treasury_topup import get_intent_status, SUCCESS_STATUSES, FAILURE_STATUSES

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

    account_result = await db.execute(
        select(SMSCreditAccount).where(SMSCreditAccount.id == top_up.account_id)
    )
    account = account_result.scalar_one_or_none()

    # 2. Check if already processed
    if top_up.status == SMSTransactionStatus.COMPLETED:
        return VerifyPaystackPaymentResponse(
            success=True,
            message="Payment already processed",
            sms_credits=top_up.sms_credits,
            new_balance=float(account.current_balance) if account else None,
        )

    # 3. Verify with treasury-api
    if not top_up.provider_order_id:
        return VerifyPaystackPaymentResponse(
            success=False,
            message="No treasury payment intent associated with this top-up",
        )

    tenant_uuid = await _resolve_topup_tenant_uuid(db, account) if account else None
    if not tenant_uuid:
        return VerifyPaystackPaymentResponse(
            success=False,
            message="Unable to resolve billing tenant for this SMS account",
        )

    treasury_status = await get_intent_status(
        tenant_uuid=tenant_uuid, intent_id=top_up.provider_order_id
    )

    if treasury_status is None:
        return VerifyPaystackPaymentResponse(
            success=False,
            message="Unable to verify payment with treasury. Please try again.",
        )

    if treasury_status in FAILURE_STATUSES:
        top_up.status = SMSTransactionStatus.FAILED
        await db.commit()
        return VerifyPaystackPaymentResponse(
            success=False,
            message=f"Payment {treasury_status}",
        )

    if treasury_status not in SUCCESS_STATUSES:
        return VerifyPaystackPaymentResponse(
            success=False,
            message="Payment is still pending",
        )

    # 4. Apply credits
    top_up.status = SMSTransactionStatus.COMPLETED
    top_up.external_transaction_id = top_up.provider_order_id
    top_up.processed_at = datetime.utcnow()
    top_up.approved_by = current_user.id

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


