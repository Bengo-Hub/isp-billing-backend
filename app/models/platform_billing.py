"""Platform Billing models for ISP provider subscription management.

RETIRED (Phase 3): the platform -> ISP-provider subscription/licence moved to
the central subscriptions-api (ISP_* plans) with treasury auto-invoicing. The
former local models ``PlatformSubscriptionTier`` / ``PlatformInvoice`` /
``PlatformPayment`` (and their endpoints) have been REMOVED. Only
``EarningsRecord`` (equity/earnings, out of scope) remains. The shared enums
(``BillingCycle``, ``TierType``, ``InvoiceStatus``, ``PaymentStatus``) are kept
as they are still imported by live billing code.
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
