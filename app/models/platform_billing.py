"""Platform Billing models for ISP provider subscription management.

DEPRECATED (Phase 3): the platform -> ISP-provider subscription/licence is
migrating to the central subscriptions-api (ISP_* plans) with treasury
auto-invoicing. These local models (PlatformSubscriptionTier, PlatformInvoice,
etc.) and their endpoints are kept INTACT during the migration so the running
platform-billing UI keeps working. Do NOT delete; retire once every ISP provider
tenant is subscribed via subscriptions-api.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base

if TYPE_CHECKING:
    from .organization import Organization


class BillingCycle(str, PyEnum):
    """Billing cycle enumeration."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class TierType(str, PyEnum):
    """Subscription tier type."""

    HOTSPOT = "hotspot"
    PPPOE = "pppoe"


class InvoiceStatus(str, PyEnum):
    """Platform invoice status."""

    DRAFT = "draft"
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, PyEnum):
    """Platform payment status."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PlatformSubscriptionTier(Base):
    """
    Platform subscription tiers for ISP providers.

    Defines pricing, limits, and features for each tier.
    Hotspot: Base 500 KES + 2% on earnings above 10k
    PPPoE: Tiered pricing based on customer count (25 bob per customer))
    """

    __tablename__ = "platform_subscription_tiers"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Tier information
    name = Column(String(100), nullable=False)  # e.g., "Basic", "Professional", "Enterprise"
    description = Column(Text, nullable=True)
    tier_type = Column(Enum(TierType), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    # Pricing - Base fee
    base_monthly_fee = Column(Numeric(10, 2), nullable=False)  # e.g., 500 KES
    base_quarterly_fee = Column(Numeric(10, 2), nullable=True)
    base_yearly_fee = Column(Numeric(10, 2), nullable=True)  # Discount for yearly
    currency = Column(String(3), default="KES", nullable=False)

    # Earnings-based pricing (for Hotspot)
    earnings_threshold = Column(Numeric(12, 2), default=10000, nullable=False)  # 10,000 KES
    earnings_percentage = Column(Numeric(5, 2), default=2.0, nullable=False)  # 2%

    # PPPoE tiered pricing (customer count based)
    min_customers = Column(Integer, default=0, nullable=False)
    max_customers = Column(Integer, nullable=True)  # null = unlimited
    per_customer_fee = Column(Numeric(6, 2), default=0, nullable=True)

    # Limits
    max_routers = Column(Integer, default=5, nullable=False)
    max_staff_users = Column(Integer, default=3, nullable=False)  # Admin/technician
    max_sms_per_month = Column(Integer, default=100, nullable=False)

    # Features (JSON object with feature flags)
    features = Column(JSON, default=dict, nullable=False)
    # Example features:
    # {
    #   "custom_domain": true,
    #   "white_label": true,
    #   "api_access": true,
    #   "priority_support": true,
    #   "advanced_analytics": true,
    #   "multi_router": true,
    #   "voucher_system": true,
    #   "sms_notifications": true
    # }

    # Trial settings
    trial_days = Column(Integer, default=14, nullable=False)
    trial_features = Column(JSON, nullable=True)  # Limited features during trial

    # Display
    display_order = Column(Integer, default=0, nullable=False)
    badge_text = Column(String(50), nullable=True)  # e.g., "Most Popular"
    badge_color = Column(String(7), nullable=True)  # e.g., "#ec4899"

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organizations = relationship("Organization", back_populates="subscription_tier")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PlatformSubscriptionTier(id={self.id}, name='{self.name}', type={self.tier_type})>"

    def calculate_monthly_fee(self, earnings: float = 0, customer_count: int = 0) -> float:
        """
        Calculate total monthly fee based on tier type.

        For Hotspot: base_fee + 2% of earnings above threshold
        For PPPoE: base_fee + per_customer_fee * customer_count (if applicable)
        """
        total = float(self.base_monthly_fee)

        if self.tier_type == TierType.HOTSPOT:
            if earnings > float(self.earnings_threshold):
                excess = earnings - float(self.earnings_threshold)
                earnings_fee = excess * (float(self.earnings_percentage) / 100)
                total += earnings_fee

        elif self.tier_type == TierType.PPPOE:
            if self.per_customer_fee and customer_count > 0:
                total += float(self.per_customer_fee) * customer_count

        return round(total, 2)


class PlatformInvoice(Base):
    """
    Platform invoice for ISP provider subscription billing.

    Auto-generated monthly/yearly based on subscription tier and earnings.
    """

    __tablename__ = "platform_invoices"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Invoice details
    invoice_number = Column(String(50), unique=True, index=True, nullable=False)
    billing_cycle = Column(Enum(BillingCycle), default=BillingCycle.MONTHLY, nullable=False)
    billing_period_start = Column(DateTime, nullable=False)
    billing_period_end = Column(DateTime, nullable=False)

    # Fee breakdown
    tier_id = Column(Integer, ForeignKey("platform_subscription_tiers.id"), nullable=True)
    base_fee = Column(Numeric(10, 2), nullable=False)  # Subscription base fee
    earnings_during_period = Column(Numeric(14, 2), default=0, nullable=False)  # ISP's earnings
    earnings_fee = Column(Numeric(10, 2), default=0, nullable=False)  # 2% of excess earnings
    customer_count = Column(Integer, default=0, nullable=False)  # For PPPoE tiered
    customer_fee = Column(Numeric(10, 2), default=0, nullable=False)  # Per-customer fees
    additional_fees = Column(Numeric(10, 2), default=0, nullable=False)  # SMS, API overages
    discount = Column(Numeric(10, 2), default=0, nullable=False)
    tax = Column(Numeric(10, 2), default=0, nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)

    # Status
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.PENDING, nullable=False, index=True)
    due_date = Column(DateTime, nullable=False)
    paid_at = Column(DateTime, nullable=True)

    # Payment reference
    paystack_reference = Column(String(100), nullable=True)
    paystack_authorization_code = Column(String(100), nullable=True)

    # Notes
    notes = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)

    # PDF
    pdf_url = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="platform_invoices")
    tier = relationship("PlatformSubscriptionTier")
    payments = relationship("PlatformPayment", back_populates="invoice")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PlatformInvoice(id={self.id}, invoice_number='{self.invoice_number}', status={self.status})>"


class PlatformPayment(Base):
    """
    Platform payment record for ISP subscription payments.

    Payments collected via Platform's Paystack account.
    """

    __tablename__ = "platform_payments"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("platform_invoices.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Payment details
    payment_reference = Column(String(100), unique=True, index=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)

    # Paystack details
    paystack_reference = Column(String(100), nullable=True, index=True)
    paystack_authorization_code = Column(String(100), nullable=True)
    paystack_channel = Column(String(50), nullable=True)  # card, mobile_money, bank
    card_last4 = Column(String(4), nullable=True)
    card_brand = Column(String(20), nullable=True)

    # Status
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True)
    status_message = Column(Text, nullable=True)

    # Callback data
    callback_data = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    invoice = relationship("PlatformInvoice", back_populates="payments")
    organization = relationship("Organization", backref="platform_payments")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PlatformPayment(id={self.id}, ref='{self.payment_reference}', status={self.status})>"


class EarningsRecord(Base):
    """
    Daily earnings record for ISP providers.

    Used to calculate monthly earnings-based platform fees.
    """

    __tablename__ = "earnings_records"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Earnings details
    date = Column(DateTime, nullable=False, index=True)
    total_transactions = Column(Integer, default=0, nullable=False)
    total_amount = Column(Numeric(14, 2), default=0, nullable=False)
    net_amount = Column(Numeric(14, 2), default=0, nullable=False)  # After gateway fees
    refunded_amount = Column(Numeric(14, 2), default=0, nullable=False)

    # Breakdown by gateway
    mpesa_amount = Column(Numeric(14, 2), default=0, nullable=False)
    paystack_amount = Column(Numeric(14, 2), default=0, nullable=False)
    other_amount = Column(Numeric(14, 2), default=0, nullable=False)

    # Customer stats
    new_customers = Column(Integer, default=0, nullable=False)
    active_customers = Column(Integer, default=0, nullable=False)
    churned_customers = Column(Integer, default=0, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Constraints
    __table_args__ = (
        UniqueConstraint('organization_id', 'date', name='uq_earnings_org_date'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<EarningsRecord(id={self.id}, org={self.organization_id}, date={self.date.date()})>"
