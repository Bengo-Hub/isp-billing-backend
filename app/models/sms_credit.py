"""SMS credit management models."""

from datetime import datetime
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


class SMSProviderType(str, PyEnum):
    """SMS provider type enumeration."""
    
    AFRICASTALKING = "africastalking"
    TWILIO = "twilio"
    SMS_GLOBAL = "sms_global"
    CUSTOM = "custom"


class SMSTransactionStatus(str, PyEnum):
    """SMS transaction status enumeration."""
    
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class SMSTransactionType(str, PyEnum):
    """SMS transaction type enumeration."""
    
    TOP_UP = "top_up"
    USAGE = "usage"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    BONUS = "bonus"


class SMSCreditAccount(Base):
    """SMS credit account for tracking SMS balances and usage."""

    __tablename__ = "sms_credit_accounts"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Account identification
    account_name = Column(String(100), nullable=False)
    account_code = Column(String(50), unique=True, nullable=False, index=True)
    provider_type = Column(Enum(SMSProviderType), nullable=False)
    
    # Account details
    phone_number = Column(String(20), nullable=False)
    country_code = Column(String(5), default="+254", nullable=False)
    provider_account_id = Column(String(100), nullable=True)
    
    # Balance tracking
    current_balance = Column(Numeric(10, 2), default=0, nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    minimum_balance_threshold = Column(Numeric(10, 2), default=100, nullable=False)
    
    # Usage statistics
    total_messages_sent = Column(Integer, default=0, nullable=False)
    total_amount_spent = Column(Numeric(10, 2), default=0, nullable=False)
    average_cost_per_sms = Column(Numeric(6, 4), default=0, nullable=False)
    
    # Account settings
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    auto_top_up_enabled = Column(Boolean, default=False, nullable=False)
    auto_top_up_amount = Column(Numeric(10, 2), default=500, nullable=False)
    auto_top_up_threshold = Column(Numeric(10, 2), default=50, nullable=False)
    
    # Provider configuration
    provider_config = Column(JSON, nullable=True)  # Provider-specific settings
    api_credentials = Column(Text, nullable=True)  # Encrypted credentials
    
    # Monitoring
    last_balance_check = Column(DateTime, nullable=True)
    last_successful_send = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    creator = relationship("User", backref="sms_credit_accounts")
    transactions = relationship("SMSTransaction", back_populates="account", cascade="all, delete-orphan")
    top_ups = relationship("SMSTopUp", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """String representation."""
        return f"<SMSCreditAccount(id={self.id}, name='{self.account_name}', balance={self.current_balance})>"

    @property
    def is_low_balance(self) -> bool:
        """Check if balance is below threshold."""
        return self.current_balance <= self.minimum_balance_threshold

    @property
    def needs_auto_top_up(self) -> bool:
        """Check if auto top-up should be triggered."""
        return (
            self.auto_top_up_enabled and 
            self.current_balance <= self.auto_top_up_threshold
        )

    def get_provider_config(self) -> Dict[str, Any]:
        """Get provider configuration as dictionary."""
        return self.provider_config or {}

    def update_balance(self, amount: Decimal, transaction_type: SMSTransactionType) -> None:
        """Update account balance."""
        if transaction_type in [SMSTransactionType.TOP_UP, SMSTransactionType.BONUS, SMSTransactionType.REFUND]:
            self.current_balance += amount
        elif transaction_type in [SMSTransactionType.USAGE, SMSTransactionType.ADJUSTMENT]:
            self.current_balance -= amount
            if self.current_balance < 0:
                self.current_balance = Decimal('0')


class SMSTransaction(Base):
    """SMS transaction history and tracking."""

    __tablename__ = "sms_transactions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Transaction identification
    transaction_id = Column(String(100), unique=True, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("sms_credit_accounts.id"), nullable=False)
    
    # Transaction details
    transaction_type = Column(Enum(SMSTransactionType), nullable=False)
    status = Column(Enum(SMSTransactionStatus), default=SMSTransactionStatus.PENDING, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    
    # SMS details (for usage transactions)
    recipient_phone = Column(String(20), nullable=True)
    message_content = Column(Text, nullable=True)
    message_length = Column(Integer, nullable=True)
    sms_count = Column(Integer, default=1, nullable=False)  # For long messages
    
    # Provider details
    provider_transaction_id = Column(String(100), nullable=True)
    provider_response = Column(JSON, nullable=True)
    delivery_status = Column(String(20), nullable=True)
    delivery_time = Column(DateTime, nullable=True)
    
    # Related records
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # User who triggered SMS
    notification_id = Column(Integer, ForeignKey("notifications.id"), nullable=True)
    top_up_id = Column(Integer, ForeignKey("sms_top_ups.id"), nullable=True)
    
    # Balance tracking
    balance_before = Column(Numeric(10, 2), nullable=False)
    balance_after = Column(Numeric(10, 2), nullable=False)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    
    # Relationships
    account = relationship("SMSCreditAccount", back_populates="transactions")
    user = relationship("User", backref="sms_transactions")
    notification = relationship("Notification", backref="sms_transactions")
    top_up = relationship("SMSTopUp", back_populates="transactions")

    def __repr__(self) -> str:
        """String representation."""
        return f"<SMSTransaction(id={self.id}, type='{self.transaction_type}', amount={self.amount})>"

    def get_provider_response(self) -> Dict[str, Any]:
        """Get provider response as dictionary."""
        return self.provider_response or {}


class SMSTopUp(Base):
    """SMS credit top-up records."""

    __tablename__ = "sms_top_ups"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Top-up identification
    top_up_reference = Column(String(100), unique=True, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("sms_credit_accounts.id"), nullable=False)
    
    # Top-up details
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)
    sms_credits = Column(Integer, nullable=False)  # Number of SMS credits purchased
    cost_per_sms = Column(Numeric(6, 4), nullable=False)
    
    # Payment details
    payment_method = Column(String(50), nullable=False)
    payment_reference = Column(String(100), nullable=True)
    external_transaction_id = Column(String(100), nullable=True)
    
    # Top-up status
    status = Column(Enum(SMSTransactionStatus), default=SMSTransactionStatus.PENDING, nullable=False)
    is_auto_top_up = Column(Boolean, default=False, nullable=False)
    
    # Processing details
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    
    # Provider details
    provider_order_id = Column(String(100), nullable=True)
    provider_response = Column(JSON, nullable=True)
    
    # Balance impact
    balance_before = Column(Numeric(10, 2), nullable=False)
    balance_after = Column(Numeric(10, 2), nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    account = relationship("SMSCreditAccount", back_populates="top_ups")
    requester = relationship("User", foreign_keys=[requested_by], backref="requested_sms_top_ups")
    approver = relationship("User", foreign_keys=[approved_by], backref="approved_sms_top_ups")
    transactions = relationship("SMSTransaction", back_populates="top_up")

    def __repr__(self) -> str:
        """String representation."""
        return f"<SMSTopUp(id={self.id}, reference='{self.top_up_reference}', amount={self.amount})>"

    def get_provider_response(self) -> Dict[str, Any]:
        """Get provider response as dictionary."""
        return self.provider_response or {}


class SMSCreditAlert(Base):
    """SMS credit alerts and notifications."""

    __tablename__ = "sms_credit_alerts"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    account_id = Column(Integer, ForeignKey("sms_credit_accounts.id"), nullable=False)
    
    # Alert details
    alert_type = Column(String(50), nullable=False)  # low_balance, failed_transaction, etc.
    severity = Column(String(20), default="medium", nullable=False)
    
    # Alert content
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    action_required = Column(String(100), nullable=True)
    
    # Alert status
    is_active = Column(Boolean, default=True, nullable=False)
    is_acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    
    # Trigger information
    trigger_balance = Column(Numeric(10, 2), nullable=True)
    trigger_transaction_id = Column(String(100), nullable=True)
    
    # Notification tracking
    notification_sent = Column(Boolean, default=False, nullable=False)
    email_sent = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    account = relationship("SMSCreditAccount", backref="alerts")
    acknowledged_by_user = relationship("User", backref="acknowledged_sms_alerts")

    def __repr__(self) -> str:
        """String representation."""
        return f"<SMSCreditAlert(id={self.id}, type='{self.alert_type}', severity='{self.severity}')>"


class PhoneNumberManagement(Base):
    """Phone number management and validation."""

    __tablename__ = "phone_number_management"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Phone number details
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    country_code = Column(String(5), nullable=False)
    formatted_number = Column(String(25), nullable=False)  # E.164 format
    
    # Validation status
    is_validated = Column(Boolean, default=False, nullable=False)
    validation_method = Column(String(20), nullable=True)  # sms, call, manual
    validation_date = Column(DateTime, nullable=True)
    validation_code = Column(String(10), nullable=True)
    validation_attempts = Column(Integer, default=0, nullable=False)
    
    # Number classification
    number_type = Column(String(20), nullable=True)  # mobile, landline, voip
    carrier = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    
    # Usage tracking
    associated_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    total_sms_sent = Column(Integer, default=0, nullable=False)
    last_sms_sent = Column(DateTime, nullable=True)
    
    # Delivery statistics
    successful_deliveries = Column(Integer, default=0, nullable=False)
    failed_deliveries = Column(Integer, default=0, nullable=False)
    delivery_rate = Column(Numeric(5, 2), default=0, nullable=False)
    
    # Preferences
    opt_in_marketing = Column(Boolean, default=False, nullable=False)
    opt_in_notifications = Column(Boolean, default=True, nullable=False)
    preferred_time_start = Column(String(5), default="08:00", nullable=False)  # HH:MM
    preferred_time_end = Column(String(5), default="20:00", nullable=False)  # HH:MM
    timezone = Column(String(50), default="Africa/Nairobi", nullable=False)
    
    # Blacklist and restrictions
    is_blacklisted = Column(Boolean, default=False, nullable=False)
    blacklist_reason = Column(String(200), nullable=True)
    blacklisted_at = Column(DateTime, nullable=True)
    blacklisted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    associated_user = relationship("User", foreign_keys=[associated_user_id], backref="managed_phone_numbers")
    blacklisted_by_user = relationship("User", foreign_keys=[blacklisted_by], backref="blacklisted_phone_numbers")

    def __repr__(self) -> str:
        """String representation."""
        return f"<PhoneNumberManagement(id={self.id}, number='{self.formatted_number}', validated={self.is_validated})>"

    @property
    def delivery_rate_percentage(self) -> float:
        """Calculate delivery rate percentage."""
        total_attempts = self.successful_deliveries + self.failed_deliveries
        if total_attempts == 0:
            return 0.0
        return (self.successful_deliveries / total_attempts) * 100

    def update_delivery_stats(self, success: bool) -> None:
        """Update delivery statistics."""
        if success:
            self.successful_deliveries += 1
            self.last_sms_sent = datetime.utcnow()
        else:
            self.failed_deliveries += 1
        
        # Recalculate delivery rate
        self.delivery_rate = self.delivery_rate_percentage

    def is_available_for_sending(self) -> bool:
        """Check if number is available for sending SMS."""
        if self.is_blacklisted or not self.is_validated:
            return False
        
        # Check preferred time (simplified - would need timezone handling)
        current_hour = datetime.utcnow().hour
        start_hour = int(self.preferred_time_start.split(':')[0])
        end_hour = int(self.preferred_time_end.split(':')[0])
        
        return start_hour <= current_hour <= end_hour


class SMSGatewayStatus(str, PyEnum):
    """SMS gateway status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VERIFICATION = "pending_verification"
    ERROR = "error"


class SMSGatewayConfig(Base):
    """
    SMS gateway configuration for platform-level SMS sending.

    When organization_id is NULL, this is a platform-level gateway
    that handles SMS for the entire platform.

    When organization_id is set, this is an organization-specific gateway.
    Credentials are stored encrypted.
    """

    __tablename__ = "sms_gateway_configs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # NULL = platform-level gateway (handles all SMS)
    # Set = organization-specific gateway
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

    # Gateway information
    provider_type = Column(Enum(SMSProviderType), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # Display name (e.g., "Twilio SMS")
    description = Column(Text, nullable=True)

    # Status
    status = Column(Enum(SMSGatewayStatus), default=SMSGatewayStatus.PENDING_VERIFICATION, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)

    # Environment (sandbox/production)
    environment = Column(String(20), default="sandbox", nullable=False)

    # Credentials (encrypted JSON)
    credentials = Column(Text, nullable=True)  # Encrypted JSON with API keys, secrets

    # Provider-specific settings
    default_sender_id = Column(String(50), nullable=True)  # Default sender phone/alphanumeric ID
    webhook_url = Column(String(500), nullable=True)  # For delivery status callbacks

    # Usage stats
    total_messages = Column(Integer, default=0, nullable=False)
    total_cost = Column(Numeric(14, 2), default=0, nullable=False)
    last_message_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    verified_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization", backref="sms_gateways")

    # Constraints
    __table_args__ = (
        UniqueConstraint('organization_id', 'provider_type', name='uq_org_sms_provider'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<SMSGatewayConfig(id={self.id}, org={self.organization_id}, type={self.provider_type})>"

    def get_display_name(self) -> str:
        """Get user-friendly display name for gateway."""
        type_names = {
            SMSProviderType.TWILIO: "Twilio",
            SMSProviderType.AFRICASTALKING: "Africa's Talking",
            SMSProviderType.SMS_GLOBAL: "SMS Global",
            SMSProviderType.CUSTOM: "Custom Provider",
        }
        return type_names.get(self.provider_type, self.provider_type.value)


class SMSCreditUsageStats(Base):
    """SMS credit usage statistics and analytics."""

    __tablename__ = "sms_credit_usage_stats"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    account_id = Column(Integer, ForeignKey("sms_credit_accounts.id"), nullable=False)
    
    # Statistics period
    stats_date = Column(DateTime, nullable=False)
    period_type = Column(String(20), default="daily", nullable=False)  # daily, weekly, monthly
    
    # Usage metrics
    messages_sent = Column(Integer, default=0, nullable=False)
    messages_delivered = Column(Integer, default=0, nullable=False)
    messages_failed = Column(Integer, default=0, nullable=False)
    total_cost = Column(Numeric(10, 2), default=0, nullable=False)
    average_cost_per_sms = Column(Numeric(6, 4), default=0, nullable=False)
    
    # Performance metrics
    delivery_rate = Column(Numeric(5, 2), default=0, nullable=False)
    average_delivery_time_seconds = Column(Integer, default=0, nullable=False)
    
    # Usage breakdown
    notification_sms = Column(Integer, default=0, nullable=False)
    marketing_sms = Column(Integer, default=0, nullable=False)
    verification_sms = Column(Integer, default=0, nullable=False)
    alert_sms = Column(Integer, default=0, nullable=False)
    
    # Top-up tracking
    top_ups_count = Column(Integer, default=0, nullable=False)
    top_ups_amount = Column(Numeric(10, 2), default=0, nullable=False)
    
    # Balance tracking
    starting_balance = Column(Numeric(10, 2), nullable=False)
    ending_balance = Column(Numeric(10, 2), nullable=False)
    lowest_balance = Column(Numeric(10, 2), nullable=False)
    highest_balance = Column(Numeric(10, 2), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    account = relationship("SMSCreditAccount", backref="usage_stats")

    # Constraints
    __table_args__ = (
        UniqueConstraint('account_id', 'stats_date', 'period_type', name='uq_sms_stats_account_date'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<SMSCreditUsageStats(id={self.id}, account_id={self.account_id}, date={self.stats_date})>"
