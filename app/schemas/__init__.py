"""Pydantic schemas for data validation and serialization."""

from .user import (
    User, UserCreate, UserUpdate, UserInDB, UserResponse, UserProfile, UserLogin,
    UserPasswordChange, UserPasswordReset, UserPasswordResetConfirm, UserVerification, TokenRefresh
)
from .auth import Token, OAuth2Token, TokenData, LoginRequest, RegisterRequest
from .router import (
    Router, RouterCreate, RouterUpdate, RouterInDB, RouterList, RouterDevice, RouterDeviceCreate,
    RouterDeviceUpdate, RouterStats, RouterLog, RouterSyncRequest, RouterSyncResponse
)
from .plan import (
    ServicePlan, ServicePlanCreate, ServicePlanUpdate, ServicePlanInDB, ServicePlanList,
    ServicePlanStats, ServicePlanFilter, PlanFeature, PlanFeatureCreate, PlanFeatureUpdate,
    PlanPricing, PlanPricingCreate, PlanPricingUpdate
)
from .subscription import (
    Subscription, SubscriptionCreate, SubscriptionUpdate, SubscriptionInDB, SubscriptionList,
    SubscriptionStats, SubscriptionFilter, SubscriptionUsageLog, SubscriptionUsageLogCreate,
    SubscriptionHistory, SubscriptionHistoryCreate, SubscriptionRenewalRequest,
    SubscriptionSuspendRequest, SubscriptionCancelRequest, SubscriptionUsageUpdate
)
from .billing import (
    Invoice, InvoiceCreate, InvoiceUpdate, InvoiceInDB, InvoiceList, InvoiceFilter,
    InvoiceItem, InvoiceItemCreate, InvoiceItemUpdate, Payment, PaymentCreate, PaymentUpdate,
    PaymentInDB, PaymentList, PaymentFilter, MpesaPaymentRequest, MpesaPaymentResponse,
    MpesaCallbackRequest, MpesaCallbackResponse, BillingStats, PaymentStats,
    InvoiceGenerationRequest, BulkInvoiceGenerationRequest
)
from .ticket import (
    SupportTicket, SupportTicketCreate, SupportTicketUpdate, SupportTicketInDB, SupportTicketList,
    SupportTicketFilter, TicketMessage, TicketMessageCreate, TicketMessageUpdate,
    TicketAssignmentRequest, TicketResolutionRequest, TicketCloseRequest, TicketCancelRequest,
    TicketStats, TicketStatsByPriority, TicketStatsByCategory, TicketDashboard, TicketSearchRequest
)
from .notification import (
    Notification, NotificationCreate, NotificationUpdate, NotificationInDB, NotificationList,
    NotificationFilter, NotificationTemplate, NotificationTemplateCreate, NotificationTemplateUpdate,
    EmailNotificationRequest, SMSNotificationRequest, NotificationStats, BulkNotificationRequest
)

__all__ = [
    # User schemas
    "User",
    "UserCreate", 
    "UserUpdate",
    "UserInDB",
    "UserResponse",
    "UserProfile",
    "UserLogin",
    "UserPasswordChange",
    "UserPasswordReset",
    "UserPasswordResetConfirm",
    "UserVerification",
    "TokenRefresh",
    
    # Auth schemas
    "Token",
    "OAuth2Token",
    "TokenData",
    "LoginRequest",
    "RegisterRequest",
    
    # Router schemas
    "Router",
    "RouterCreate",
    "RouterUpdate",
    "RouterInDB",
    "RouterList",
    "RouterDevice",
    "RouterDeviceCreate",
    "RouterDeviceUpdate",
    "RouterStats",
    "RouterLog",
    "RouterSyncRequest",
    "RouterSyncResponse",
    
    # Plan schemas
    "ServicePlan",
    "ServicePlanCreate",
    "ServicePlanUpdate",
    "ServicePlanInDB",
    "ServicePlanList",
    "ServicePlanStats",
    "ServicePlanFilter",
    "PlanFeature",
    "PlanFeatureCreate",
    "PlanFeatureUpdate",
    "PlanPricing",
    "PlanPricingCreate",
    "PlanPricingUpdate",
    
    # Subscription schemas
    "Subscription",
    "SubscriptionCreate",
    "SubscriptionUpdate",
    "SubscriptionInDB",
    "SubscriptionList",
    "SubscriptionStats",
    "SubscriptionFilter",
    "SubscriptionUsageLog",
    "SubscriptionUsageLogCreate",
    "SubscriptionHistory",
    "SubscriptionHistoryCreate",
    "SubscriptionRenewalRequest",
    "SubscriptionSuspendRequest",
    "SubscriptionCancelRequest",
    "SubscriptionUsageUpdate",
    
    # Billing schemas
    "Invoice",
    "InvoiceCreate",
    "InvoiceUpdate",
    "InvoiceInDB",
    "InvoiceList",
    "InvoiceFilter",
    "InvoiceItem",
    "InvoiceItemCreate",
    "InvoiceItemUpdate",
    "Payment",
    "PaymentCreate",
    "PaymentUpdate",
    "PaymentInDB",
    "PaymentList",
    "PaymentFilter",
    "MpesaPaymentRequest",
    "MpesaPaymentResponse",
    "MpesaCallbackRequest",
    "MpesaCallbackResponse",
    "BillingStats",
    "PaymentStats",
    "InvoiceGenerationRequest",
    "BulkInvoiceGenerationRequest",
    
    # Ticket schemas
    "SupportTicket",
    "SupportTicketCreate",
    "SupportTicketUpdate",
    "SupportTicketInDB",
    "SupportTicketList",
    "SupportTicketFilter",
    "TicketMessage",
    "TicketMessageCreate",
    "TicketMessageUpdate",
    "TicketAssignmentRequest",
    "TicketResolutionRequest",
    "TicketCloseRequest",
    "TicketCancelRequest",
    "TicketStats",
    "TicketStatsByPriority",
    "TicketStatsByCategory",
    "TicketDashboard",
    "TicketSearchRequest",
    
    # Notification schemas
    "Notification",
    "NotificationCreate",
    "NotificationUpdate",
    "NotificationInDB",
    "NotificationList",
    "NotificationFilter",
    "NotificationTemplate",
    "NotificationTemplateCreate",
    "NotificationTemplateUpdate",
    "EmailNotificationRequest",
    "SMSNotificationRequest",
    "NotificationStats",
    "BulkNotificationRequest",
]
