"""Payment transaction / manual-record / payout models for multi-tenant payment processing.

NOTE (Phase 3 cleanup): the ``PaymentGatewayConfig`` model (table
``payment_gateway_configs``) and its ``GatewayType`` / ``GatewayStatus`` /
``TransactionFeeType`` enums were REMOVED here — gateway configuration is now
owned by treasury-api. ``PaymentTransaction.gateway_id`` is retained as a plain
integer column (no FK) for historical reconciliation data; the live
payment-initiation/confirmation path runs through treasury-api.
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


class PaymentTransaction(Base):
    """
    Payment transaction record.

    Records all payment attempts and their status for auditing
    and reconciliation purposes.
    """

    __tablename__ = "payment_transactions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    # Historical gateway reference (FK removed — payment_gateway_configs dropped; treasury owns gateways).
    gateway_id = Column(Integer, nullable=True, index=True)

    # Transaction details
    transaction_reference = Column(String(100), unique=True, index=True, nullable=False)
    external_reference = Column(String(100), nullable=True, index=True)  # e.g., M-PESA receipt
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)

    # Transaction type
    transaction_type = Column(String(50), nullable=False)  # payment, refund, reversal

    # Status
    status = Column(String(50), nullable=False, index=True)  # pending, completed, failed, cancelled
    status_message = Column(Text, nullable=True)

    # Payment source
    phone_number = Column(String(20), nullable=True)  # For M-PESA
    account_reference = Column(String(100), nullable=True)

    # Related entities
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Customer who paid

    # Callback data
    callback_data = Column(JSON, nullable=True)  # Raw callback response
    processed_at = Column(DateTime, nullable=True)

    # Fees
    gateway_fee = Column(Numeric(10, 2), default=0, nullable=False)
    net_amount = Column(Numeric(10, 2), nullable=True)  # amount - gateway_fee

    # Additional data
    extra_data = Column(JSON, nullable=True)  # Additional transaction data
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    invoice = relationship("Invoice", backref="payment_transactions")
    subscription = relationship("Subscription", backref="payment_transactions")
    user = relationship("User", backref="payment_transactions")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PaymentTransaction(id={self.id}, ref={self.transaction_reference}, status={self.status})>"


class ManualPaymentRecord(Base):
    """
    Manual payment record for gateways without API integration.

    Used when ISPs receive payments manually and need to record them
    for reconciliation purposes.
    """

    __tablename__ = "manual_payment_records"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    # Historical gateway reference (FK removed — payment_gateway_configs dropped; treasury owns gateways).
    gateway_id = Column(Integer, nullable=True, index=True)

    # Transaction details
    mpesa_code = Column(String(20), nullable=True, index=True)  # M-PESA transaction code
    amount = Column(Numeric(10, 2), nullable=False)
    phone_number = Column(String(20), nullable=True)
    sender_name = Column(String(200), nullable=True)
    transaction_date = Column(DateTime, nullable=False)
    notes = Column(Text, nullable=True)

    # Matching
    is_matched = Column(Boolean, default=False, nullable=False)
    matched_transaction_id = Column(Integer, ForeignKey("payment_transactions.id"), nullable=True)
    matched_at = Column(DateTime, nullable=True)
    matched_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relationships
    organization = relationship("Organization", backref="manual_payment_records")
    matched_transaction = relationship("PaymentTransaction", backref="manual_records")

    def __repr__(self) -> str:
        """String representation."""
        return f"<ManualPaymentRecord(id={self.id}, mpesa_code={self.mpesa_code}, matched={self.is_matched})>"


class PayoutScheduleType(str, PyEnum):
    """Payout schedule type enumeration."""
    
    INSTANT = "instant"      # Immediate payout upon payment receipt
    DAILY = "daily"          # End of business day payout
    WEEKLY = "weekly"        # Weekly payout (configurable day)
    MONTHLY = "monthly"      # Monthly payout (configurable date)


class PayoutRecipientType(str, PyEnum):
    """
    Payout recipient type enumeration.
    Based on Paystack supported transfer recipient types.
    """
    
    # Nigeria - NUBAN (Nigerian Uniform Bank Account Number)
    NUBAN = "nuban"
    
    # Ghana - GHIPSS (Ghana Interbank Payment and Settlement Systems)
    GHIPSS = "ghipss"
    
    # Kenya - KEPSS (Kenya Electronic Payment and Settlement System)
    KEPSS = "kepss"
    
    # South Africa - BASA (Banking Association South Africa)
    BASA = "basa"
    
    # Mobile Money (Ghana, Kenya)
    MOBILE_MONEY = "mobile_money"
    
    # Mobile Money Business (Kenya - Paybill, Till)
    MOBILE_MONEY_BUSINESS = "mobile_money_business"
    
    # Authorization (Card-based payout via auth code)
    AUTHORIZATION = "authorization"


class PayoutStatus(str, PyEnum):
    """Payout status enumeration."""
    
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PayoutConfig(Base):
    """
    Payout configuration for an organization.
    
    Defines how and when collected payments are disbursed to the ISP's
    settlement account. Supports Paystack transfer recipients.
    """
    
    __tablename__ = "payout_configs"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True)
    
    # Schedule settings
    schedule_type = Column(Enum(PayoutScheduleType), default=PayoutScheduleType.DAILY, nullable=False)
    payout_day = Column(Integer, nullable=True)  # 1-7 for weekly (1=Monday), 1-28 for monthly
    payout_time = Column(String(10), default="17:00", nullable=False)  # COB time for daily payouts
    
    # Recipient details (Paystack transfer recipient)
    recipient_type = Column(Enum(PayoutRecipientType), default=PayoutRecipientType.KEPSS, nullable=False)
    recipient_code = Column(String(100), nullable=True)  # Paystack recipient code (RCP_xxx)
    recipient_name = Column(String(200), nullable=True)
    bank_code = Column(String(20), nullable=True)  # Bank or mobile money provider code
    bank_name = Column(String(100), nullable=True)
    account_number = Column(String(50), nullable=True)
    account_name = Column(String(200), nullable=True)
    currency = Column(String(3), default="KES", nullable=False)
    
    # For Mobile Money
    mobile_number = Column(String(20), nullable=True)
    
    # For authorization-based payouts
    authorization_code = Column(String(100), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    
    # Minimum payout threshold
    min_payout_amount = Column(Numeric(10, 2), default=1000, nullable=False)  # Minimum amount before payout
    
    # Fees
    payout_fee_percentage = Column(Numeric(5, 2), default=0, nullable=False)
    payout_fee_fixed = Column(Numeric(10, 2), default=0, nullable=False)
    
    # Stats
    total_payouts = Column(Integer, default=0, nullable=False)
    total_payout_amount = Column(Numeric(14, 2), default=0, nullable=False)
    last_payout_at = Column(DateTime, nullable=True)
    last_payout_amount = Column(Numeric(10, 2), nullable=True)
    
    # Error tracking
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    organization = relationship("Organization", backref="payout_config")
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<PayoutConfig(id={self.id}, org={self.organization_id}, schedule={self.schedule_type})>"
    
    @property
    def is_paystack_supported(self) -> bool:
        """Check if recipient type is Paystack supported."""
        return self.recipient_type in [
            PayoutRecipientType.NUBAN,
            PayoutRecipientType.GHIPSS,
            PayoutRecipientType.KEPSS,
            PayoutRecipientType.BASA,
            PayoutRecipientType.MOBILE_MONEY,
            PayoutRecipientType.MOBILE_MONEY_BUSINESS,
            PayoutRecipientType.AUTHORIZATION,
        ]
    
    def get_schedule_description(self) -> str:
        """Get human-readable schedule description."""
        if self.schedule_type == PayoutScheduleType.INSTANT:
            return "Instant payout upon payment receipt"
        elif self.schedule_type == PayoutScheduleType.DAILY:
            return f"Daily payout at {self.payout_time}"
        elif self.schedule_type == PayoutScheduleType.WEEKLY:
            days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            day_name = days[(self.payout_day or 1) - 1]
            return f"Weekly payout on {day_name} at {self.payout_time}"
        elif self.schedule_type == PayoutScheduleType.MONTHLY:
            suffix = "th"
            if self.payout_day == 1:
                suffix = "st"
            elif self.payout_day == 2:
                suffix = "nd"
            elif self.payout_day == 3:
                suffix = "rd"
            return f"Monthly payout on {self.payout_day}{suffix} at {self.payout_time}"
        return "Unknown schedule"


class PayoutRecord(Base):
    """
    Record of executed payouts.
    
    Tracks all payout transactions for auditing and reconciliation.
    """
    
    __tablename__ = "payout_records"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    payout_config_id = Column(Integer, ForeignKey("payout_configs.id"), nullable=False, index=True)
    
    # Payout details
    reference = Column(String(100), unique=True, index=True, nullable=False)
    transfer_code = Column(String(100), nullable=True, index=True)  # Paystack transfer code
    amount = Column(Numeric(10, 2), nullable=False)
    fee = Column(Numeric(10, 2), default=0, nullable=False)
    net_amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    
    # Period covered
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    transaction_count = Column(Integer, default=0, nullable=False)  # Number of transactions included
    
    # Status
    status = Column(Enum(PayoutStatus), default=PayoutStatus.PENDING, nullable=False, index=True)
    status_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    organization = relationship("Organization", backref="payout_records")
    payout_config = relationship("PayoutConfig", backref="payout_records")
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<PayoutRecord(id={self.id}, ref={self.reference}, amount={self.amount}, status={self.status})>"

