"""WhatsApp provider integrations for ISP Billing.

This module provides a unified interface for sending WhatsApp messages via multiple providers:
- APIWAP (default, managed by platform)

The platform owner configures API keys, and ISP providers simply select the provider
and subscribe to enable WhatsApp messaging for their organization.

Usage:
    from app.integrations.whatsapp import WhatsAppProviderFactory, WhatsAppProviderType

    provider = await WhatsAppProviderFactory.create(
        WhatsAppProviderType.APIWAP,
        credentials={"api_key": "..."}
    )
    result = await provider.send_message("+254712345678", "Hello World", "text")
"""

from .base import (
    WhatsAppProviderInterface,
    WhatsAppResult,
    WhatsAppDeliveryStatus,
    WhatsAppProviderConfig,
    WhatsAppMessageType,
)
from .factory import WhatsAppProviderFactory
from .apiwap_provider import APIWAPWhatsAppProvider

__all__ = [
    "WhatsAppProviderInterface",
    "WhatsAppResult",
    "WhatsAppDeliveryStatus",
    "WhatsAppProviderConfig",
    "WhatsAppMessageType",
    "WhatsAppProviderFactory",
    "APIWAPWhatsAppProvider",
]
