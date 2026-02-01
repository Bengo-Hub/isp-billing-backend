"""WhatsApp messaging models for platform and organization-level management."""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Dict, Any

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


class WhatsAppProviderType(str, PyEnum):
    """WhatsApp provider type enumeration."""

    APIWAP = "apiwap"
    TWILIO_WHATSAPP = "twilio_whatsapp"
    CUSTOM = "custom"


class WhatsAppGatewayStatus(str, PyEnum):
    """WhatsApp gateway status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VERIFICATION = "pending_verification"
    ERROR = "error"


class WhatsAppSubscriptionStatus(str, PyEnum):
    """WhatsApp subscription status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"


class WhatsAppTransactionStatus(str, PyEnum):
    """WhatsApp transaction status enumeration."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class WhatsAppGatewayConfig(Base):
    """
    WhatsApp gateway configuration for platform-level WhatsApp messaging.

    Platform owner configures APIWAP API keys here.
    ISP providers don't see or manage these credentials - they just
    select APIWAP as their provider and subscribe.

    When organization_id is NULL: Platform-level gateway (default)
    When organization_id is set: Reserved for future org-specific gateways
    """

    __tablename__ = "whatsapp_gateway_configs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # NULL = platform-level gateway (managed by platform owner)
    # Set = organization-specific gateway (future feature)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

    # Gateway information
    provider_type = Column(Enum(WhatsAppProviderType), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # Display name (e.g., "APIWAP WhatsApp")
    description = Column(Text, nullable=True)

    # Status
    status = Column(Enum(WhatsAppGatewayStatus), default=WhatsAppGatewayStatus.PENDING_VERIFICATION, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)

    # Environment (sandbox/production)
    environment = Column(String(20), default="production", nullable=False)

    # Credentials (encrypted JSON) - managed by platform owner only
    credentials = Column(Text, nullable=True)  # Encrypted JSON with API keys
    # Example: {"api_key": "encrypted_apiwap_key"}

    # Provider-specific settings
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
    organization = relationship("Organization", backref="whatsapp_gateways")

    # Constraints
    __table_args__ = (
        UniqueConstraint('organization_id', 'provider_type', name='uq_org_whatsapp_provider'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<WhatsAppGatewayConfig(id={self.id}, org={self.organization_id}, type={self.provider_type})>"

    def get_display_name(self) -> str:
        """Get user-friendly display name for gateway."""
        type_names = {
            WhatsAppProviderType.APIWAP: "APIWAP",
            WhatsAppProviderType.TWILIO_WHATSAPP: "Twilio WhatsApp",
            WhatsAppProviderType.CUSTOM: "Custom Provider",
        }
        return type_names.get(self.provider_type, self.provider_type.value)


class WhatsAppSubscriptionPackage(Base):
    """
    WhatsApp subscription packages for ISP providers.

    ISP providers subscribe to enable WhatsApp messaging for their organization.
    Monthly fee: 500 KES
    """

    __tablename__ = "whatsapp_subscription_packages"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Package information
    name = Column(String(100), nullable=False, default="WhatsApp Messaging")
    description = Column(Text, nullable=True, default="Enable WhatsApp notifications for your customers")
    is_active = Column(Boolean, default=True, nullable=False)

    # Pricing
    monthly_fee = Column(Numeric(10, 2), nullable=False, default=500.00)  # 500 KES
    currency = Column(String(3), default="KES", nullable=False)

    # Limits
    max_messages_per_month = Column(Integer, nullable=True)  # null = unlimited
    max_message_length = Column(Integer, default=1000, nullable=False)

    # Features (JSON object)
    features = Column(JSON, default=dict, nullable=False)
    # Example:
    # {
    #   "text_messages": true,
    #   "media_messages": false,
    #   "template_messages": true,
    #   "delivery_reports": true
    # }

    # Trial settings
    trial_days = Column(Integer, default=7, nullable=False)
    trial_message_limit = Column(Integer, default=50, nullable=False)

    # Display
    display_order = Column(Integer, default=0, nullable=False)
    badge_text = Column(String(50), nullable=True)
    badge_color = Column(String(7), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    subscriptions = relationship("WhatsAppOrganizationSubscription", back_populates="package")

    def __repr__(self) -> str:
        """String representation."""
        return f"<WhatsAppSubscriptionPackage(id={self.id}, name='{self.name}', fee={self.monthly_fee})>"


class WhatsAppOrganizationSubscription(Base):
    """
    WhatsApp subscription for an ISP provider organization.

    When an ISP subscribes:
    1. WhatsApp is auto-enabled for their organization
    2. Monthly billing of 500 KES starts
    3. They can send WhatsApp messages to their customers
    """

    __tablename__ = "whatsapp_organization_subscriptions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    package_id = Column(Integer, ForeignKey("whatsapp_subscription_packages.id"), nullable=False)

    # Subscription details
    status = Column(Enum(WhatsAppSubscriptionStatus), default=WhatsAppSubscriptionStatus.PENDING, nullable=False, index=True)
    provider_type = Column(Enum(WhatsAppProviderType), default=WhatsAppProviderType.APIWAP, nullable=False)

    # Billing cycle
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    next_billing_date = Column(DateTime, nullable=False)
    is_auto_renewal = Column(Boolean, default=True, nullable=False)

    # Trial
    is_trial = Column(Boolean, default=False, nullable=False)
    trial_end_date = Column(DateTime, nullable=True)

    # Usage tracking
    messages_sent_this_month = Column(Integer, default=0, nullable=False)
    total_messages_sent = Column(Integer, default=0, nullable=False)
    last_message_sent_at = Column(DateTime, nullable=True)

    # APIWAP account details (auto-managed by platform)
    apiwap_account_id = Column(String(100), nullable=True)  # Platform-generated account ID
    apiwap_account_created_at = Column(DateTime, nullable=True)

    # Notes
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    activated_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="whatsapp_subscription")
    package = relationship("WhatsAppSubscriptionPackage", back_populates="subscriptions")
    creator = relationship("User", foreign_keys=[created_by])
    payments = relationship("WhatsAppSubscriptionPayment", back_populates="subscription", cascade="all, delete-orphan")
    messages = relationship("WhatsAppMessage", back_populates="subscription", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        UniqueConstraint('organization_id', name='uq_whatsapp_org_subscription'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<WhatsAppOrganizationSubscription(id={self.id}, org_id={self.organization_id}, status={self.status})>"

    @property
    def is_active(self) -> bool:
        """Check if subscription is active."""
        return (
            self.status == WhatsAppSubscriptionStatus.ACTIVE
            and self.end_date > datetime.utcnow()
        )

    @property
    def is_expired(self) -> bool:
        """Check if subscription is expired."""
        return self.end_date <= datetime.utcnow()

    @property
    def is_in_trial(self) -> bool:
        """Check if subscription is in trial period."""
        return (
            self.is_trial
            and self.trial_end_date
            and self.trial_end_date > datetime.utcnow()
        )

    def can_send_message(self) -> bool:
        """Check if organization can send WhatsApp messages."""
        if not self.is_active:
            return False

        # Check message limit
        if self.is_in_trial:
            # Get trial limit from package
            return True  # Will be checked against trial_message_limit

        return True  # Unlimited for paid subscriptions


class WhatsAppSubscriptionPayment(Base):
    """
    Payment records for WhatsApp subscriptions.

    Monthly payments of 500 KES from ISP providers for WhatsApp access.
    """

    __tablename__ = "whatsapp_subscription_payments"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Subscription
    subscription_id = Column(Integer, ForeignKey("whatsapp_organization_subscriptions.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Payment details
    payment_reference = Column(String(100), unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="KES", nullable=False)

    # Billing period
    billing_period_start = Column(DateTime, nullable=False)
    billing_period_end = Column(DateTime, nullable=False)

    # Payment gateway details
    payment_method = Column(String(50), nullable=True)  # mpesa, paystack, card
    gateway_reference = Column(String(100), nullable=True)
    gateway_response = Column(JSON, nullable=True)

    # Status
    status = Column(Enum(WhatsAppTransactionStatus), default=WhatsAppTransactionStatus.PENDING, nullable=False, index=True)
    status_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True)

    # Relationships
    subscription = relationship("WhatsAppOrganizationSubscription", back_populates="payments")
    organization = relationship("Organization", backref="whatsapp_payments")

    def __repr__(self) -> str:
        """String representation."""
        return f"<WhatsAppSubscriptionPayment(id={self.id}, ref='{self.payment_reference}', status={self.status})>"


class WhatsAppMessage(Base):
    """
    WhatsApp message records for tracking and analytics.

    Tracks all WhatsApp messages sent by ISP providers to their customers.
    """

    __tablename__ = "whatsapp_messages"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Organization and subscription
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("whatsapp_organization_subscriptions.id"), nullable=False, index=True)

    # Message details
    message_id = Column(String(100), unique=True, nullable=False, index=True)  # Platform-generated
    provider_message_id = Column(String(100), nullable=True, index=True)  # APIWAP message ID
    recipient_phone = Column(String(20), nullable=False)
    message_content = Column(Text, nullable=False)
    message_type = Column(String(20), default="text", nullable=False)

    # Delivery tracking
    status = Column(String(20), default="pending", nullable=False, index=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)

    # Cost tracking
    cost = Column(Numeric(6, 4), nullable=True)
    currency = Column(String(3), default="KES", nullable=False)

    # Related records
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Customer who received message
    notification_id = Column(Integer, ForeignKey("notifications.id"), nullable=True)
    triggered_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # Staff who triggered message

    # Provider response
    provider_response = Column(JSON, nullable=True)
    webhook_data = Column(JSON, nullable=True)  # Delivery status webhook data

    # Retry tracking
    retry_count = Column(Integer, default=0, nullable=False)
    last_retry_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", backref="whatsapp_messages")
    subscription = relationship("WhatsAppOrganizationSubscription", back_populates="messages")
    recipient = relationship("User", foreign_keys=[user_id], backref="received_whatsapp_messages")
    sender = relationship("User", foreign_keys=[triggered_by], backref="sent_whatsapp_messages")
    notification = relationship("Notification", backref="whatsapp_messages")

    def __repr__(self) -> str:
        """String representation."""
        return f"<WhatsAppMessage(id={self.id}, message_id='{self.message_id}', status='{self.status}')>"

    def get_provider_response(self) -> Dict[str, Any]:
        """Get provider response as dictionary."""
        return self.provider_response or {}


class PlatformWhatsAppSettings(Base):
    """
    Platform-level WhatsApp pricing and payment collection settings.

    Defines subscription pricing and where ISP provider payments are collected.
    Platform admin configures this to specify how ISPs should pay for WhatsApp subscription.
    """

    __tablename__ = "platform_whatsapp_settings"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Subscription Pricing
    monthly_subscription_fee = Column(Numeric(10, 2), default=500.00, nullable=False)  # 500 KES
    currency = Column(String(3), default="KES", nullable=False)
    minimum_subscription_months = Column(Integer, default=1, nullable=False)

    # Payment Collection Settings (where ISP payments go)
    payment_method = Column(String(50), default="paystack", nullable=False)  # mpesa, paystack, bank
    mpesa_paybill = Column(String(20), nullable=True)
    mpesa_till_number = Column(String(20), nullable=True)
    mpesa_account_name = Column(String(100), nullable=True)
    bank_account_number = Column(String(50), nullable=True)
    bank_name = Column(String(100), nullable=True)
    bank_branch = Column(String(100), nullable=True)
    bank_swift_code = Column(String(20), nullable=True)
    paystack_subaccount_code = Column(String(100), nullable=True)

    # Trial settings
    trial_enabled = Column(Boolean, default=True, nullable=False)
    trial_days = Column(Integer, default=7, nullable=False)
    trial_message_limit = Column(Integer, default=50, nullable=False)

    # Message limits
    default_message_limit_per_month = Column(Integer, nullable=True)  # null = unlimited
    max_message_length = Column(Integer, default=1000, nullable=False)

    # Auto-renewal settings
    auto_renewal_enabled = Column(Boolean, default=True, nullable=False)
    auto_renewal_grace_days = Column(Integer, default=3, nullable=False)

    # Active status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<PlatformWhatsAppSettings(id={self.id}, monthly_fee={self.monthly_subscription_fee})>"
