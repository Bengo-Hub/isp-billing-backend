"""Billing API endpoints."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.api.deps_org import get_org_id_for_query
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.models.user import User
from app.models.billing import InvoiceStatus, PaymentStatus, PaymentMethod
from app.schemas.billing import (
    Invoice, InvoiceCreate, InvoiceUpdate, InvoiceList, InvoiceFilter,
    InvoiceItem, InvoiceItemCreate, InvoiceItemUpdate, Payment, PaymentCreate,
    PaymentUpdate, PaymentList, PaymentFilter, MpesaPaymentRequest, MpesaPaymentResponse,
    MpesaCallbackRequest, MpesaCallbackResponse, BillingStats, PaymentStats,
    InvoiceGenerationRequest, BulkInvoiceGenerationRequest
)
from app.modules.billing import BillingService

# NOTE: the ISP-provider platform-subscription renewal endpoint was removed —
# platform billing is owned by the central subscriptions-api now.

router = APIRouter()


# Invoice endpoints
@router.get("/invoices", response_model=InvoiceList)
async def get_invoices(
    pagination: PaginationParams = Depends(),
    user_id: Optional[int] = Query(None),
    status: Optional[InvoiceStatus] = Query(None),
    search: Optional[str] = Query(None),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceList:
    """Get all invoices with pagination and filters."""
    # Users can only view their own invoices unless they're admin
    if current_user.role != "admin" and user_id and user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's invoices"
        )
    
    # Non-admin users can only view their own invoices
    if current_user.role != "admin":
        user_id = current_user.id
    
    service = BillingService(db)
    result = await service.get_invoices(
        pagination=pagination,
        user_id=user_id,
        status=status,
        search=search,
    )
    return InvoiceList(**result)


@router.post("/invoices", response_model=Invoice, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    invoice_data: InvoiceCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Create a new invoice."""
    service = BillingService(db)
    try:
        invoice = await service.create_invoice(
            user_id=invoice_data.user_id,
            subscription_id=invoice_data.subscription_id,
            subtotal=invoice_data.subtotal,
            tax_amount=invoice_data.tax_amount,
            discount_amount=invoice_data.discount_amount,
            billing_period_start=invoice_data.billing_period_start,
            billing_period_end=invoice_data.billing_period_end,
            notes=invoice_data.notes,
        )
        return invoice
    except (ValueError, ValidationError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/invoices/overdue", response_model=InvoiceList)
async def get_overdue_invoices(
    pagination: PaginationParams = Depends(),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceList:
    """Get overdue invoices."""
    service = BillingService(db)

    # For non-admin users, only show their own overdue invoices
    user_id = None if current_user.role == "admin" else current_user.id

    result = await service.get_invoices(
        pagination=pagination,
        user_id=user_id,
        status=InvoiceStatus.OVERDUE,
            )
    return InvoiceList(**result)


@router.get("/invoices/pending", response_model=InvoiceList)
async def get_pending_invoices(
    pagination: PaginationParams = Depends(),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceList:
    """Get pending invoices."""
    service = BillingService(db)

    # For non-admin users, only show their own pending invoices
    user_id = None if current_user.role == "admin" else current_user.id

    result = await service.get_invoices(
        pagination=pagination,
        user_id=user_id,
        status=InvoiceStatus.PENDING,
            )
    return InvoiceList(**result)


@router.get("/invoices/paid", response_model=InvoiceList)
async def get_paid_invoices(
    pagination: PaginationParams = Depends(),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceList:
    """Get paid invoices."""
    service = BillingService(db)

    # For non-admin users, only show their own paid invoices
    user_id = None if current_user.role == "admin" else current_user.id

    result = await service.get_invoices(
        pagination=pagination,
        user_id=user_id,
        status=InvoiceStatus.PAID,
            )
    return InvoiceList(**result)


@router.get("/invoices/{invoice_id}", response_model=Invoice)
async def get_invoice(
    invoice_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Get invoice by ID."""
    service = BillingService(db)
    # TODO: Service method needs updating to support organization_id parameter
    invoice = await service.get_invoice_by_id(invoice_id, organization_id=org_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    # Users can only view their own invoices unless they're admin
    if current_user.role != "admin" and invoice.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this invoice"
        )
    
    return invoice


@router.patch("/invoices/{invoice_id}", response_model=Invoice)
async def update_invoice(
    invoice_id: int,
    invoice_data: InvoiceUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Update invoice."""
    service = BillingService(db)
    invoice = await service.update_invoice(invoice_id, invoice_data.dict(exclude_unset=True))
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    return invoice


@router.patch("/invoices/{invoice_id}/status", response_model=Invoice)
async def update_invoice_status(
    invoice_id: int,
    status: InvoiceStatus,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Update invoice status."""
    service = BillingService(db)
    invoice = await service.update_invoice_status(invoice_id, status)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    return invoice


@router.post("/invoices/generate", response_model=Dict[str, Any])
async def generate_invoices(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Manually trigger invoice generation for all active subscriptions."""
    service = BillingService(db)
    result = await service.generate_billing_cycle_invoices()
    return result


@router.post("/invoices/generate/subscription/{subscription_id}", response_model=Invoice)
async def generate_subscription_invoice(
    subscription_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Generate invoice for specific subscription."""
    service = BillingService(db)
    invoice = await service.generate_subscription_invoice(subscription_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found or invoice generation failed"
        )
    return invoice


# Invoice Items endpoints
@router.post("/invoices/{invoice_id}/items", response_model=InvoiceItem, status_code=status.HTTP_201_CREATED)
async def add_invoice_item(
    invoice_id: int,
    item_data: InvoiceItemCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> InvoiceItem:
    """Add item to invoice."""
    service = BillingService(db)
    item = await service.add_invoice_item(
        invoice_id=invoice_id,
        description=item_data.description,
        quantity=item_data.quantity,
        unit_price=item_data.unit_price,
        item_type=item_data.item_type,
    )
    return item


@router.patch("/invoice-items/{item_id}", response_model=InvoiceItem)
async def update_invoice_item(
    item_id: int,
    item_data: InvoiceItemUpdate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> InvoiceItem:
    """Update invoice item."""
    try:
        billing_service = BillingService(db)
        updated_item = await billing_service.update_invoice_item(item_id, item_data.dict(exclude_unset=True))
        
        if not updated_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice item not found"
            )
        
        return updated_item
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update invoice item: {str(e)}"
        )


@router.delete("/invoice-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice_item(
    item_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete invoice item."""
    try:
        billing_service = BillingService(db)
        success = await billing_service.delete_invoice_item(item_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice item not found"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete invoice item: {str(e)}"
        )


# Payment endpoints
@router.get("/payments", response_model=PaymentList)
async def get_payments(
    pagination: PaginationParams = Depends(),
    user_id: Optional[int] = Query(None),
    invoice_id: Optional[int] = Query(None),
    status: Optional[PaymentStatus] = Query(None),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentList:
    """Get all payments with pagination and filters."""
    # Users can only view their own payments unless they're admin
    if current_user.role != "admin" and user_id and user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's payments"
        )
    
    # Non-admin users can only view their own payments
    if current_user.role != "admin":
        user_id = current_user.id
    
    service = BillingService(db)
    result = await service.get_payments(
        pagination=pagination,
        user_id=user_id,
        invoice_id=invoice_id,
        status=status,
    )
    return PaymentList(**result)


@router.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_data: PaymentCreate,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Payment:
    """Create a new payment."""
    service = BillingService(db)
    # This endpoint is the admin "Record Payment" / manual-reconcile path: the
    # funds were already received out-of-band, so mark it manual → COMPLETED and
    # applied to the invoice (which activates the linked subscription).
    payment = await service.create_payment(
        user_id=payment_data.user_id,
        amount=payment_data.amount,
        payment_method=payment_data.payment_method,
        invoice_id=payment_data.invoice_id,
        transaction_id=payment_data.transaction_id,
        reference_number=payment_data.reference_number,
        notes=payment_data.notes,
        is_manual=True,
    )
    return payment


@router.get("/payments/{payment_id:int}", response_model=Payment)
async def get_payment(
    payment_id: int,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payment:
    """Get payment by ID."""
    service = BillingService(db)
    payment = await service.get_payment_by_id(payment_id)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )
    
    # Users can only view their own payments unless they're admin
    if current_user.role != "admin" and payment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this payment"
        )
    
    return payment


@router.get("/payments/history", response_model=List[Payment])
async def get_payment_history(
    limit: int = Query(50, ge=1, le=1000),
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Payment]:
    """Get payment history for current user."""
    service = BillingService(db)
    payments = await service.get_user_payment_history(current_user.id, limit)
    return payments


# MPESA endpoints
@router.post("/payments/mpesa/stk", response_model=MpesaPaymentResponse)
async def initiate_mpesa_stk(
    payment_request: MpesaPaymentRequest,
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MpesaPaymentResponse:
    """Initiate MPESA STK Push payment."""
    service = BillingService(db)
    result = await service.process_mpesa_payment(
        user_id=current_user.id,
        phone_number=payment_request.phone_number,
        amount=payment_request.amount,
        invoice_number=payment_request.invoice_number,
        description=payment_request.description,
    )
    return MpesaPaymentResponse(**result)


@router.post("/payments/mpesa/callback", response_model=MpesaCallbackResponse)
async def mpesa_callback(
    callback_data: MpesaCallbackRequest,
    db: AsyncSession = Depends(get_db),
) -> MpesaCallbackResponse:
    """MPESA payment callback webhook."""
    service = BillingService(db)
    result = await service.handle_mpesa_callback(callback_data.Body)
    return MpesaCallbackResponse(**result)


# Statistics endpoints
@router.get("/stats", response_model=BillingStats)
async def get_billing_stats(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> BillingStats:
    """Get billing statistics."""
    service = BillingService(db)
    stats = await service.get_billing_stats()
    return BillingStats(**stats)


@router.get("/payments/stats", response_model=PaymentStats)
async def get_payment_stats(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> PaymentStats:
    """Get payment statistics."""
    try:
        billing_service = BillingService(db)
        stats = await billing_service.get_payment_statistics()
        return PaymentStats(**stats)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get payment statistics: {str(e)}"
        )


@router.get("/invoices/overdue", response_model=List[Invoice])
async def get_overdue_invoices(
    org_id: int = Depends(get_org_id_for_query),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> List[Invoice]:
    """Get overdue invoices."""
    service = BillingService(db)
    invoices = await service.get_overdue_invoices()
    return invoices