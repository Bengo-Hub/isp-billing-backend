"""Feature modules for ISP Billing System.

This package contains feature-specific modules, each with its own:
- service.py: Business logic
- Additional operation files for specialized functionality

Available modules:
- routers: MikroTik router management
- licences: Licence management
- system: Configuration, initialization, data integrity, and UI
- auth: Authentication, user management, and RBAC
- plans: Service plans and package templates
- notifications: Notifications, templates, and SMS
- billing: Invoices, payments, and MPESA
- subscriptions: Subscription lifecycle management
- support: Customer support tickets
- analytics: Reports and advanced analytics
- gateways: Payment gateway management
- provisioning: MikroTik device provisioning
"""

# Lazy imports to avoid circular dependencies and missing optional dependencies
_module_mapping = {
    # Routers
    "RouterService": ("app.modules.routers", "RouterService"),
    "MikroTikOperations": ("app.modules.routers", "MikroTikOperations"),
    "DeviceOperations": ("app.modules.routers", "DeviceOperations"),
    # Licences
    "LicenceService": ("app.modules.licences", "LicenceService"),
    "KeyOperations": ("app.modules.licences", "KeyOperations"),
    "AnalyticsOperations": ("app.modules.licences", "AnalyticsOperations"),
    # System
    "ConfigurationService": ("app.modules.system", "ConfigurationService"),
    "initialization_service": ("app.modules.system", "initialization_service"),
    "InitializationService": ("app.modules.system", "InitializationService"),
    "DataIntegrityService": ("app.modules.system", "DataIntegrityService"),
    "UIService": ("app.modules.system", "UIService"),
    # Auth
    "AuthService": ("app.modules.auth", "AuthService"),
    "UserService": ("app.modules.auth", "UserService"),
    "RBACService": ("app.modules.auth", "RBACService"),
    # Plans
    "PlanService": ("app.modules.plans", "PlanService"),
    "PackageTemplateService": ("app.modules.plans", "PackageTemplateService"),
    # Notifications
    "NotificationService": ("app.modules.notifications", "NotificationService"),
    "NotificationTemplateService": ("app.modules.notifications", "NotificationTemplateService"),
    "SMSCreditService": ("app.modules.notifications", "SMSCreditService"),
    # Billing
    "BillingService": ("app.modules.billing", "BillingService"),
    "PaymentManagementService": ("app.modules.billing", "PaymentManagementService"),
    "MpesaService": ("app.modules.billing", "MpesaService"),
    # Subscriptions
    "SubscriptionService": ("app.modules.subscriptions", "SubscriptionService"),
    # Support
    "TicketService": ("app.modules.support", "TicketService"),
    # Analytics
    "ReportsService": ("app.modules.analytics", "ReportsService"),
    "AdvancedAnalyticsService": ("app.modules.analytics", "AdvancedAnalyticsService"),
    # Gateways
    "GatewayManagementService": ("app.modules.gateways", "GatewayManagementService"),
    # Provisioning
    "ProvisioningService": ("app.modules.provisioning", "ProvisioningService"),
    "streaming_manager": ("app.modules.provisioning", "streaming_manager"),
}


def __getattr__(name: str):
    """Lazy import for modules."""
    if name in _module_mapping:
        module_path, attr_name = _module_mapping[name]
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_module_mapping.keys())
