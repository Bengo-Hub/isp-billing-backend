"""SMS provider integrations for ISP Billing.

This module provides a unified interface for sending SMS via multiple providers:
- Twilio (default, global coverage)
- Africa's Talking (African markets)
- AWS SNS (AWS-based infrastructure)

Usage:
    from app.integrations.sms import SMSProviderFactory, SMSProviderType
    
    provider = await SMSProviderFactory.create(
        SMSProviderType.TWILIO,
        credentials={"account_sid": "...", "auth_token": "...", "from_number": "..."}
    )
    result = await provider.send_sms("+254712345678", "Hello World")
"""

from .base import (
    SMSProviderInterface,
    SMSResult,
    SMSDeliveryStatus,
    SMSProviderConfig,
)
from .factory import SMSProviderFactory
from .twilio_provider import TwilioSMSProvider
from .africastalking_provider import AfricasTalkingSMSProvider

__all__ = [
    "SMSProviderInterface",
    "SMSResult",
    "SMSDeliveryStatus",
    "SMSProviderConfig",
    "SMSProviderFactory",
    "TwilioSMSProvider",
    "AfricasTalkingSMSProvider",
]
