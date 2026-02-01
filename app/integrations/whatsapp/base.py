"""Base WhatsApp provider interface.

All WhatsApp provider implementations must inherit from this abstract class
and implement the required methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class WhatsAppDeliveryStatus(str, Enum):
    """WhatsApp delivery status enumeration."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    UNDELIVERED = "undelivered"
    UNKNOWN = "unknown"


class WhatsAppMessageType(str, Enum):
    """WhatsApp message type enumeration."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    TEMPLATE = "template"


@dataclass
class WhatsAppProviderConfig:
    """Configuration for WhatsApp provider.

    Attributes:
        provider_type: Type of WhatsApp provider (apiwap, twilio_whatsapp, etc.)
        is_active: Whether the provider is active
        is_default: Whether this is the default provider
        default_country_code: Default country code for phone formatting
        rate_limit_per_second: Maximum messages per second
        retry_count: Number of retries on failure
        timeout_seconds: Request timeout in seconds
    """

    provider_type: str
    credentials: Dict[str, Any]
    is_active: bool = True
    is_default: bool = False
    default_country_code: str = "+254"
    rate_limit_per_second: int = 10
    retry_count: int = 3
    timeout_seconds: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WhatsAppResult:
    """Result of WhatsApp send operation.

    Attributes:
        success: Whether the message was sent successfully
        message_id: Provider's message ID
        status: Delivery status
        recipient: Recipient phone number
        cost: Cost of the message (if available)
        currency: Currency of the cost
        message: Status message
        error_code: Error code if failed
        raw_response: Raw provider response
    """

    success: bool
    message_id: Optional[str] = None
    status: WhatsAppDeliveryStatus = WhatsAppDeliveryStatus.UNKNOWN
    recipient: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    message: Optional[str] = None
    error_code: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    sent_at: Optional[datetime] = None


@dataclass
class BulkWhatsAppResult:
    """Result of bulk WhatsApp send operation."""

    total: int
    successful: int
    failed: int
    results: List[WhatsAppResult] = field(default_factory=list)
    total_cost: Optional[float] = None
    currency: Optional[str] = None


class WhatsAppProviderInterface(ABC):
    """Abstract base class for WhatsApp providers.

    All WhatsApp provider implementations must inherit from this class
    and implement the abstract methods.
    """

    def __init__(self, config: WhatsAppProviderConfig):
        """Initialize the WhatsApp provider.

        Args:
            config: Provider configuration
        """
        self.config = config
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """Validate provider configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        pass

    @property
    @abstractmethod
    def supports_delivery_reports(self) -> bool:
        """Whether provider supports delivery reports."""
        pass

    @property
    @abstractmethod
    def supports_bulk_messages(self) -> bool:
        """Whether provider supports bulk message sending."""
        pass

    @abstractmethod
    async def send_message(
        self,
        to: str,
        message: str,
        message_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WhatsAppResult:
        """Send a single WhatsApp message.

        Args:
            to: Recipient phone number
            message: Message content
            message_type: Type of message (text, image, etc.)
            metadata: Optional metadata to attach

        Returns:
            WhatsAppResult with send status
        """
        pass

    async def send_bulk_messages(
        self,
        recipients: List[str],
        message: str,
        message_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BulkWhatsAppResult:
        """Send WhatsApp message to multiple recipients.

        Default implementation sends one by one. Override for optimized bulk sending.

        Args:
            recipients: List of recipient phone numbers
            message: Message content
            message_type: Type of message
            metadata: Optional metadata to attach

        Returns:
            BulkWhatsAppResult with aggregated results
        """
        results = []
        successful = 0
        failed = 0
        total_cost = 0.0

        for recipient in recipients:
            result = await self.send_message(to=recipient, message=message, message_type=message_type, metadata=metadata)
            results.append(result)

            if result.success:
                successful += 1
                if result.cost:
                    total_cost += result.cost
            else:
                failed += 1

        return BulkWhatsAppResult(
            total=len(recipients),
            successful=successful,
            failed=failed,
            results=results,
            total_cost=total_cost if total_cost > 0 else None,
            currency=results[0].currency if results and results[0].currency else None,
        )

    @abstractmethod
    async def get_delivery_status(self, message_id: str) -> WhatsAppResult:
        """Get delivery status for a message.

        Args:
            message_id: Provider's message ID

        Returns:
            WhatsAppResult with current delivery status
        """
        pass

    def format_phone_number(
        self,
        phone_number: str,
        country_code: Optional[str] = None,
    ) -> str:
        """Format phone number to E.164 format.

        Args:
            phone_number: Phone number to format
            country_code: Country code to use (default from config)

        Returns:
            Formatted phone number in E.164 format
        """
        country_code = country_code or self.config.default_country_code

        # Remove any whitespace and formatting characters
        phone = ''.join(c for c in phone_number if c.isdigit() or c == '+')

        # If already in international format, return as is
        if phone.startswith('+'):
            return phone

        # Remove leading zeros
        phone = phone.lstrip('0')

        # Add country code
        if not country_code.startswith('+'):
            country_code = '+' + country_code

        return f"{country_code}{phone}"

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the provider.

        Returns:
            Health status dictionary
        """
        try:
            # Simple connectivity check - override for provider-specific checks
            return {
                "provider": self.provider_name,
                "status": "healthy",
                "is_active": self.config.is_active,
            }
        except Exception as e:
            return {
                "provider": self.provider_name,
                "status": "unhealthy",
                "error": str(e),
                "is_active": self.config.is_active,
            }
