"""
Platform Owner API - Billing Management.

Endpoints for platform billing and invoice management.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
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

logger = logging.getLogger(__name__)
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
    from sqlalchemy.orm import selectinload

    query = select(PlatformInvoice).options(selectinload(PlatformInvoice.organization))

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

    # Map to response with organization name
    invoice_responses = []
    for inv in invoices:
        inv_dict = {
            "id": inv.id,
            "organization_id": inv.organization_id,
            "organization_name": inv.organization.name if inv.organization else None,
            "invoice_number": inv.invoice_number,
            "billing_cycle": inv.billing_cycle,
            "billing_period_start": inv.billing_period_start,
            "billing_period_end": inv.billing_period_end,
            "tier_id": inv.tier_id,
            "base_fee": inv.base_fee,
            "earnings_during_period": inv.earnings_during_period,
            "earnings_fee": inv.earnings_fee,
            "customer_count": inv.customer_count,
            "customer_fee": inv.customer_fee,
            "additional_fees": inv.additional_fees,
            "discount": inv.discount,
            "tax": inv.tax,
            "total_amount": inv.total_amount,
            "currency": "KES",
            "status": inv.status,
            "due_date": inv.due_date,
            "paid_at": inv.paid_at,
            "paystack_reference": inv.paystack_reference,
            "notes": inv.notes,
            "pdf_url": inv.pdf_url,
            "created_at": inv.created_at,
            "updated_at": inv.updated_at,
        }
        invoice_responses.append(PlatformInvoiceResponse(**inv_dict))

    return InvoiceListResponse(
        items=invoice_responses,
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
    from sqlalchemy.orm import selectinload

    query = select(PlatformPayment).options(selectinload(PlatformPayment.organization))

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

    # Map to response with organization name
    payment_responses = []
    for p in payments:
        p_dict = {
            "id": p.id,
            "invoice_id": p.invoice_id,
            "organization_id": p.organization_id,
            "organization_name": p.organization.name if p.organization else None,
            "payment_reference": p.payment_reference,
            "amount": p.amount,
            "currency": p.currency,
            "paystack_reference": p.paystack_reference,
            "paystack_channel": p.paystack_channel,
            "card_last4": p.card_last4,
            "card_brand": p.card_brand,
            "status": p.status,
            "status_message": p.status_message,
            "created_at": p.created_at,
            "completed_at": p.completed_at,
        }
        payment_responses.append(PlatformPaymentResponse(**p_dict))

    return PaymentListResponse(
        items=payment_responses,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/payments/{payment_id}", response_model=PlatformPaymentResponse)
async def get_payment_details(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Get payment details by ID.

    Platform owner only.
    """
    result = await db.execute(
        select(PlatformPayment).where(PlatformPayment.id == payment_id)
    )
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    return PlatformPaymentResponse.model_validate(payment)


class RefundPaymentRequest(BaseModel):
    """Request schema for payment refund."""
    amount: Optional[float] = Field(None, description="Partial refund amount (leave empty for full refund)")
    reason: str = Field(..., description="Reason for refund")


class RefundPaymentResponse(BaseModel):
    """Response schema for payment refund."""
    success: bool
    message: str
    refund_reference: Optional[str] = None
    refunded_amount: Optional[float] = None


@router.post("/payments/{payment_id}/refund", response_model=RefundPaymentResponse)
async def refund_payment(
    payment_id: int,
    refund_request: RefundPaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Initiate a refund for a payment.

    Platform owner only.
    Supports both full and partial refunds.
    """
    from decimal import Decimal
    from app.integrations.payment_gateways import PaymentGatewayFactory
    from app.models.payment_gateway import PaymentGatewayConfig, GatewayType
    from app.models.billing import Invoice

    # 1. Get the payment
    result = await db.execute(
        select(PlatformPayment).where(PlatformPayment.id == payment_id)
    )
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    # 2. Check if payment is refundable
    if payment.status != PaymentStatus.COMPLETED:
        return RefundPaymentResponse(
            success=False,
            message=f"Cannot refund payment with status: {payment.status.value}",
        )

    if not payment.transaction_id:
        return RefundPaymentResponse(
            success=False,
            message="Payment has no transaction reference",
        )

    # 3. Get payment gateway configuration
    # Determine which gateway was used based on payment metadata or method
    gateway_type = GatewayType.PAYSTACK  # Default to Paystack for platform payments

    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.gateway_type == gateway_type,
            PaymentGatewayConfig.is_active == True,
            PaymentGatewayConfig.organization_id.is_(None),  # Platform-level gateway
        ).limit(1)
    )
    gateway_config = result.scalar_one_or_none()

    if not gateway_config:
        return RefundPaymentResponse(
            success=False,
            message="Payment gateway not configured",
        )

    # 4. Initialize payment gateway
    try:
        gateway = PaymentGatewayFactory.create(gateway_config)
    except Exception as e:
        return RefundPaymentResponse(
            success=False,
            message=f"Failed to initialize payment gateway: {str(e)}",
        )

    # 5. Process refund
    try:
        refund_amount = Decimal(str(refund_request.amount)) if refund_request.amount else None

        refund_result = await gateway.refund_payment(
            transaction_reference=payment.transaction_id,
            amount=refund_amount,
            reason=refund_request.reason,
        )

        if refund_result.success:
            # Update payment status
            payment.status = PaymentStatus.REFUNDED
            payment.metadata = payment.metadata or {}
            payment.metadata["refund"] = {
                "refund_reference": refund_result.refund_reference,
                "refund_amount": float(refund_result.amount) if refund_result.amount else float(payment.amount),
                "refund_reason": refund_request.reason,
                "refunded_by": current_user.id,
                "refunded_at": datetime.utcnow().isoformat(),
            }

            # If there's an associated invoice, update it
            if payment.invoice_id:
                invoice_result = await db.execute(
                    select(Invoice).where(Invoice.id == payment.invoice_id)
                )
                invoice = invoice_result.scalar_one_or_none()
                if invoice:
                    invoice.status = InvoiceStatus.CANCELLED
                    invoice.metadata = invoice.metadata or {}
                    invoice.metadata["refund_info"] = payment.metadata["refund"]

            await db.commit()

            return RefundPaymentResponse(
                success=True,
                message=refund_result.message or "Refund processed successfully",
                refund_reference=refund_result.refund_reference,
                refunded_amount=float(refund_result.amount) if refund_result.amount else float(payment.amount),
            )
        else:
            return RefundPaymentResponse(
                success=False,
                message=refund_result.message or "Refund failed",
            )

    except Exception as e:
        await db.rollback()
        return RefundPaymentResponse(
            success=False,
            message=f"Refund processing error: {str(e)}",
        )


@router.patch("/invoices/{invoice_id}/update")
async def update_invoice(
    invoice_id: int,
    total_amount: Optional[float] = None,
    due_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Update invoice details (amount, due date, notes).

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoice = await billing_service.get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    if invoice.status == InvoiceStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a paid invoice"
        )

    from decimal import Decimal

    if total_amount is not None:
        invoice.total_amount = Decimal(str(total_amount))

    if due_date is not None:
        invoice.due_date = due_date

    if notes is not None:
        invoice.notes = notes

    invoice.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(invoice)

    return PlatformInvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(
    invoice_id: int,
    reason: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Void/cancel an invoice.

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoice = await billing_service.get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    if invoice.status == InvoiceStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot void a paid invoice. Use refund instead."
        )

    invoice.status = InvoiceStatus.CANCELLED
    invoice.internal_notes = (invoice.internal_notes or "") + f"\nVoided by user {current_user.id}: {reason}"
    invoice.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(invoice)

    return {
        "message": "Invoice voided successfully",
        "invoice_id": invoice.id,
        "status": invoice.status.value,
    }


@router.delete("/invoices/{invoice_id}")
async def delete_invoice(
    invoice_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Delete an invoice.

    - DRAFT/CANCELLED: Can always be deleted
    - PENDING: Can be deleted if never paid (no paid_at date)
    - PAID/OVERDUE: Cannot be deleted unless force=True

    Platform owner only.
    """
    billing_service = PlatformBillingService(db)
    invoice = await billing_service.get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    # Check if invoice has been paid
    if invoice.paid_at and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete paid invoice. Use force=True to override (not recommended)."
        )

    # Allow deletion of DRAFT, CANCELLED, or PENDING (if not paid)
    deletable_statuses = [InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]
    if invoice.status == InvoiceStatus.PENDING and not invoice.paid_at:
        deletable_statuses.append(InvoiceStatus.PENDING)

    if invoice.status not in deletable_statuses and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete invoice with status: {invoice.status.value}. Use force=True to override."
        )

    await db.delete(invoice)
    await db.commit()

    return {
        "message": "Invoice deleted successfully",
        "invoice_id": invoice_id,
        "invoice_number": invoice.invoice_number,
    }


@router.post("/invoices/{invoice_id}/regenerate")
async def regenerate_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_platform_owner),
):
    """
    Regenerate an invoice (recalculates amounts based on current data).

    Platform owner only.
    """
    # Get invoice directly with a simple query first
    result = await db.execute(
        select(PlatformInvoice).where(PlatformInvoice.id == invoice_id)
    )
    old_invoice = result.scalar_one_or_none()

    if not old_invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with ID {invoice_id} not found"
        )

    if old_invoice.status == InvoiceStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot regenerate a paid invoice"
        )

    # Save invoice details before deletion
    org_id = old_invoice.organization_id
    period_start = old_invoice.billing_period_start
    period_end = old_invoice.billing_period_end
    cycle = old_invoice.billing_cycle
    old_amount = float(old_invoice.total_amount)

    # Delete old invoice
    await db.delete(old_invoice)
    await db.flush()

    # Generate new invoice with same period - skip duplicate check since we just deleted the old one
    billing_service = PlatformBillingService(db)
    new_invoice = await billing_service.generate_invoice(
        org_id,
        period_start,
        period_end,
        cycle,
        skip_duplicate_check=True,
    )

    return {
        "success": True,
        "message": "Invoice regenerated successfully",
        "old_invoice_id": invoice_id,
        "new_invoice_id": new_invoice.id,
        "old_amount": old_amount,
        "new_amount": float(new_invoice.total_amount),
        "invoice": PlatformInvoiceResponse.model_validate({
            "id": new_invoice.id,
            "organization_id": new_invoice.organization_id,
            "organization_name": None,  # Will be populated by frontend refresh
            "invoice_number": new_invoice.invoice_number,
            "billing_cycle": new_invoice.billing_cycle,
            "billing_period_start": new_invoice.billing_period_start,
            "billing_period_end": new_invoice.billing_period_end,
            "tier_id": new_invoice.tier_id,
            "base_fee": new_invoice.base_fee,
            "earnings_during_period": new_invoice.earnings_during_period,
            "earnings_fee": new_invoice.earnings_fee,
            "customer_count": new_invoice.customer_count,
            "customer_fee": new_invoice.customer_fee,
            "additional_fees": new_invoice.additional_fees,
            "discount": new_invoice.discount,
            "tax": new_invoice.tax,
            "total_amount": new_invoice.total_amount,
            "currency": "KES",
            "status": new_invoice.status,
            "due_date": new_invoice.due_date,
            "paid_at": new_invoice.paid_at,
            "paystack_reference": new_invoice.paystack_reference,
            "notes": new_invoice.notes,
            "pdf_url": new_invoice.pdf_url,
            "created_at": new_invoice.created_at,
            "updated_at": new_invoice.updated_at,
        })
    }


class PlatformPaymentInitiationRequest(BaseModel):
    """Request schema for platform payment initiation."""
    callback_url: str = Field(..., description="URL to redirect after payment")
    email: str = Field(..., description="Email for payment receipt")


class PlatformPaymentInitiationResponse(BaseModel):
    """Response schema for platform payment initiation."""
    success: bool
    checkout_url: Optional[str] = None
    reference: Optional[str] = None
    access_code: Optional[str] = None
    error: Optional[str] = None


@router.post("/invoices/{invoice_id}/pay", response_model=PlatformPaymentInitiationResponse)
async def initiate_invoice_payment(
    invoice_id: int,
    request_data: PlatformPaymentInitiationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate a Paystack payment for a platform invoice.

    This endpoint allows ISP providers to pay their platform subscription invoices.
    Returns a Paystack checkout URL for payment completion.

    The invoice_id should correspond to a platform_invoices record, NOT a regular invoices record.
    """
    try:
        billing_service = PlatformBillingService(db)

        # Verify invoice exists
        invoice = await billing_service.get_invoice(invoice_id)
        if not invoice:
            return PlatformPaymentInitiationResponse(
                success=False,
                error="Invoice not found"
            )

        if invoice.status == InvoiceStatus.PAID:
            return PlatformPaymentInitiationResponse(
                success=False,
                error="Invoice is already paid"
            )

        # Initiate payment through PlatformBillingService
        result = await billing_service.initiate_payment(
            invoice_id=invoice_id,
            email=request_data.email,
            callback_url=request_data.callback_url,
        )

        return PlatformPaymentInitiationResponse(
            success=result.get("success", False),
            checkout_url=result.get("checkout_url"),
            reference=result.get("reference"),
            access_code=result.get("access_code"),
            error=result.get("error"),
        )

    except Exception as e:
        logger.error(f"Platform payment initiation error: {e}")
        return PlatformPaymentInitiationResponse(
            success=False,
            error=str(e),
        )


class PaymentVerificationResponse(BaseModel):
    """Response schema for payment verification."""
    success: bool
    status: str
    message: str
    invoice_id: Optional[int] = None
    payment_id: Optional[int] = None


@router.get("/payments/verify/{reference}", response_model=PaymentVerificationResponse)
async def verify_payment_by_reference(
    reference: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify a Paystack payment by reference.

    This endpoint is called after a customer completes payment on Paystack
    to confirm the payment status and update the invoice.

    It first checks for an existing payment record. If none exists (e.g.
    webhook hasn't fired), it verifies directly with Paystack and processes
    the payment if successful.
    """
    try:
        billing_service = PlatformBillingService(db)

        # 1. Check for existing payment record by our reference format
        result = await db.execute(
            select(PlatformPayment).where(
                or_(
                    PlatformPayment.payment_reference == f"PAY-{reference}",
                    PlatformPayment.paystack_reference == reference,
                )
            )
        )
        payment = result.scalar_one_or_none()

        if payment:
            if payment.status == PaymentStatus.COMPLETED:
                return PaymentVerificationResponse(
                    success=True,
                    status="success",
                    message="Payment completed successfully",
                    invoice_id=payment.invoice_id,
                    payment_id=payment.id,
                )
            elif payment.status == PaymentStatus.FAILED:
                return PaymentVerificationResponse(
                    success=False,
                    status="failed",
                    message=payment.status_message or "Payment failed",
                    invoice_id=payment.invoice_id,
                    payment_id=payment.id,
                )
            else:
                return PaymentVerificationResponse(
                    success=False,
                    status="pending",
                    message="Payment is still pending verification",
                    invoice_id=payment.invoice_id,
                    payment_id=payment.id,
                )

        # 2. No payment record yet - look up the invoice by paystack_reference
        #    and verify directly with Paystack (webhook may not have fired)
        invoice_result = await db.execute(
            select(PlatformInvoice).where(
                PlatformInvoice.paystack_reference == reference
            )
        )
        invoice = invoice_result.scalar_one_or_none()

        if not invoice:
            return PaymentVerificationResponse(
                success=False,
                status="not_found",
                message="No invoice found for this payment reference",
            )

        # Already paid via another path
        if invoice.status == InvoiceStatus.PAID:
            return PaymentVerificationResponse(
                success=True,
                status="success",
                message="Invoice already paid",
                invoice_id=invoice.id,
            )

        # 3. Verify directly with Paystack API
        try:
            paystack = await billing_service._get_payment_gateway(invoice.organization_id)
            verification = await paystack.verify_payment(reference)
        except Exception as e:
            logger.error(f"Paystack verification failed: {e}")
            return PaymentVerificationResponse(
                success=False,
                status="pending",
                message="Unable to verify with payment gateway. Please try again shortly.",
            )

        if not verification.success:
            return PaymentVerificationResponse(
                success=False,
                status=verification.status.value if hasattr(verification.status, 'value') else str(verification.status),
                message=verification.message or "Payment was not successful",
            )

        # 4. Payment confirmed by Paystack - process it
        payment = await billing_service.verify_and_complete_payment(
            invoice=invoice,
            reference=reference,
            verification=verification,
        )

        return PaymentVerificationResponse(
            success=True,
            status="success",
            message="Payment verified and processed successfully",
            invoice_id=invoice.id,
            payment_id=payment.id if payment else None,
        )

    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return PaymentVerificationResponse(
            success=False,
            status="error",
            message=f"Verification error: {str(e)}"
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
