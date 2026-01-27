"""Payment gateway integrations package."""

from .base import (
    PaymentGatewayInterface,
    PaymentInitiationResult,
    PaymentVerificationResult,
    PaymentCallbackResult,
    BalanceResult,
    RefundResult,
    PaymentStatus,
    TransactionHistoryItem,
    TransactionHistoryResult,
)
from .factory import PaymentGatewayFactory

# Import gateway implementations to register them with the factory
from .mpesa import MPesaPaybillGateway, MPesaTillGateway
from .paystack import PaystackGateway
from .manual import (
    ManualPaymentGateway,
    MPesaPaybillManualGateway,
    MPesaTillManualGateway,
    BankAccountGateway,
)

__all__ = [
    # Base classes and types
    "PaymentGatewayInterface",
    "PaymentInitiationResult",
    "PaymentVerificationResult",
    "PaymentCallbackResult",
    "BalanceResult",
    "RefundResult",
    "PaymentStatus",
    "TransactionHistoryItem",
    "TransactionHistoryResult",
    "PaymentGatewayFactory",

    # Gateway implementations
    "MPesaPaybillGateway",
    "MPesaTillGateway",
    "PaystackGateway",
    "ManualPaymentGateway",
    "MPesaPaybillManualGateway",
    "MPesaTillManualGateway",
    "BankAccountGateway",
]
