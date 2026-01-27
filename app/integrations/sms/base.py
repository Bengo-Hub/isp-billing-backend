"""Base SMS provider interface.

All SMS provider implementations must inherit from this abstract class
and implement the required methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class SMSDeliveryStatus(str, Enum):
    """SMS delivery status enumeration."""
    
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNDELIVERED = "undelivered"
    UNKNOWN = "unknown"


@dataclass
class SMSProviderConfig:
    """Configuration for SMS provider.
    
    Attributes:
        provider_type: Type of SMS provider (twilio, africastalking, etc.)
        is_active: Whether the provider is active
        is_default: Whether this is the default provider
        default_country_code: Default country code for phone formatting
        rate_limit_per_second: Maximum SMS per second
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
class SMSResult:
    """Result of SMS send operation.
    
    Attributes:
        success: Whether the SMS was sent successfully
        message_id: Provider's message ID
        status: Delivery status
        recipient: Recipient phone number
        cost: Cost of the SMS (if available)
        currency: Currency of the cost
        segments: Number of SMS segments
        message: Status message
        error_code: Error code if failed
        raw_response: Raw provider response
    """
    
    success: bool
    message_id: Optional[str] = None
    status: SMSDeliveryStatus = SMSDeliveryStatus.UNKNOWN
    recipient: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    segments: int = 1
    message: Optional[str] = None
    error_code: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    sent_at: Optional[datetime] = None


@dataclass
class BulkSMSResult:
    """Result of bulk SMS send operation."""
    
    total: int
    successful: int
    failed: int
    results: List[SMSResult] = field(default_factory=list)
    total_cost: Optional[float] = None
    currency: Optional[str] = None


class SMSProviderInterface(ABC):
    """Abstract base class for SMS providers.
    
    All SMS provider implementations must inherit from this class
    and implement the abstract methods.
    """
    
    def __init__(self, config: SMSProviderConfig):
        """Initialize the SMS provider.
        
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
    def supports_bulk_sms(self) -> bool:
        """Whether provider supports bulk SMS sending."""
        pass
    
    @abstractmethod
    async def send_sms(
        self,
        to: str,
        message: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SMSResult:
        """Send a single SMS message.
        
        Args:
            to: Recipient phone number
            message: SMS message content
            sender_id: Optional sender ID override
            metadata: Optional metadata to attach
            
        Returns:
            SMSResult with send status
        """
        pass
    
    async def send_bulk_sms(
        self,
        recipients: List[str],
        message: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BulkSMSResult:
        """Send SMS to multiple recipients.
        
        Default implementation sends one by one. Override for optimized bulk sending.
        
        Args:
            recipients: List of recipient phone numbers
            message: SMS message content
            sender_id: Optional sender ID override
            metadata: Optional metadata to attach
            
        Returns:
            BulkSMSResult with aggregated results
        """
        results = []
        successful = 0
        failed = 0
        total_cost = 0.0
        
        for recipient in recipients:
            result = await self.send_sms(to=recipient, message=message, sender_id=sender_id, metadata=metadata)
            results.append(result)
            
            if result.success:
                successful += 1
                if result.cost:
                    total_cost += result.cost
            else:
                failed += 1
        
        return BulkSMSResult(
            total=len(recipients),
            successful=successful,
            failed=failed,
            results=results,
            total_cost=total_cost if total_cost > 0 else None,
            currency=results[0].currency if results and results[0].currency else None,
        )
    
    @abstractmethod
    async def get_delivery_status(self, message_id: str) -> SMSResult:
        """Get delivery status for a message.
        
        Args:
            message_id: Provider's message ID
            
        Returns:
            SMSResult with current delivery status
        """
        pass
    
    @abstractmethod
    async def get_account_balance(self) -> Tuple[float, str]:
        """Get provider account balance.
        
        Returns:
            Tuple of (balance, currency)
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
    
    def calculate_segments(self, message: str) -> int:
        """Calculate number of SMS segments for a message.
        
        Args:
            message: SMS message content
            
        Returns:
            Number of SMS segments
        """
        # Check if message contains non-GSM characters (requires UCS-2 encoding)
        gsm_chars = (
            "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
            "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
        )
        
        is_gsm = all(c in gsm_chars or c == ' ' for c in message)
        
        if is_gsm:
            # GSM-7: 160 chars for single, 153 for concatenated
            if len(message) <= 160:
                return 1
            return (len(message) + 152) // 153
        else:
            # UCS-2: 70 chars for single, 67 for concatenated
            if len(message) <= 70:
                return 1
            return (len(message) + 66) // 67
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the provider.
        
        Returns:
            Health status dictionary
        """
        try:
            balance, currency = await self.get_account_balance()
            return {
                "provider": self.provider_name,
                "status": "healthy",
                "balance": balance,
                "currency": currency,
                "is_active": self.config.is_active,
            }
        except Exception as e:
            return {
                "provider": self.provider_name,
                "status": "unhealthy",
                "error": str(e),
                "is_active": self.config.is_active,
            }
