"""Centipid licence management models."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Dict, Any, Optional

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


class LicenceStatus(str, PyEnum):
    """Licence status enumeration."""
    
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    PENDING_RENEWAL = "pending_renewal"
    TRIAL = "trial"


class LicenceType(str, PyEnum):
    """Licence type enumeration."""
    
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    TRIAL = "trial"
    CUSTOM = "custom"


class LicencePaymentStatus(str, PyEnum):
    """Licence payment status enumeration."""
    
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIAL = "partial"


class Licence(Base):
    """Centipid licence model for tracking software subscriptions."""

    __tablename__ = "licences"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Licence identification
    licence_key = Column(String(100), unique=True, nullable=False, index=True)
    licence_name = Column(String(100), nullable=False)
    licence_type = Column(Enum(LicenceType), nullable=False)
    
    # Status and validity
    status = Column(Enum(LicenceStatus), default=LicenceStatus.ACTIVE, nullable=False)
    issue_date = Column(DateTime, nullable=False)
    expiry_date = Column(DateTime, nullable=False)
    last_renewal_date = Column(DateTime, nullable=True)
    
    # Licence limits and features
    max_routers = Column(Integer, default=1, nullable=False)
    max_users = Column(Integer, default=100, nullable=False)
    max_concurrent_sessions = Column(Integer, default=50, nullable=False)
    features = Column(JSON, nullable=True)  # Available features
    
    # Billing information
    monthly_cost = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    billing_cycle_months = Column(Integer, default=1, nullable=False)
    
    # Usage tracking
    current_routers = Column(Integer, default=0, nullable=False)
    current_users = Column(Integer, default=0, nullable=False)
    total_transactions = Column(Integer, default=0, nullable=False)
    
    # Auto-renewal settings
    auto_renewal_enabled = Column(Boolean, default=True, nullable=False)
    renewal_reminder_days = Column(Integer, default=7, nullable=False)
    
    # Contact and organization
    organization_name = Column(String(200), nullable=True)
    contact_email = Column(String(100), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    
    # Additional information
    notes = Column(Text, nullable=True)
    licence_metadata = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    payments = relationship("LicencePayment", back_populates="licence", cascade="all, delete-orphan")
    usage_logs = relationship("LicenceUsageLog", back_populates="licence", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Licence(id={self.id}, key='{self.licence_key}', status='{self.status}')>"

    @property
    def is_expired(self) -> bool:
        """Check if licence is expired."""
        return datetime.utcnow() > self.expiry_date

    @property
    def days_until_expiry(self) -> int:
        """Get days until expiry."""
        if self.is_expired:
            return 0
        return (self.expiry_date - datetime.utcnow()).days

    @property
    def is_near_expiry(self) -> bool:
        """Check if licence is near expiry (within reminder days)."""
        return self.days_until_expiry <= self.renewal_reminder_days

    def get_features(self) -> Dict[str, Any]:
        """Get features as dictionary."""
        return self.features or {}

    def has_feature(self, feature_name: str) -> bool:
        """Check if licence has a specific feature."""
        features = self.get_features()
        return features.get(feature_name, False)

    def get_usage_percentage(self, resource_type: str) -> float:
        """Get usage percentage for a resource type."""
        if resource_type == "routers":
            if self.max_routers <= 0:
                return 0.0
            return (self.current_routers / self.max_routers) * 100
        elif resource_type == "users":
            if self.max_users <= 0:
                return 0.0
            return (self.current_users / self.max_users) * 100
        return 0.0


class LicencePayment(Base):
    """Licence payment tracking model."""

    __tablename__ = "licence_payments"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    licence_id = Column(Integer, ForeignKey("licences.id"), nullable=False)
    
    # Payment details
    payment_reference = Column(String(100), unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    payment_method = Column(String(50), nullable=False)
    
    # Payment status and processing
    status = Column(Enum(LicencePaymentStatus), default=LicencePaymentStatus.PENDING, nullable=False)
    payment_date = Column(DateTime, nullable=True)
    processed_date = Column(DateTime, nullable=True)
    
    # Billing period covered by this payment
    billing_period_start = Column(DateTime, nullable=False)
    billing_period_end = Column(DateTime, nullable=False)
    
    # External payment tracking
    external_transaction_id = Column(String(100), nullable=True)
    gateway_response = Column(Text, nullable=True)  # JSON response from payment gateway
    
    # Renewal information
    extends_licence_until = Column(DateTime, nullable=True)
    is_renewal = Column(Boolean, default=False, nullable=False)
    is_upgrade = Column(Boolean, default=False, nullable=False)
    
    # Additional information
    invoice_number = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    licence = relationship("Licence", back_populates="payments")

    def __repr__(self) -> str:
        """String representation."""
        return f"<LicencePayment(id={self.id}, reference='{self.payment_reference}', amount={self.amount})>"


class LicenceUsageLog(Base):
    """Licence usage tracking and analytics."""

    __tablename__ = "licence_usage_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    licence_id = Column(Integer, ForeignKey("licences.id"), nullable=False)
    
    # Usage metrics
    routers_count = Column(Integer, default=0, nullable=False)
    users_count = Column(Integer, default=0, nullable=False)
    active_sessions = Column(Integer, default=0, nullable=False)
    total_transactions = Column(Integer, default=0, nullable=False)
    data_transferred_gb = Column(Numeric(15, 3), default=0, nullable=False)
    
    # Revenue metrics
    daily_revenue = Column(Numeric(10, 2), default=0, nullable=False)
    monthly_revenue = Column(Numeric(10, 2), default=0, nullable=False)
    sms_balance = Column(Numeric(10, 2), default=0, nullable=False)
    
    # Performance metrics
    system_uptime_percentage = Column(Numeric(5, 2), default=0, nullable=False)
    average_response_time_ms = Column(Integer, default=0, nullable=False)
    error_rate_percentage = Column(Numeric(5, 2), default=0, nullable=False)
    
    # Feature usage
    features_used = Column(JSON, nullable=True)  # Track which features are being used
    api_calls_count = Column(Integer, default=0, nullable=False)
    
    # Log period
    log_date = Column(DateTime, nullable=False)
    log_type = Column(String(20), default="daily", nullable=False)  # daily, weekly, monthly
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    licence = relationship("Licence", back_populates="usage_logs")

    # Constraints
    __table_args__ = (
        UniqueConstraint('licence_id', 'log_date', 'log_type', name='uq_licence_usage_log'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<LicenceUsageLog(id={self.id}, licence_id={self.licence_id}, date={self.log_date})>"


class LicenceFeature(Base):
    """Available licence features and their configurations."""

    __tablename__ = "licence_features"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Feature identification
    feature_name = Column(String(100), unique=True, nullable=False, index=True)
    feature_code = Column(String(50), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    
    # Feature details
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    
    # Feature configuration
    is_core_feature = Column(Boolean, default=False, nullable=False)
    requires_additional_payment = Column(Boolean, default=False, nullable=False)
    additional_cost = Column(Numeric(10, 2), default=0, nullable=False)
    
    # Limits and restrictions
    usage_limit = Column(Integer, default=-1, nullable=False)  # -1 for unlimited
    limit_type = Column(String(20), nullable=True)  # daily, monthly, total
    
    # Availability
    available_in_trial = Column(Boolean, default=False, nullable=False)
    minimum_licence_type = Column(Enum(LicenceType), default=LicenceType.BASIC, nullable=False)
    
    # Metadata
    configuration_schema = Column(JSON, nullable=True)
    default_configuration = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<LicenceFeature(id={self.id}, name='{self.feature_name}', code='{self.feature_code}')>"


class LicenceAlert(Base):
    """Licence alerts and notifications."""

    __tablename__ = "licence_alerts"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    licence_id = Column(Integer, ForeignKey("licences.id"), nullable=False)
    
    # Alert details
    alert_type = Column(String(50), nullable=False)  # expiry, usage_limit, payment_due
    severity = Column(String(20), default="medium", nullable=False)  # low, medium, high, critical
    
    # Alert content
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    action_required = Column(String(100), nullable=True)
    
    # Alert status
    is_active = Column(Boolean, default=True, nullable=False)
    is_acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    
    # Alert triggers
    trigger_condition = Column(String(100), nullable=True)
    trigger_value = Column(String(50), nullable=True)
    
    # Notification tracking
    notification_sent = Column(Boolean, default=False, nullable=False)
    notification_sent_at = Column(DateTime, nullable=True)
    email_sent = Column(Boolean, default=False, nullable=False)
    sms_sent = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    licence = relationship("Licence", backref="alerts")
    acknowledged_by_user = relationship("User", backref="acknowledged_alerts")

    def __repr__(self) -> str:
        """String representation."""
        return f"<LicenceAlert(id={self.id}, type='{self.alert_type}', severity='{self.severity}')>"
