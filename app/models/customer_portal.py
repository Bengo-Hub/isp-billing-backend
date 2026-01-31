"""Customer Portal models for Hotspot and PPPoE customer management."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Optional
import secrets
import string

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
    from .plan import ServicePlan
    from .user import User


class VoucherStatus(str, PyEnum):
    """Voucher status enumeration."""

    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SessionStatus(str, PyEnum):
    """Customer session status."""

    ACTIVE = "active"
    EXPIRED = "expired"
    DISCONNECTED = "disconnected"
    SUSPENDED = "suspended"


class VoucherCode(Base):
    """
    Voucher code for hotspot access.

    Pre-generated codes that can be sold or distributed to customers
    for immediate access to hotspot services.
    """

    __tablename__ = "voucher_codes"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Voucher details
    code = Column(String(50), unique=True, index=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)

    # Status
    status = Column(Enum(VoucherStatus), default=VoucherStatus.ACTIVE, nullable=False, index=True)
    is_used = Column(Boolean, default=False, nullable=False)

    # Usage
    used_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    used_at = Column(DateTime, nullable=True)
    used_mac_address = Column(String(17), nullable=True)  # MAC address when used
    used_ip_address = Column(String(45), nullable=True)

    # Validity
    expires_at = Column(DateTime, nullable=True)  # Expiry before use
    valid_from = Column(DateTime, nullable=True)  # Can only be used after this date

    # Value
    value = Column(Numeric(10, 2), nullable=True)  # Monetary value if sold

    # Hotspot credentials (auto-generated on purchase)
    hotspot_username = Column(String(50), nullable=True, index=True)  # e.g., C029, H0001
    hotspot_password = Column(String(20), nullable=True)  # e.g., 865, 1234

    # Batch info
    batch_id = Column(String(50), nullable=True, index=True)  # For batch generation
    batch_name = Column(String(100), nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    printed_at = Column(DateTime, nullable=True)  # When printed/exported
    sold_at = Column(DateTime, nullable=True)
    sold_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="voucher_codes")
    plan = relationship("ServicePlan", backref="vouchers")
    user = relationship("User", foreign_keys=[used_by], backref="used_vouchers")
    creator = relationship("User", foreign_keys=[created_by], backref="created_vouchers")
    seller = relationship("User", foreign_keys=[sold_by], backref="sold_vouchers")

    def __repr__(self) -> str:
        """String representation."""
        return f"<VoucherCode(id={self.id}, code='{self.code}', status={self.status})>"

    @staticmethod
    def generate_code(format_pattern: str = "XXXX-XXXX", length: int = 8) -> str:
        """
        Generate a random voucher code based on pattern.

        Format patterns:
        - X = alphanumeric uppercase
        - N = numeric only
        - A = letters only
        - Other characters are kept as-is

        Args:
            format_pattern: Pattern for the code (e.g., "XXXX-XXXX")
            length: Fallback length if pattern is empty

        Returns:
            Generated voucher code
        """
        if not format_pattern:
            # Default: random alphanumeric of specified length
            chars = string.ascii_uppercase + string.digits
            return ''.join(secrets.choice(chars) for _ in range(length))

        result = []
        for char in format_pattern:
            if char == 'X':
                result.append(secrets.choice(string.ascii_uppercase + string.digits))
            elif char == 'N':
                result.append(secrets.choice(string.digits))
            elif char == 'A':
                result.append(secrets.choice(string.ascii_uppercase))
            else:
                result.append(char)

        return ''.join(result)


class VoucherBatch(Base):
    """
    Batch of voucher codes for bulk generation.

    Tracks batch generation, printing, and sales.
    """

    __tablename__ = "voucher_batches"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Batch details
    batch_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Plan
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)

    # Quantity
    quantity = Column(Integer, nullable=False)
    used_count = Column(Integer, default=0, nullable=False)
    remaining_count = Column(Integer, nullable=False)

    # Value
    unit_price = Column(Numeric(10, 2), nullable=True)  # Selling price per voucher
    total_value = Column(Numeric(12, 2), nullable=True)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    # Export
    exported_at = Column(DateTime, nullable=True)
    export_format = Column(String(20), nullable=True)  # pdf, csv, print

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", backref="voucher_batches")
    plan = relationship("ServicePlan", backref="voucher_batches")
    creator = relationship("User", backref="created_batches")

    def __repr__(self) -> str:
        """String representation."""
        return f"<VoucherBatch(id={self.id}, batch_id='{self.batch_id}', quantity={self.quantity})>"


class CustomerSession(Base):
    """
    Customer session for hotspot access tracking.

    Tracks active hotspot sessions with MAC address, IP, and usage.
    """

    __tablename__ = "customer_sessions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Session details
    session_token = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Null for voucher-only
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)

    # Device info
    mac_address = Column(String(17), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    nas_ip_address = Column(String(45), nullable=True)  # Router IP
    nas_port = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    device_type = Column(String(50), nullable=True)  # mobile, desktop, tablet

    # Status
    status = Column(Enum(SessionStatus), default=SessionStatus.ACTIVE, nullable=False, index=True)

    # Session timing
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    last_activity_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Usage
    bytes_in = Column(Integer, default=0, nullable=False)  # Downloaded
    bytes_out = Column(Integer, default=0, nullable=False)  # Uploaded
    packets_in = Column(Integer, default=0, nullable=False)
    packets_out = Column(Integer, default=0, nullable=False)
    session_time = Column(Integer, default=0, nullable=False)  # Seconds

    # Plan details at session start
    plan_name = Column(String(100), nullable=True)
    speed_limit_up = Column(Integer, nullable=True)  # kbps
    speed_limit_down = Column(Integer, nullable=True)  # kbps
    data_limit = Column(Integer, nullable=True)  # bytes

    # Termination
    terminate_cause = Column(String(100), nullable=True)  # User-Request, Session-Timeout, etc.

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", backref="customer_sessions")
    user = relationship("User", backref="hotspot_sessions")
    subscription = relationship("Subscription", backref="hotspot_sessions")

    def __repr__(self) -> str:
        """String representation."""
        return f"<CustomerSession(id={self.id}, mac='{self.mac_address}', status={self.status})>"

    @property
    def is_active(self) -> bool:
        """Check if session is currently active."""
        if self.status != SessionStatus.ACTIVE:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    @property
    def total_bytes(self) -> int:
        """Get total bytes transferred."""
        return self.bytes_in + self.bytes_out

    @property
    def human_readable_usage(self) -> str:
        """Get human-readable usage string."""
        total = self.total_bytes
        if total < 1024:
            return f"{total} B"
        elif total < 1024 * 1024:
            return f"{total / 1024:.2f} KB"
        elif total < 1024 * 1024 * 1024:
            return f"{total / (1024 * 1024):.2f} MB"
        else:
            return f"{total / (1024 * 1024 * 1024):.2f} GB"


class CustomerPurchase(Base):
    """
    Customer purchase record for portal transactions.

    Records all customer purchases made through the portal.
    """

    __tablename__ = "customer_purchases"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Customer info
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Null for guest
    phone_number = Column(String(20), nullable=False, index=True)
    email = Column(String(100), nullable=True)
    mac_address = Column(String(17), nullable=True)

    # Purchase details
    plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)

    # Payment
    payment_method = Column(String(50), nullable=False)  # mpesa, card, voucher
    payment_reference = Column(String(100), nullable=True, index=True)
    payment_status = Column(String(50), nullable=False, index=True)  # pending, completed, failed
    transaction_id = Column(Integer, ForeignKey("payment_transactions.id"), nullable=True)

    # Result
    voucher_code_id = Column(Integer, ForeignKey("voucher_codes.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    session_id = Column(Integer, ForeignKey("customer_sessions.id"), nullable=True)

    # Additional data
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    extra_data = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization", backref="customer_purchases")
    user = relationship("User", backref="portal_purchases")
    plan = relationship("ServicePlan", backref="customer_purchases")
    transaction = relationship("PaymentTransaction", backref="customer_purchases")
    voucher = relationship("VoucherCode", backref="purchase")
    subscription = relationship("Subscription", backref="purchase")
    session = relationship("CustomerSession", backref="purchase")

    def __repr__(self) -> str:
        """String representation."""
        return f"<CustomerPurchase(id={self.id}, phone='{self.phone_number}', status={self.payment_status})>"
