"""Database models package."""

# Import models in dependency order to avoid circular imports
from app.core.database import Base as BaseModel
from .user import User, UserSession, UserVerification
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

__all__ = [
    "BaseModel",
    "User",
    "UserSession", 
    "UserVerification",
    "Router",
    "RouterDevice",
    "RouterLog",
    "ServicePlan",
    "PlanFeature",
    "PlanPricing",
    "Subscription",
    "SubscriptionUsageLog",
    "SubscriptionHistory",
    "Invoice",
    "InvoiceItem",
    "Payment",
    "PaymentLog",
    "BillingCycle",
    "Notification",
    "SupportTicket",
    "TicketMessage",
    "NotificationTemplate",
    "ProvisioningSession",
    "ProvisioningStepLog",
    "ProvisioningCommand",
    "ProvisioningTemplate",
    "RouterConfiguration",
    "UserSettings",
    "GlobalSearch",
    "UIBulkOperation",
    "SearchSuggestion",
    "UIPreferences",
    "Licence",
    "LicencePayment",
    "LicenceUsageLog",
    "LicenceFeature",
    "LicenceAlert",
    "PackageTemplate",
    "PackageAssignment",
    "BulkOperation",
    "PackageGuide",
    "QuickSetup",
    "PackageCategoryConfig",
    "PackageRating",
    "SMSCreditAccount",
    "SMSTransaction",
    "SMSTopUp",
    "SMSCreditAlert",
    "PhoneNumberManagement",
    "SMSCreditUsageStats",
]
