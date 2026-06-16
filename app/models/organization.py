"""Organization model for multi-tenancy."""

import uuid
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
    String,
    Text,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base

if TYPE_CHECKING:
    from .user import User
    from .router import Router
    from .plan import ServicePlan
    from .subscription import Subscription
    from .billing import Invoice, Payment


class OrganizationType(str, PyEnum):
    """Organization type enumeration."""

    HOTSPOT = "hotspot"
    PPPOE = "pppoe"
    HYBRID = "hybrid"


class OrganizationStatus(str, PyEnum):
    """Organization status enumeration."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    PENDING_PAYMENT = "pending_payment"
    INACTIVE = "inactive"


class Organization(Base):
    """
    Organization model representing an ISP provider (tenant).

    This is the core model for multi-tenancy. Each ISP provider is an organization
    with their own customers, routers, packages, and payment configuration.
    """

    __tablename__ = "organizations"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True, nullable=False)

    # ── Auth-api tenant linkage (SoT = auth-api) ──
    # The central auth-api tenant UUID this Organization mirrors. ISP providers
    # now sign up via SSO; auth-api publishes auth.tenant.created / auth.user.*
    # which this service consumes (see app/events/consumer.py) to upsert the
    # local Organization + Users keyed by this id. Nullable + unique so existing
    # local-only orgs are unaffected. For tenant scoping against treasury /
    # subscriptions, ``uuid`` is kept in sync with this value (see the consumer)
    # so the local uuid IS the auth tenant UUID.
    auth_tenant_id = Column(String(36), unique=True, index=True, nullable=True)

    # Basic information
    name = Column(String(200), nullable=False, index=True)
    slug = Column(String(100), unique=True, index=True, nullable=False)  # URL-friendly identifier
    organization_type = Column(Enum(OrganizationType), default=OrganizationType.HOTSPOT, nullable=False)
    status = Column(Enum(OrganizationStatus), default=OrganizationStatus.TRIAL, nullable=False)

    # Contact information
    email = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), default="Kenya", nullable=False)

    # Branding
    logo_url = Column(String(500), nullable=True)
    favicon_url = Column(String(500), nullable=True)
    primary_color = Column(String(7), default="#ec4899", nullable=False)  # Pink/Magenta default
    secondary_color = Column(String(7), default="#8b5cf6", nullable=True)

    # Portal configuration
    portal_domain = Column(String(200), nullable=True)  # Custom domain for portal
    portal_title = Column(String(200), nullable=True)  # Custom portal title
    portal_description = Column(Text, nullable=True)
    terms_of_service = Column(Text, nullable=True)
    privacy_policy = Column(Text, nullable=True)

    # Subscription and limits
    # NOTE: subscription_tier_id (FK -> platform_subscription_tiers) was removed —
    # ISP-provider subscriptions/limits are now owned by the central subscriptions-api.
    trial_ends_at = Column(DateTime, nullable=True)
    subscription_ends_at = Column(DateTime, nullable=True)
    max_routers = Column(Integer, default=5, nullable=False)
    max_customers = Column(Integer, default=100, nullable=False)
    max_users = Column(Integer, default=5, nullable=False)  # Staff users (admin, technician)

    # Features
    features = Column(JSON, default=dict, nullable=False)  # Feature flags

    # Payment settings
    default_currency = Column(String(3), default="KES", nullable=False)
    timezone = Column(String(50), default="Africa/Nairobi", nullable=False)

    # Notification settings
    notification_email = Column(String(100), nullable=True)
    notification_phone = Column(String(20), nullable=True)
    # NOTE (Phase C1): sms_sender_id removed — SMS sending/sender-id is owned by
    # notifications-api now (column dropped via migration).

    # Analytics
    total_revenue = Column(Integer, default=0, nullable=False)  # In cents
    total_customers = Column(Integer, default=0, nullable=False)
    active_subscriptions = Column(Integer, default=0, nullable=False)

    # Grace period and licence enforcement
    grace_period_days = Column(Integer, default=2, nullable=False)
    grace_period_ends_at = Column(DateTime, nullable=True)
    licence_bypass = Column(Boolean, default=False, nullable=False)
    bypass_reason = Column(Text, nullable=True)
    bypass_set_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    activated_at = Column(DateTime, nullable=True)  # When trial converted to active
    suspended_at = Column(DateTime, nullable=True)

    # Relationships
    users = relationship("User", back_populates="organization", foreign_keys="User.organization_id")
    routers = relationship("Router", back_populates="organization")
    service_plans = relationship("ServicePlan", back_populates="organization")
    subscriptions = relationship("Subscription", back_populates="organization")
    invoices = relationship("Invoice", back_populates="organization")
    payments = relationship("Payment", back_populates="organization")
    voucher_codes = relationship("VoucherCode", back_populates="organization")
    # NOTE (Phase C1): whatsapp_subscription relationship removed — WhatsApp
    # subscriptions are owned by notifications-api now.
    expenses = relationship("Expense", back_populates="organization")
    system_logs = relationship("SystemLog", back_populates="organization")
    campaigns = relationship("Campaign", back_populates="organization")
    leads = relationship("Lead", back_populates="organization")
    emails = relationship("Email", back_populates="organization")
    tickets = relationship("SupportTicket", back_populates="organization")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Organization(id={self.id}, name='{self.name}', slug='{self.slug}')>"

    @property
    def is_trial(self) -> bool:
        """Check if organization is in trial period."""
        if self.status != OrganizationStatus.TRIAL:
            return False
        if not self.trial_ends_at:
            return False
        return datetime.utcnow() < self.trial_ends_at

    @property
    def trial_days_remaining(self) -> int:
        """Get remaining trial days."""
        if not self.is_trial or not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - datetime.utcnow()
        return max(0, delta.days)

    @property
    def is_subscription_active(self) -> bool:
        """Check if subscription is active."""
        if self.status not in [OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL]:
            return False
        if self.is_trial:
            return True
        if not self.subscription_ends_at:
            return False
        return datetime.utcnow() < self.subscription_ends_at

    @property
    def subscription_status(self) -> str:
        """Get subscription status as string."""
        return self.status.value if self.status else "inactive"

    @property
    def subscription_expires_at(self) -> Optional[datetime]:
        """Alias for subscription_ends_at."""
        return self.subscription_ends_at

    @property
    def subscription_days_remaining(self) -> int:
        """Get remaining subscription days."""
        if self.is_trial:
            return self.trial_days_remaining
        if not self.subscription_ends_at:
            return 0
        delta = self.subscription_ends_at - datetime.utcnow()
        return max(0, delta.days)

    @property
    def is_in_grace_period(self) -> bool:
        """Check if organization is in grace period (expired but within grace window)."""
        if self.status != OrganizationStatus.PENDING_PAYMENT:
            return False
        if self.grace_period_ends_at:
            return datetime.utcnow() < self.grace_period_ends_at
        return False

    @property
    def is_suspended(self) -> bool:
        """Check if organization is suspended."""
        return self.status == OrganizationStatus.SUSPENDED

    @property
    def max_staff_users(self) -> int:
        """Alias for max_users (staff users like admin, technician)."""
        return self.max_users

    @property
    def currency(self) -> str:
        """Alias for default_currency."""
        return self.default_currency

    def to_dict(self) -> dict:
        """Convert organization to dictionary."""
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "name": self.name,
            "slug": self.slug,
            "organization_type": self.organization_type.value if self.organization_type else None,
            "status": self.status.value if self.status else None,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "logo_url": self.logo_url,
            "primary_color": self.primary_color,
            "portal_domain": self.portal_domain,
            "max_routers": self.max_routers,
            "max_customers": self.max_customers,
            "max_users": self.max_users,
            "is_trial": self.is_trial,
            "trial_days_remaining": self.trial_days_remaining,
            "is_subscription_active": self.is_subscription_active,
            "default_currency": self.default_currency,
            "timezone": self.timezone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OrganizationSettings(Base):
    """Organization-specific settings."""

    __tablename__ = "organization_settings"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), unique=True, nullable=False)

    # General settings
    language = Column(String(10), default="en", nullable=False)
    date_format = Column(String(20), default="DD/MM/YYYY", nullable=False)
    time_format = Column(String(10), default="24h", nullable=False)

    # Billing settings
    invoice_prefix = Column(String(10), default="INV", nullable=False)
    invoice_footer = Column(Text, nullable=True)
    payment_reminder_days = Column(Integer, default=3, nullable=False)
    auto_suspend_days = Column(Integer, default=14, nullable=False)  # Days after due date / churn window for duration-less accounts (system default 14)

    # Notification settings
    notify_on_payment = Column(Boolean, default=True, nullable=False)
    notify_on_subscription = Column(Boolean, default=True, nullable=False)
    notify_on_expiry = Column(Boolean, default=True, nullable=False)
    notify_before_expiry_days = Column(Integer, default=3, nullable=False)

    # Router settings
    auto_disconnect_expired = Column(Boolean, default=True, nullable=False)
    session_timeout_minutes = Column(Integer, default=60, nullable=False)

    # Hotspot settings
    voucher_format = Column(String(50), default="XXXX-XXXX", nullable=False)  # X = alphanumeric
    voucher_length = Column(Integer, default=8, nullable=False)
    show_packages_on_portal = Column(Boolean, default=True, nullable=False)
    allow_guest_purchases = Column(Boolean, default=True, nullable=False)

    # Hotspot user generation settings (for auto-created users when purchasing packages)
    hotspot_username_prefix = Column(String(10), default="C", nullable=False)  # Prefix for generated usernames (e.g., "C" -> C001, C002)
    hotspot_username_counter = Column(Integer, default=1, nullable=False)  # Auto-increment counter for unique usernames
    hotspot_template = Column(String(50), default="Aurora", nullable=False)  # Login page template name
    prune_inactive_users_days = Column(Integer, default=14, nullable=False)  # Auto-delete inactive hotspot users after N days
    hotspot_redirect_url = Column(String(500), default="https://www.google.com", nullable=False)  # Redirect URL after login/purchase

    # PPPoE settings
    require_username_approval = Column(Boolean, default=False, nullable=False)
    allow_self_registration = Column(Boolean, default=False, nullable=False)

    # Remote Winbox/VPN settings
    vpn_domain = Column(String(200), default="vpn.codevertex.com", nullable=False)  # VPN domain for remote Winbox
    winbox_port_start = Column(Integer, default=51000, nullable=False)  # Starting port for VPN Winbox allocation
    winbox_port_end = Column(Integer, default=59999, nullable=False)  # Ending port for VPN Winbox allocation

    # Advanced settings
    api_rate_limit = Column(Integer, default=100, nullable=False)  # Requests per minute
    enable_webhooks = Column(Boolean, default=False, nullable=False)
    webhook_url = Column(String(500), nullable=True)
    webhook_secret = Column(String(255), nullable=True)

    # Notification Template Settings
    # MikroTik Status Notifications
    enable_mikrotik_status_notifications = Column(Boolean, default=False, nullable=False)

    # Payment Confirmation SMS Templates
    send_hotspot_payment_confirmation = Column(Boolean, default=True, nullable=False)
    hotspot_payment_confirmation_sms = Column(Text, nullable=True, default="Dear @username, you have successfully subscribed to @package_name. Your subscription will expire on @expiry_date. Your username is @username and password is @password. To login visit @portal_url/buy/@org_slug and click connect.")

    send_pppoe_payment_confirmation = Column(Boolean, default=True, nullable=False)
    pppoe_payment_confirmation_sms = Column(Text, nullable=True, default="Hello @first_name, Your PPPoE account has been created. You can use account number: @account_number to pay. Login to your account at @portal_url/portal/pppoe/@org_slug/login using username: @username and password: @password")

    # Expiry Notification SMS Templates
    send_hotspot_expiry_notification = Column(Boolean, default=True, nullable=False)
    hotspot_expiry_notification_sms = Column(Text, nullable=True, default="Dear @username, your package has expired. Kindly select another package to continue using the internet.")

    send_pppoe_expiry_notification = Column(Boolean, default=True, nullable=False)
    pppoe_expiry_notification_sms = Column(Text, nullable=True, default="Dear @username, your package has expired. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.")

    # Expiry Reminder SMS Templates
    send_hotspot_expiry_reminder = Column(Boolean, default=True, nullable=False)
    hotspot_expiry_reminder_sms = Column(Text, nullable=True, default="Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.")

    send_pppoe_expiry_reminder = Column(Boolean, default=True, nullable=False)
    pppoe_expiry_reminder_sms = Column(Text, nullable=True, default="Dear @username, your package will expire in @days_left. Kindly pay using the paybill @paybill and account number @account_number to continue using the internet.")

    # Email Subscription Reminder Settings
    enable_email_subscription_reminders = Column(Boolean, default=True, nullable=False)
    send_pppoe_email_reminders = Column(Boolean, default=True, nullable=False)
    pppoe_email_reminder_subject = Column(String(200), nullable=True, default="Your subscription expires in @days_left days")
    pppoe_email_reminder_message = Column(Text, nullable=True, default="Dear @first_name,<br><br>Your internet subscription will expire in @days_left days on @expiry_date.<br><br>Please renew by paying to paybill @paybill using account number @account_number to avoid service interruption.<br><br>Kind regards,<br>@company_name")

    # WhatsApp Settings
    whatsapp_provider = Column(String(50), nullable=True)  # apiwap, twilio_whatsapp, etc.
    whatsapp_enabled = Column(Boolean, default=False, nullable=False)

    # WhatsApp Payment Confirmation Templates
    send_hotspot_payment_confirmation_whatsapp = Column(Boolean, default=False, nullable=False)
    hotspot_payment_confirmation_whatsapp = Column(Text, nullable=True, default="Hello @username! 👋\n\nYou've successfully subscribed to *@package_name*\n\n✅ Username: @username\n🔑 Password: @password\n📅 Expires: @expiry_date\n\n🌐 Login: @portal_url/buy/@org_slug\n(Click connect and login with your details)\n\nThank you for choosing us!")

    send_pppoe_payment_confirmation_whatsapp = Column(Boolean, default=False, nullable=False)
    pppoe_payment_confirmation_whatsapp = Column(Text, nullable=True, default="Hello @first_name! 👋\n\nYour PPPoE account is ready!\n\n*@package_name*\n\n✅ Username: @username\n🔑 Password: @password\n📅 Expires: @expiry_date\n💳 Account Number: @account_number\n\n🌐 Login: @portal_url/portal/pppoe/@org_slug/login\n\nThank you for choosing us!")

    # WhatsApp Expiry Notification Templates
    send_hotspot_expiry_notification_whatsapp = Column(Boolean, default=False, nullable=False)
    hotspot_expiry_notification_whatsapp = Column(Text, nullable=True, default="Hello @username! 📢\n\nYour internet package has expired. Please purchase a new package to continue browsing.\n\nThank you!")

    send_pppoe_expiry_notification_whatsapp = Column(Boolean, default=False, nullable=False)
    pppoe_expiry_notification_whatsapp = Column(Text, nullable=True, default="Hello @username! 📢\n\nYour internet subscription has expired.\n\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to continue browsing!")

    # WhatsApp Expiry Reminder Templates
    send_hotspot_expiry_reminder_whatsapp = Column(Boolean, default=False, nullable=False)
    hotspot_expiry_reminder_whatsapp = Column(Text, nullable=True, default="Hello @username! ⏰\n\nYour package expires in *@days_left days*\n\n📅 Expiry Date: @expiry_date\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to avoid interruption!")

    send_pppoe_expiry_reminder_whatsapp = Column(Boolean, default=False, nullable=False)
    pppoe_expiry_reminder_whatsapp = Column(Text, nullable=True, default="Hello @username! ⏰\n\nYour subscription expires in *@days_left days*\n\n📅 Expiry Date: @expiry_date\n💳 Paybill: @paybill\n📋 Account: @account_number\n\nRenew now to stay connected!")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", backref="settings", uselist=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<OrganizationSettings(id={self.id}, organization_id={self.organization_id})>"
