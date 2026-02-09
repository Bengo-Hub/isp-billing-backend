"""Platform Billing schemas for API requests and responses."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.platform_billing import BillingCycle, TierType, InvoiceStatus, PaymentStatus


class SubscriptionTierBase(BaseModel):
    """Base schema for subscription tier."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    tier_type: TierType
    base_monthly_fee: Decimal = Field(..., ge=0)
    base_quarterly_fee: Optional[Decimal] = None
    base_yearly_fee: Optional[Decimal] = None
    currency: str = "KES"
    earnings_threshold: Decimal = Field(default=10000, ge=0)
    earnings_percentage: Decimal = Field(default=2.0, ge=0, le=100)
    min_customers: int = Field(default=0, ge=0)
    max_customers: Optional[int] = None
    per_customer_fee: Optional[Decimal] = None
    max_routers: int = Field(default=5, ge=1)
    max_staff_users: int = Field(default=3, ge=1)
    max_sms_per_month: int = Field(default=100, ge=0)
    features: Dict[str, Any] = Field(default_factory=dict)
    trial_days: int = Field(default=14, ge=0)
    display_order: int = Field(default=0, ge=0)
    badge_text: Optional[str] = None
    badge_color: Optional[str] = None


class SubscriptionTierCreate(SubscriptionTierBase):
    """Schema for creating a subscription tier."""

    is_active: bool = True
    is_default: bool = False


class SubscriptionTierUpdate(BaseModel):
    """Schema for updating a subscription tier."""

    name: Optional[str] = None
    description: Optional[str] = None
    base_monthly_fee: Optional[Decimal] = None
    base_quarterly_fee: Optional[Decimal] = None
    base_yearly_fee: Optional[Decimal] = None
    earnings_threshold: Optional[Decimal] = None
    earnings_percentage: Optional[Decimal] = None
    min_customers: Optional[int] = None
    max_customers: Optional[int] = None
    per_customer_fee: Optional[Decimal] = None
    max_routers: Optional[int] = None
    max_staff_users: Optional[int] = None
    max_sms_per_month: Optional[int] = None
    features: Optional[Dict[str, Any]] = None
    trial_days: Optional[int] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    display_order: Optional[int] = None
    badge_text: Optional[str] = None
    badge_color: Optional[str] = None


class SubscriptionTierResponse(SubscriptionTierBase):
    """Response schema for subscription tier."""

    id: int
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PlatformInvoiceCreate(BaseModel):
    """Schema for creating a platform invoice."""

    organization_id: int
    billing_cycle: BillingCycle = BillingCycle.MONTHLY
    billing_period_start: datetime
    billing_period_end: datetime
    notes: Optional[str] = None


class PlatformInvoiceResponse(BaseModel):
    """Response schema for platform invoice."""

    id: int
    organization_id: int
    organization_name: Optional[str] = None
    invoice_number: str
    billing_cycle: BillingCycle
    billing_period_start: datetime
    billing_period_end: datetime
    tier_id: Optional[int]
    base_fee: Decimal
    earnings_during_period: Decimal
    earnings_fee: Decimal
    customer_count: int
    customer_fee: Decimal
    additional_fees: Decimal
    discount: Decimal
    tax: Decimal
    total_amount: Decimal
    currency: str = "KES"
    status: InvoiceStatus
    due_date: datetime
    paid_at: Optional[datetime]
    paystack_reference: Optional[str]
    notes: Optional[str]
    pdf_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PlatformPaymentCreate(BaseModel):
    """Schema for recording a platform payment."""

    invoice_id: int
    amount: Decimal = Field(..., gt=0)
    paystack_reference: Optional[str] = None
    paystack_authorization_code: Optional[str] = None
    paystack_channel: Optional[str] = None


class PlatformPaymentResponse(BaseModel):
    """Response schema for platform payment."""

    id: int
    invoice_id: int
    organization_id: int
    organization_name: Optional[str] = None
    payment_reference: str
    amount: Decimal
    currency: str
    paystack_reference: Optional[str]
    paystack_channel: Optional[str]
    card_last4: Optional[str]
    card_brand: Optional[str]
    status: PaymentStatus
    status_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class EarningsReportResponse(BaseModel):
    """Response schema for earnings report."""

    organization_id: int
    period_start: datetime
    period_end: datetime
    total_transactions: int
    total_amount: Decimal
    net_amount: Decimal
    refunded_amount: Decimal
    new_customers: int
    active_customers: int
    churned_customers: int
    daily_breakdown: List[Dict[str, Any]]


class OrganizationBillingStatus(BaseModel):
    """Schema for organization billing status."""

    organization_id: int
    organization_name: str
    tier_name: Optional[str]
    tier_type: Optional[TierType]
    is_trial: bool
    trial_days_remaining: int
    is_subscription_active: bool
    subscription_ends_at: Optional[datetime]
    current_month_earnings: Decimal
    pending_invoice_amount: Optional[Decimal]
    overdue_invoice_count: int
    last_payment_date: Optional[datetime]


class BillingDashboardStats(BaseModel):
    """Schema for billing dashboard statistics."""

    total_organizations: int
    active_organizations: int
    trial_organizations: int
    suspended_organizations: int
    total_monthly_revenue: Decimal
    pending_payments: Decimal
    overdue_payments: Decimal
    new_signups_this_month: int
    churn_this_month: int
    average_revenue_per_org: Decimal


class InvoiceGenerationRequest(BaseModel):
    """Request schema for generating invoices."""

    organization_ids: Optional[List[int]] = None  # None means all organizations
    billing_period_start: datetime
    billing_period_end: datetime
    send_notifications: bool = True
