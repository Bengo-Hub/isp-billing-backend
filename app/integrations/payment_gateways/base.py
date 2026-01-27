"""
Base payment gateway interface.

All payment gateway implementations must inherit from this abstract class
and implement the required methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


class PaymentStatus(str, Enum):
    """Payment transaction status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    TIMEOUT = "timeout"


@dataclass
class PaymentInitiationResult:
    """Result of payment initiation."""

    success: bool
    transaction_reference: str
    gateway_reference: Optional[str] = None
    status: PaymentStatus = PaymentStatus.PENDING
    message: Optional[str] = None
    checkout_url: Optional[str] = None  # For redirect-based payments
    instructions: Optional[str] = None  # For manual payment instructions
    metadata: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[datetime] = None


@dataclass
class PaymentVerificationResult:
    """Result of payment verification."""

    success: bool
    transaction_reference: str
    status: PaymentStatus
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    gateway_reference: Optional[str] = None
    paid_at: Optional[datetime] = None
    payer_phone: Optional[str] = None
    payer_name: Optional[str] = None
    message: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentCallbackResult:
    """Result of processing a payment callback."""

    success: bool
    transaction_reference: str
    status: PaymentStatus
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    gateway_reference: Optional[str] = None
    paid_at: Optional[datetime] = None
    payer_phone: Optional[str] = None
    payer_name: Optional[str] = None
    message: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BalanceResult:
    """Result of balance inquiry."""

    success: bool
    available_balance: Optional[Decimal] = None
    current_balance: Optional[Decimal] = None
    currency: Optional[str] = None
    message: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundResult:
    """Result of refund operation."""

    success: bool
    transaction_reference: str
    refund_reference: Optional[str] = None
    amount: Optional[Decimal] = None
    status: PaymentStatus = PaymentStatus.PENDING
    message: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransactionHistoryItem:
    """Single transaction in history."""

    transaction_reference: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    transaction_type: str  # payment, refund, transfer
    payer_phone: Optional[str] = None
    payer_name: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransactionHistoryResult:
    """Result of transaction history query."""

    success: bool
    transactions: list = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    message: Optional[str] = None


class PaymentGatewayInterface(ABC):
    """
    Abstract base class for payment gateway implementations.

    All payment gateways must implement these methods to ensure
    consistent behavior across different payment providers.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the payment gateway with configuration.

        Args:
            config: Gateway-specific configuration including credentials
        """
        self.config = config
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """
        Validate the gateway configuration.

        Raises:
            ValueError: If configuration is invalid or missing required fields
        """
        pass

    @property
    @abstractmethod
    def gateway_name(self) -> str:
        """Return the gateway name for logging and display."""
        pass

    @property
    @abstractmethod
    def supports_stk_push(self) -> bool:
        """Whether the gateway supports STK push (customer-initiated payment)."""
        pass

    @property
    @abstractmethod
    def supports_c2b(self) -> bool:
        """Whether the gateway supports C2B (customer to business) payments."""
        pass

    @property
    @abstractmethod
    def supports_b2c(self) -> bool:
        """Whether the gateway supports B2C (business to customer) payments."""
        pass

    @property
    @abstractmethod
    def supports_refunds(self) -> bool:
        """Whether the gateway supports refunds."""
        pass

    @abstractmethod
    async def initiate_payment(
        self,
        amount: Decimal,
        phone_number: str,
        reference: str,
        description: str,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentInitiationResult:
        """
        Initiate a payment request.

        For M-PESA, this triggers an STK push to the customer's phone.
        For card payments, this may return a checkout URL.

        Args:
            amount: Payment amount
            phone_number: Customer's phone number
            reference: Unique transaction reference
            description: Payment description
            callback_url: URL for payment callback (optional, uses config default)
            metadata: Additional metadata to store with the transaction

        Returns:
            PaymentInitiationResult with transaction details
        """
        pass

    @abstractmethod
    async def verify_payment(
        self,
        transaction_reference: str,
    ) -> PaymentVerificationResult:
        """
        Verify the status of a payment.

        Args:
            transaction_reference: The reference from initiate_payment

        Returns:
            PaymentVerificationResult with current status
        """
        pass

    @abstractmethod
    async def process_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> PaymentCallbackResult:
        """
        Process a payment callback from the gateway.

        Args:
            callback_data: Raw callback data from the gateway

        Returns:
            PaymentCallbackResult with parsed transaction details
        """
        pass

    async def get_balance(self) -> BalanceResult:
        """
        Get the current account balance.

        Not all gateways support this. Default implementation returns unsupported.

        Returns:
            BalanceResult with balance information
        """
        return BalanceResult(
            success=False,
            message="Balance inquiry not supported by this gateway"
        )

    async def refund_payment(
        self,
        transaction_reference: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
    ) -> RefundResult:
        """
        Refund a payment.

        Not all gateways support this. Default implementation returns unsupported.

        Args:
            transaction_reference: Original transaction reference
            amount: Amount to refund (None for full refund)
            reason: Reason for refund

        Returns:
            RefundResult with refund details
        """
        return RefundResult(
            success=False,
            transaction_reference=transaction_reference,
            message="Refunds not supported by this gateway"
        )

    async def get_transaction_status(
        self,
        transaction_reference: str,
    ) -> PaymentVerificationResult:
        """
        Get the current status of a transaction.

        Default implementation calls verify_payment.

        Args:
            transaction_reference: Transaction reference

        Returns:
            PaymentVerificationResult with status
        """
        return await self.verify_payment(transaction_reference)

    async def get_transaction_history(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TransactionHistoryResult:
        """
        Get transaction history.

        Not all gateways support this. Default implementation returns unsupported.

        Args:
            start_date: Filter by start date
            end_date: Filter by end date
            page: Page number
            page_size: Number of items per page

        Returns:
            TransactionHistoryResult with transactions
        """
        return TransactionHistoryResult(
            success=False,
            message="Transaction history not supported by this gateway"
        )

    def generate_reference(self, prefix: str = "TXN") -> str:
        """
        Generate a unique transaction reference.

        Args:
            prefix: Prefix for the reference

        Returns:
            Unique reference string
        """
        import uuid
        import time

        timestamp = int(time.time() * 1000)
        unique_id = uuid.uuid4().hex[:8].upper()
        return f"{prefix}{timestamp}{unique_id}"

    def format_phone_number(self, phone: str, country_code: str = "254") -> str:
        """
        Format phone number to international format.

        Args:
            phone: Phone number in any format
            country_code: Country code without +

        Returns:
            Formatted phone number (e.g., 254712345678)
        """
        # Remove all non-numeric characters
        phone = "".join(filter(str.isdigit, phone))

        # Remove leading zeros
        phone = phone.lstrip("0")

        # Remove country code if already present
        if phone.startswith(country_code):
            phone = phone[len(country_code):]

        # Add country code
        return f"{country_code}{phone}"
