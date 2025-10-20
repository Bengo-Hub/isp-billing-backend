"""Billing and payment models."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

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
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class InvoiceStatus(str, PyEnum):
    """Invoice status enumeration."""

    DRAFT = "draft"
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, PyEnum):
    """Payment status enumeration."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    CHECKED = "checked"  # Payment verified by admin
    UNCHECKED = "unchecked"  # Payment needs verification


class PaymentMethod(str, PyEnum):
    """Payment method enumeration."""

    MPESA = "mpesa"
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


class Invoice(Base):
    """Invoice model."""

    __tablename__ = "invoices"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    
    # Invoice details
    invoice_number = Column(String(50), unique=True, index=True, nullable=False)
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT, nullable=False)
    
    # Amounts
    subtotal = Column(Numeric(10, 2), nullable=False)
    tax_amount = Column(Numeric(10, 2), default=0, nullable=False)
    discount_amount = Column(Numeric(10, 2), default=0, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    paid_amount = Column(Numeric(10, 2), default=0, nullable=False)
    balance = Column(Numeric(10, 2), nullable=False)
    
    # Dates
    issue_date = Column(DateTime, nullable=False)
    due_date = Column(DateTime, nullable=False)
    paid_date = Column(DateTime, nullable=True)
    
    # Billing period
    billing_period_start = Column(DateTime, nullable=True)
    billing_period_end = Column(DateTime, nullable=True)
    
    # Additional information
    currency = Column(String(3), default="KES", nullable=False)
    notes = Column(Text, nullable=True)
    terms = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="invoices")
    subscription = relationship("Subscription", backref="invoices")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def is_overdue(self) -> bool:
        """Check if invoice is overdue."""
        from datetime import datetime
        return (
            self.status == InvoiceStatus.PENDING
            and self.due_date < datetime.utcnow()
        )

    @property
    def is_fully_paid(self) -> bool:
        """Check if invoice is fully paid."""
        return self.paid_amount >= self.total_amount

    def __repr__(self) -> str:
        """String representation."""
        return f"<Invoice(id={self.id}, number='{self.invoice_number}', status='{self.status}')>"


class InvoiceItem(Base):
    """Invoice line items model."""

    __tablename__ = "invoice_items"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    description = Column(String(200), nullable=False)
    quantity = Column(Numeric(10, 2), default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    item_type = Column(String(50), nullable=True)  # subscription, setup, penalty, etc.

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    invoice = relationship("Invoice", back_populates="items")

    def __repr__(self) -> str:
        """String representation."""
        return f"<InvoiceItem(id={self.id}, invoice_id={self.invoice_id}, description='{self.description}')>"


class Payment(Base):
    """Payment model."""

    __tablename__ = "payments"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    
    # Payment details
    payment_number = Column(String(50), unique=True, index=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    
    # Payment processing
    transaction_id = Column(String(100), nullable=True)
    reference_number = Column(String(100), nullable=True)
    gateway_response = Column(Text, nullable=True)
    
    # MPESA specific fields
    mpesa_receipt_number = Column(String(50), nullable=True)
    mpesa_phone_number = Column(String(20), nullable=True)
    mpesa_transaction_date = Column(DateTime, nullable=True)
    
    # Dates
    payment_date = Column(DateTime, nullable=True)
    processed_date = Column(DateTime, nullable=True)
    
    # Additional information
    notes = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    
    # Payment verification and status tracking
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verification_notes = Column(Text, nullable=True)
    disbursement_method = Column(String(50), nullable=True)
    disbursement_reference = Column(String(100), nullable=True)
    
    # Manual payment fields
    is_manual_payment = Column(Boolean, default=False, nullable=False)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    receipt_image_url = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="payments", foreign_keys=[user_id])
    invoice = relationship("Invoice", back_populates="payments")
    verifier = relationship("User", foreign_keys=[verified_by], backref="verified_payments")
    recorder = relationship("User", foreign_keys=[recorded_by], backref="recorded_payments")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Payment(id={self.id}, number='{self.payment_number}', amount={self.amount})>"


class PaymentLog(Base):
    """Payment processing logs."""

    __tablename__ = "payment_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False)
    action = Column(String(50), nullable=False)  # initiated, completed, failed, etc.
    status = Column(String(20), nullable=False)
    details = Column(Text, nullable=True)
    gateway_response = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    payment = relationship("Payment", backref="logs")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PaymentLog(id={self.id}, payment_id={self.payment_id}, action='{self.action}')>"


class BillingCycle(Base):
    """Billing cycle configuration model."""

    __tablename__ = "billing_cycles"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    name = Column(String(100), nullable=False)
    cycle_type = Column(String(20), nullable=False)  # daily, weekly, monthly, etc.
    cycle_day = Column(Integer, nullable=False)  # day of month/week
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(Text, nullable=True)

    def __repr__(self) -> str:
        """String representation."""
        return f"<BillingCycle(id={self.id}, name='{self.name}', type='{self.cycle_type}')>"
