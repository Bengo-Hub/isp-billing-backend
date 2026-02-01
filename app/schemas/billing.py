"""Billing and payment-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.billing import InvoiceStatus, PaymentStatus, PaymentMethod


class InvoiceItemBase(BaseModel):
    """Base invoice item schema."""

    description: str = Field(..., min_length=1, max_length=255)
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    item_type: str = Field("subscription", max_length=50)

    @validator("item_type")
    def validate_item_type(cls, v):
        """Validate item type."""
        allowed_types = ["subscription", "setup", "equipment", "other"]
        if v not in allowed_types:
            raise ValueError(f"Item type must be one of: {', '.join(allowed_types)}")
        return v


class InvoiceItemCreate(InvoiceItemBase):
    """Schema for creating an invoice item."""
    pass


class InvoiceItemUpdate(BaseModel):
    """Schema for updating an invoice item."""

    description: Optional[str] = Field(None, min_length=1, max_length=255)
    quantity: Optional[Decimal] = Field(None, gt=0)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    item_type: Optional[str] = Field(None, max_length=50)

    @validator("item_type")
    def validate_item_type(cls, v):
        """Validate item type."""
        if v:
            allowed_types = ["subscription", "setup", "equipment", "other"]
            if v not in allowed_types:
                raise ValueError(f"Item type must be one of: {', '.join(allowed_types)}")
        return v


class InvoiceItem(InvoiceItemBase):
    """Schema for invoice item response."""

    id: int
    invoice_id: int
    total_price: Decimal
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InvoiceBase(BaseModel):
    """Base invoice schema."""

    user_id: int = Field(..., gt=0)
    subscription_id: Optional[int] = Field(None, gt=0)
    subtotal: Decimal = Field(..., ge=0)
    tax_amount: Decimal = Field(0, ge=0)
    discount_amount: Decimal = Field(0, ge=0)
    billing_period_start: Optional[datetime] = None
    billing_period_end: Optional[datetime] = None
    notes: Optional[str] = None

    @validator("billing_period_end")
    def validate_billing_period_end(cls, v, values):
        """Validate billing period end is after start."""
        if v and "billing_period_start" in values and values["billing_period_start"]:
            if v <= values["billing_period_start"]:
                raise ValueError("Billing period end must be after start")
        return v


class InvoiceCreate(InvoiceBase):
    """Schema for creating an invoice."""
    pass


class InvoiceUpdate(BaseModel):
    """Schema for updating an invoice."""

    subtotal: Optional[Decimal] = Field(None, ge=0)
    tax_amount: Optional[Decimal] = Field(None, ge=0)
    discount_amount: Optional[Decimal] = Field(None, ge=0)
    billing_period_start: Optional[datetime] = None
    billing_period_end: Optional[datetime] = None
    notes: Optional[str] = None


class InvoiceInDB(InvoiceBase):
    """Schema for invoice in database."""

    id: int
    invoice_number: str
    total_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    issue_date: datetime
    due_date: datetime
    paid_date: Optional[datetime] = None
    status: InvoiceStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Invoice(InvoiceInDB):
    """Schema for invoice response."""

    items: List[InvoiceItem] = []


class InvoiceList(BaseModel):
    """Schema for invoice list response."""

    invoices: List[Invoice]
    total: int
    page: int
    size: int
    pages: int


class InvoiceFilter(BaseModel):
    """Schema for invoice filters."""

    user_id: Optional[int] = None
    status: Optional[InvoiceStatus] = None
    search: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None


class PaymentBase(BaseModel):
    """Base payment schema."""

    user_id: int = Field(..., gt=0)
    invoice_id: Optional[int] = Field(None, gt=0)
    amount: Decimal = Field(..., gt=0)
    payment_method: PaymentMethod
    transaction_id: Optional[str] = Field(None, max_length=100)
    reference_number: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class PaymentCreate(PaymentBase):
    """Schema for creating a payment."""
    pass


class PaymentUpdate(BaseModel):
    """Schema for updating a payment."""

    amount: Optional[Decimal] = Field(None, gt=0)
    payment_method: Optional[PaymentMethod] = None
    transaction_id: Optional[str] = Field(None, max_length=100)
    reference_number: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class PaymentInDB(PaymentBase):
    """Schema for payment in database."""

    id: int
    payment_number: str
    status: PaymentStatus
    payment_date: Optional[datetime] = None
    processed_date: Optional[datetime] = None
    mpesa_receipt_number: Optional[str] = None
    mpesa_phone_number: Optional[str] = None
    mpesa_transaction_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Payment(PaymentInDB):
    """Schema for payment response."""
    pass


class PaymentList(BaseModel):
    """Schema for payment list response."""

    payments: List[Payment]
    total: int
    page: int
    size: int
    pages: int


class PaymentFilter(BaseModel):
    """Schema for payment filters."""

    user_id: Optional[int] = None
    invoice_id: Optional[int] = None
    status: Optional[PaymentStatus] = None
    payment_method: Optional[PaymentMethod] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class MpesaPaymentRequest(BaseModel):
    """Schema for MPESA payment request."""

    phone_number: str = Field(..., min_length=10, max_length=15)
    amount: int = Field(..., gt=0, le=70000)  # MPESA limit
    invoice_number: str = Field(..., min_length=1, max_length=50)
    description: str = Field("Payment for internet service", max_length=255)

    @validator("phone_number")
    def validate_phone_number(cls, v):
        """Validate phone number format."""
        import re
        # Remove any non-digit characters
        phone = re.sub(r'\D', '', v)
        # Check if it's a valid Kenyan phone number
        if not re.match(r'^(254|0)[0-9]{9}$', phone):
            raise ValueError("Invalid phone number format")
        return phone


class MpesaPaymentResponse(BaseModel):
    """Schema for MPESA payment response."""

    success: bool
    payment_id: Optional[int] = None
    payment_number: Optional[str] = None
    merchant_request_id: Optional[str] = None
    checkout_request_id: Optional[str] = None
    customer_message: Optional[str] = None
    error: Optional[str] = None


class MpesaCallbackRequest(BaseModel):
    """Schema for MPESA callback request."""

    Body: Dict[str, Any]


class MpesaCallbackResponse(BaseModel):
    """Schema for MPESA callback response."""

    success: bool
    message: str
    payment_id: Optional[int] = None
    error: Optional[str] = None


class BillingStats(BaseModel):
    """Schema for billing statistics."""

    total_invoices: int
    paid_invoices: int
    pending_invoices: int
    overdue_invoices: int
    total_revenue: float
    pending_revenue: float
    collection_rate: float


class PaymentStats(BaseModel):
    """Schema for payment statistics."""

    total_payments: int
    successful_payments: int
    failed_payments: int
    pending_payments: int
    total_amount: float
    mpesa_payments: int
    cash_payments: int
    bank_transfer_payments: int
    daily_earnings: float
    weekly_earnings: float
    monthly_earnings: float


class InvoiceGenerationRequest(BaseModel):
    """Schema for invoice generation request."""

    subscription_id: int
    billing_period_start: Optional[datetime] = None
    billing_period_end: Optional[datetime] = None
    notes: Optional[str] = None


class BulkInvoiceGenerationRequest(BaseModel):
    """Schema for bulk invoice generation request."""

    subscription_ids: List[int] = Field(..., min_items=1)
    billing_period_start: Optional[datetime] = None
    billing_period_end: Optional[datetime] = None
    notes: Optional[str] = None
