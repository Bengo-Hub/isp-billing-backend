"""Database models package."""

# Import models in dependency order to avoid circular imports
from app.core.database import Base as BaseModel

# Multi-tenancy models (must be imported first due to FK references)
from .organization import Organization, OrganizationSettings, OrganizationType, OrganizationStatus
from .platform_billing import (
    PlatformSubscriptionTier, PlatformInvoice, PlatformPayment, EarningsRecord,
    BillingCycle as PlatformBillingCycle, TierType, InvoiceStatus as PlatformInvoiceStatus
)
from .payment_gateway import (
    PaymentGatewayConfig, PaymentTransaction, ManualPaymentRecord,
    GatewayType, GatewayStatus, TransactionFeeType,
    PayoutConfig, PayoutRecord, PayoutScheduleType, PayoutRecipientType, PayoutStatus
)
from .customer_portal import (
    VoucherCode, VoucherBatch, CustomerSession, CustomerPurchase,
    VoucherStatus, SessionStatus
)

# Core models
from .user import User, UserSession, UserVerification, UserRole as UserRoleEnum, UserStatus
from .router import Router, RouterDevice, RouterLog
from .plan import ServicePlan, PlanFeature, PlanPricing
from .subscription import Subscription, SubscriptionUsageLog, SubscriptionHistory
from .billing import Invoice, InvoiceItem, Payment, PaymentLog, BillingCycle
from .notification import Notification, SupportTicket, TicketMessage, NotificationTemplate
from .provisioning import (
    ProvisioningSession, ProvisioningStepLog, ProvisioningCommand,
    ProvisioningTemplate, RouterConfiguration
)
from .user_settings import (
    UserSettings, GlobalSearch, UIBulkOperation, SearchSuggestion, UIPreferences
)
from .licence import (
    Licence, LicencePayment, LicenceUsageLog, LicenceFeature, LicenceAlert
)
from .package_template import (
    PackageTemplate, PackageAssignment, BulkOperation, PackageGuide,
    QuickSetup, PackageCategoryConfig, PackageRating
)
from .sms_credit import (
    SMSCreditAccount, SMSTransaction, SMSTopUp, SMSCreditAlert,
    PhoneNumberManagement, SMSCreditUsageStats
)
from .rbac import (
    Role, Permission, UserPermission, SystemLicence,
    PermissionModule, PermissionAction, UserRole
)
from .configuration import Configuration, ConfigType

__all__ = [
    # Base
    "BaseModel",

    # Multi-tenancy
    "Organization",
    "OrganizationSettings",
    "OrganizationType",
    "OrganizationStatus",

    # Platform Billing
    "PlatformSubscriptionTier",
    "PlatformInvoice",
    "PlatformPayment",
    "EarningsRecord",
    "PlatformBillingCycle",
    "TierType",
    "PlatformInvoiceStatus",

    # Payment Gateways
    "PaymentGatewayConfig",
    "PaymentTransaction",
    "ManualPaymentRecord",
    "GatewayType",
    "GatewayStatus",
    "TransactionFeeType",
    "PayoutConfig",
    "PayoutRecord",
    "PayoutScheduleType",
    "PayoutRecipientType",
    "PayoutStatus",

    # Customer Portal
    "VoucherCode",
    "VoucherBatch",
    "CustomerSession",
    "CustomerPurchase",
    "VoucherStatus",
    "SessionStatus",

    # Users
    "User",
    "UserSession",
    "UserVerification",
    "UserRoleEnum",
    "UserStatus",

    # Routers
    "Router",
    "RouterDevice",
    "RouterLog",

    # Plans
    "ServicePlan",
    "PlanFeature",
    "PlanPricing",

    # Subscriptions
    "Subscription",
    "SubscriptionUsageLog",
    "SubscriptionHistory",

    # Billing
    "Invoice",
    "InvoiceItem",
    "Payment",
    "PaymentLog",
    "BillingCycle",

    # Notifications
    "Notification",
    "SupportTicket",
    "TicketMessage",
    "NotificationTemplate",

    # Provisioning
    "ProvisioningSession",
    "ProvisioningStepLog",
    "ProvisioningCommand",
    "ProvisioningTemplate",
    "RouterConfiguration",

    # User Settings
    "UserSettings",
    "GlobalSearch",
    "UIBulkOperation",
    "SearchSuggestion",
    "UIPreferences",

    # Licence
    "Licence",
    "LicencePayment",
    "LicenceUsageLog",
    "LicenceFeature",
    "LicenceAlert",

    # Package Templates
    "PackageTemplate",
    "PackageAssignment",
    "BulkOperation",
    "PackageGuide",
    "QuickSetup",
    "PackageCategoryConfig",
    "PackageRating",

    # SMS
    "SMSCreditAccount",
    "SMSTransaction",
    "SMSTopUp",
    "SMSCreditAlert",
    "PhoneNumberManagement",
    "SMSCreditUsageStats",

    # RBAC
    "Role",
    "Permission",
    "UserPermission",
    "SystemLicence",
    "PermissionModule",
    "PermissionAction",
    "UserRole",
    "Configuration",
]
