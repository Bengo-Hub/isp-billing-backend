"""
Manual payment gateway for non-API payment methods.

Handles payment methods that require manual reconciliation:
- M-PESA Paybill without API
- M-PESA Till without API
- Bank Account transfers
"""

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from app.models.payment_gateway import GatewayType
from .base import (
    PaymentGatewayInterface,
    PaymentInitiationResult,
    PaymentVerificationResult,
    PaymentCallbackResult,
    PaymentStatus,
)
from .factory import PaymentGatewayFactory

logger = logging.getLogger(__name__)


class ManualPaymentGateway(PaymentGatewayInterface):
    """
    Base class for manual payment gateways.

    Provides payment instructions but doesn't actually process payments.
    Payments are recorded manually and reconciled by administrators.
    """

    def _validate_config(self) -> None:
        """Validate configuration - minimal for manual gateways."""
        pass

    @property
    def gateway_name(self) -> str:
        return "Manual Payment"

    @property
    def supports_stk_push(self) -> bool:
        return False

    @property
    def supports_c2b(self) -> bool:
        return False

    @property
    def supports_b2c(self) -> bool:
        return False

    @property
    def supports_refunds(self) -> bool:
        return False

    def _get_payment_instructions(
        self,
        amount: Decimal,
        reference: str,
    ) -> str:
        """
        Get payment instructions for the customer.

        Override in subclasses for specific instructions.
        """
        return f"Please make a payment of {amount} with reference: {reference}"

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
        Create a pending payment record with instructions.

        The payment must be confirmed manually.
        """
        instructions = self._get_payment_instructions(amount, reference)

        return PaymentInitiationResult(
            success=True,
            transaction_reference=reference,
            status=PaymentStatus.PENDING,
            instructions=instructions,
            message="Payment pending manual confirmation",
            metadata={
                "requires_manual_confirmation": True,
                "amount": float(amount),
                "phone_number": phone_number,
                "description": description,
                **(metadata or {}),
            },
        )

    async def verify_payment(
        self,
        transaction_reference: str,
    ) -> PaymentVerificationResult:
        """
        For manual gateways, verification must be done through admin interface.
        """
        return PaymentVerificationResult(
            success=False,
            transaction_reference=transaction_reference,
            status=PaymentStatus.PENDING,
            message="Manual verification required. Check admin dashboard.",
        )

    async def process_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> PaymentCallbackResult:
        """
        Manual gateways don't receive callbacks.
        """
        return PaymentCallbackResult(
            success=False,
            transaction_reference="",
            status=PaymentStatus.PENDING,
            message="Manual gateways do not support callbacks",
            raw_data=callback_data,
        )


@PaymentGatewayFactory.register(GatewayType.MPESA_PAYBILL_NO_API)
class MPesaPaybillManualGateway(ManualPaymentGateway):
    """
    M-PESA Paybill without API integration.

    Provides payment instructions for customers to pay via M-PESA.
    Payments are reconciled manually.
    """

    @property
    def gateway_name(self) -> str:
        return "M-PESA Paybill (Manual)"

    def _validate_config(self) -> None:
        """Validate paybill number is provided."""
        if not self.config.get("paybill_number"):
            raise ValueError("Paybill number is required")

    def _get_payment_instructions(
        self,
        amount: Decimal,
        reference: str,
    ) -> str:
        """Get M-PESA Paybill payment instructions."""
        paybill = self.config.get("paybill_number", "")
        account_format = self.config.get("account_number_format", "PHONE")

        # Format account number based on configuration
        if account_format == "PHONE":
            account_hint = "Your phone number"
        elif account_format == "REFERENCE":
            account_hint = reference
        else:
            account_hint = account_format.replace("{reference}", reference)

        instructions = f"""
Pay via M-PESA Paybill:

1. Go to M-PESA menu
2. Select "Lipa na M-PESA"
3. Select "Pay Bill"
4. Enter Business Number: {paybill}
5. Enter Account Number: {account_hint}
6. Enter Amount: KES {amount:,.0f}
7. Enter your M-PESA PIN
8. Confirm the transaction

Your payment will be confirmed within 24 hours.
Reference: {reference}
"""
        return instructions.strip()


@PaymentGatewayFactory.register(GatewayType.MPESA_TILL_NO_API)
class MPesaTillManualGateway(ManualPaymentGateway):
    """
    M-PESA Till without API integration.

    Provides payment instructions for customers to pay via M-PESA Buy Goods.
    """

    @property
    def gateway_name(self) -> str:
        return "M-PESA Till (Manual)"

    def _validate_config(self) -> None:
        """Validate till number is provided."""
        if not self.config.get("till_number"):
            raise ValueError("Till number is required")

    def _get_payment_instructions(
        self,
        amount: Decimal,
        reference: str,
    ) -> str:
        """Get M-PESA Till payment instructions."""
        till = self.config.get("till_number", "")

        instructions = f"""
Pay via M-PESA Buy Goods:

1. Go to M-PESA menu
2. Select "Lipa na M-PESA"
3. Select "Buy Goods and Services"
4. Enter Till Number: {till}
5. Enter Amount: KES {amount:,.0f}
6. Enter your M-PESA PIN
7. Confirm the transaction

Your payment will be confirmed within 24 hours.
Reference: {reference}
"""
        return instructions.strip()


@PaymentGatewayFactory.register(GatewayType.BANK_ACCOUNT)
class BankAccountGateway(ManualPaymentGateway):
    """
    Bank account transfer gateway.

    Provides bank details for customers to make direct transfers.
    """

    @property
    def gateway_name(self) -> str:
        return "Bank Transfer"

    def _validate_config(self) -> None:
        """Validate bank details are provided."""
        required = ["bank_name", "bank_account_number"]
        missing = [f for f in required if not self.config.get(f)]
        if missing:
            raise ValueError(f"Missing required bank details: {missing}")

    def _get_payment_instructions(
        self,
        amount: Decimal,
        reference: str,
    ) -> str:
        """Get bank transfer instructions."""
        bank_name = self.config.get("bank_name", "")
        account_number = self.config.get("bank_account_number", "")
        account_name = self.config.get("bank_account_name", "")
        branch = self.config.get("bank_branch", "")
        swift_code = self.config.get("bank_swift_code", "")

        # Check if there's a paybill for the bank
        paybill = self.config.get("paybill_number", "")

        instructions = f"""
Bank Transfer Details:

Bank: {bank_name}
Account Number: {account_number}
Account Name: {account_name}
"""

        if branch:
            instructions += f"Branch: {branch}\n"

        if swift_code:
            instructions += f"SWIFT Code: {swift_code}\n"

        instructions += f"""
Amount: KES {amount:,.0f}
Reference: {reference}

Please include the reference number in your transfer description.
"""

        if paybill:
            instructions += f"""
Alternatively, pay via M-PESA:
1. Lipa na M-PESA > Pay Bill
2. Business Number: {paybill}
3. Account Number: {account_number}
4. Amount: KES {amount:,.0f}
"""

        instructions += "\nYour payment will be confirmed within 1-2 business days."

        return instructions.strip()
