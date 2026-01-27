"""
Platform Owner API - Billing Management.

Endpoints for platform billing and invoice management.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_tenant import require_platform_owner
from app.models.user import User
from app.models.platform_billing import (
    PlatformInvoice,
    PlatformPayment,
    InvoiceStatus,
    PaymentStatus,
    BillingCycle,
)
from app.modules.platform_billing.service import PlatformBillingService
from app.modules.platform_billing.schemas import (
    PlatformInvoiceResponse,
    PlatformPaymentResponse,
    InvoiceGenerationRequest,
)

router = APIRouter(prefix="/billing", tags=["Platform - Billing"])


# =========================================================================
# Schemas
# =========================================================================

class InvoiceListResponse(BaseModel):
    """Paginated list of invoices."""

    items: List[PlatformInvoiceResponse]
    total: int
    page: int
    page_size: int
    pages: int


class PaymentListResponse(BaseModel):
    """Paginated list of payments."""

    items: List[PlatformPaymentResponse]
    total: int
    page: int
    page_size: int
    pages: int


class BillingStats(BaseModel):
    """Billing statistics."""

    total_invoiced: float
    total_paid: float
    total_pending: float
    total_overdue: float
    pending_invoice_count: int
    overdue_invoice_count: int
    paid_invoice_count: int


class GenerateInvoicesResponse(BaseModel):
    """Response for invoice generation."""

    generated_count: int
    total_amount: float
    invoice_ids: List[int]


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    organization_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    List all platform invoices.

    Platform owner only.
    """
    query = select(PlatformInvoice)

    if status_filter:
        query = query.where(PlatformInvoice.status == status_filter)

    if organization_id:
        query = query.where(PlatformInvoice.organization_id == organization_id)

    # Get total count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    # Apply pagination
    query = query.order_by(PlatformInvoice.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    invoices = list(result.scalars().all())

    return InvoiceListResponse(
        items=[PlatformInvoiceResponse.model_validate(inv) for inv in invoices],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/invoices/stats", response_model=BillingStats)
async def get_billing_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get billing statistics.

    Platform owner only.
    """
    # Get totals by status
    result = await db.execute(
        select(
            PlatformInvoice.status,
            func.count(PlatformInvoice.id),
            func.sum(PlatformInvoice.total_amount),
        ).group_by(PlatformInvoice.status)
    )
    status_data = {row[0]: {"count": row[1], "total": float(row[2] or 0)} for row in result.all()}

    return BillingStats(
        total_invoiced=sum(d["total"] for d in status_data.values()),
        total_paid=status_data.get(InvoiceStatus.PAID, {}).get("total", 0),
        total_pending=status_data.get(InvoiceStatus.PENDING, {}).get("total", 0),
        total_overdue=status_data.get(InvoiceStatus.OVERDUE, {}).get("total", 0),
        pending_invoice_count=status_data.get(InvoiceStatus.PENDING, {}).get("count", 0),
        overdue_invoice_count=status_data.get(InvoiceStatus.OVERDUE, {}).get("count", 0),
        paid_invoice_count=status_data.get(InvoiceStatus.PAID, {}).get("count", 0),
    )


@router.post("/invoices/generate", response_model=GenerateInvoicesResponse)
async def generate_invoices(
    request: InvoiceGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Generate invoices for organizations.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)

    invoices = []
    for org_id in request.organization_ids or []:
        try:
            invoice = await billing_service.generate_invoice(
                org_id,
                request.billing_period_start,
                request.billing_period_end,
            )
            invoices.append(invoice)
        except Exception as e:
            # Log error but continue with other organizations
            pass

    return GenerateInvoicesResponse(
        generated_count=len(invoices),
        total_amount=sum(float(inv.total_amount) for inv in invoices),
        invoice_ids=[inv.id for inv in invoices],
    )


@router.post("/invoices/generate-monthly", response_model=GenerateInvoicesResponse)
async def generate_monthly_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Generate monthly invoices for all active organizations.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoices = await billing_service.generate_monthly_invoices()

    return GenerateInvoicesResponse(
        generated_count=len(invoices),
        total_amount=sum(float(inv.total_amount) for inv in invoices),
        invoice_ids=[inv.id for inv in invoices],
    )


@router.get("/invoices/{invoice_id}", response_model=PlatformInvoiceResponse)
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get an invoice by ID.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoice = await billing_service.get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    return PlatformInvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/mark-paid")
async def mark_invoice_paid(
    invoice_id: int,
    reference: str,
    amount: Optional[float] = None,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Manually mark an invoice as paid.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoice = await billing_service.get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    from decimal import Decimal

    payment = await billing_service.record_manual_payment(
        invoice_id=invoice_id,
        amount=Decimal(str(amount)) if amount else invoice.total_amount,
        reference=reference,
        notes=notes,
    )

    return {
        "message": "Invoice marked as paid",
        "payment_id": payment.id,
    }


@router.get("/invoices/pending", response_model=List[PlatformInvoiceResponse])
async def get_pending_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get all pending invoices.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoices = await billing_service.get_pending_invoices()
    return [PlatformInvoiceResponse.model_validate(inv) for inv in invoices]


@router.get("/invoices/overdue", response_model=List[PlatformInvoiceResponse])
async def get_overdue_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get all overdue invoices.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoices = await billing_service.get_overdue_invoices()
    return [PlatformInvoiceResponse.model_validate(inv) for inv in invoices]


@router.post("/invoices/mark-overdue")
async def mark_overdue_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Mark all overdue invoices.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    count = await billing_service.mark_overdue_invoices()

    return {
        "message": f"Marked {count} invoices as overdue",
        "count": count,
    }


@router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
    status_filter: Optional[PaymentStatus] = Query(None, alias="status"),
    organization_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    List all platform payments.

    Platform owner only.
    """
    query = select(PlatformPayment)

    if status_filter:
        query = query.where(PlatformPayment.status == status_filter)

    if organization_id:
        query = query.where(PlatformPayment.organization_id == organization_id)

    # Get total count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    # Apply pagination
    query = query.order_by(PlatformPayment.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    payments = list(result.scalars().all())

    return PaymentListResponse(
        items=[PlatformPaymentResponse.model_validate(p) for p in payments],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/webhooks/paystack")
async def paystack_webhook(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Paystack webhook for payment callbacks.

    This endpoint receives payment notifications from Paystack.
    """
    billing_service = PlatformBillingService(db)

    try:
        payment = await billing_service.process_payment_callback(payload)

        if payment:
            return {"status": "success", "payment_id": payment.id}
        else:
            return {"status": "ignored"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
