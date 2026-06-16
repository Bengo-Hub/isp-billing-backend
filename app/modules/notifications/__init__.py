"""Notifications module for in-app notifications and templates.

DELIVERY of SMS / WhatsApp / email and all messaging credits / subscriptions are
centralized on notifications-api. This module only persists Notification rows and
manages notification templates.

This module provides:
- NotificationService: Notification management
- NotificationTemplateService: Notification template operations
"""

from .service import NotificationService
from .templates import NotificationTemplateService

__all__ = [
    "NotificationService",
    "NotificationTemplateService",
]
