"""SMS Credit management API endpoints."""

from typing import Any, Dict, List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_technician_or_admin, PaginationParams
from app.models.user import User
from app.models.sms_credit import SMSCreditAccount, SMSTransaction
from app.services.sms_credit_service import SMSCreditService
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


