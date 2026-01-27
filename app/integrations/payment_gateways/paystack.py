"""
Paystack payment gateway integration.

Supports card payments, bank transfers, and mobile money.
Used primarily for platform billing (collecting ISP subscriptions).

Features:
- Transaction initialization (card, bank, mobile money)
- Transaction verification
- Webhook processing
- Refunds
- Subscription/plan management
- Transfer/payout to bank accounts and mobile money
- Account verification

Documentation: https://paystack.com/docs/api/
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx

from app.models.payment_gateway import GatewayType
from .base import (
    PaymentGatewayInterface,
    PaymentInitiationResult,
    PaymentVerificationResult,
    PaymentCallbackResult,
    BalanceResult,
    RefundResult,
    PaymentStatus,
)
from .factory import PaymentGatewayFactory

logger = logging.getLogger(__name__)


@PaymentGatewayFactory.register(GatewayType.PAYSTACK)
class PaystackGateway(PaymentGatewayInterface):
    """
    Paystack payment gateway implementation.

    Supports card payments, bank transfers, mobile money,
    and recurring subscriptions.
    """

    BASE_URL = "https://api.paystack.co"

    def __init__(self, config: Dict[str, Any]):
        """Initialize Paystack gateway."""
        super().__init__(config)

    def _validate_config(self) -> None:
        """Validate Paystack configuration."""
        credentials = self.config.get("credentials", {})

        if not credentials.get("secret_key"):
            raise ValueError("Paystack secret_key is required")

    @property
    def gateway_name(self) -> str:
        return "Paystack"

    @property
    def supports_stk_push(self) -> bool:
        return False  # Uses redirect-based flow

    @property
    def supports_c2b(self) -> bool:
        return True

    @property
    def supports_b2c(self) -> bool:
        return True  # Supports transfers

    @property
    def supports_refunds(self) -> bool:
        return True

    @property
    def _secret_key(self) -> str:
        """Get secret key."""
        return self.config.get("credentials", {}).get("secret_key", "")

    @property
    def _headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }

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
        Initialize a Paystack transaction.

        Returns a checkout URL for the customer to complete payment.
        """
        try:
            # Amount in kobo (smallest currency unit)
            amount_kobo = int(amount * 100)

            # Get email from metadata or use phone as email placeholder
            email = (metadata or {}).get("email", f"{phone_number}@customer.local")

            callback = callback_url or self.config.get("callback_url", "")

            payload = {
                "email": email,
                "amount": amount_kobo,
                "reference": reference,
                "callback_url": callback,
                "metadata": {
                    "phone_number": phone_number,
                    "description": description,
                    **(metadata or {}),
                },
            }

            # Add channels if specified
            channels = self.config.get("channels")
            if channels:
                payload["channels"] = channels

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/transaction/initialize",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack initialize response: {data}")

                if data.get("status"):
                    return PaymentInitiationResult(
                        success=True,
                        transaction_reference=reference,
                        gateway_reference=data["data"].get("access_code"),
                        status=PaymentStatus.PENDING,
                        checkout_url=data["data"].get("authorization_url"),
                        message="Payment initialized",
                        metadata={
                            "access_code": data["data"].get("access_code"),
                            "authorization_url": data["data"].get("authorization_url"),
                        },
                    )
                else:
                    return PaymentInitiationResult(
                        success=False,
                        transaction_reference=reference,
                        status=PaymentStatus.FAILED,
                        message=data.get("message", "Initialization failed"),
                    )

        except Exception as e:
            logger.error(f"Paystack initialization error: {e}")
            return PaymentInitiationResult(
                success=False,
                transaction_reference=reference,
                status=PaymentStatus.FAILED,
                message=str(e),
            )

    async def verify_payment(
        self,
        transaction_reference: str,
    ) -> PaymentVerificationResult:
        """
        Verify a Paystack transaction.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/transaction/verify/{transaction_reference}",
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack verify response: {data}")

                if data.get("status") and data.get("data"):
                    tx_data = data["data"]
                    status = tx_data.get("status", "")

                    payment_status = PaymentStatus.PENDING
                    if status == "success":
                        payment_status = PaymentStatus.COMPLETED
                    elif status == "failed":
                        payment_status = PaymentStatus.FAILED
                    elif status == "abandoned":
                        payment_status = PaymentStatus.CANCELLED

                    return PaymentVerificationResult(
                        success=status == "success",
                        transaction_reference=transaction_reference,
                        status=payment_status,
                        amount=Decimal(str(tx_data.get("amount", 0))) / 100,
                        currency=tx_data.get("currency", "KES"),
                        gateway_reference=str(tx_data.get("id", "")),
                        paid_at=datetime.fromisoformat(tx_data["paid_at"].replace("Z", "+00:00")) if tx_data.get("paid_at") else None,
                        payer_phone=tx_data.get("metadata", {}).get("phone_number"),
                        message=tx_data.get("gateway_response", ""),
                        raw_response=data,
                    )
                else:
                    return PaymentVerificationResult(
                        success=False,
                        transaction_reference=transaction_reference,
                        status=PaymentStatus.FAILED,
                        message=data.get("message", "Verification failed"),
                        raw_response=data,
                    )

        except Exception as e:
            logger.error(f"Paystack verification error: {e}")
            return PaymentVerificationResult(
                success=False,
                transaction_reference=transaction_reference,
                status=PaymentStatus.PENDING,
                message=str(e),
            )

    async def process_callback(
        self,
        callback_data: Dict[str, Any],
    ) -> PaymentCallbackResult:
        """
        Process Paystack webhook.
        """
        try:
            event = callback_data.get("event", "")
            data = callback_data.get("data", {})

            if event == "charge.success":
                return PaymentCallbackResult(
                    success=True,
                    transaction_reference=data.get("reference", ""),
                    status=PaymentStatus.COMPLETED,
                    amount=Decimal(str(data.get("amount", 0))) / 100,
                    currency=data.get("currency", "KES"),
                    gateway_reference=str(data.get("id", "")),
                    paid_at=datetime.fromisoformat(data["paid_at"].replace("Z", "+00:00")) if data.get("paid_at") else None,
                    payer_phone=data.get("metadata", {}).get("phone_number"),
                    message="Payment successful",
                    raw_data=callback_data,
                )
            elif event == "charge.failed":
                return PaymentCallbackResult(
                    success=False,
                    transaction_reference=data.get("reference", ""),
                    status=PaymentStatus.FAILED,
                    message=data.get("gateway_response", "Payment failed"),
                    raw_data=callback_data,
                )
            else:
                return PaymentCallbackResult(
                    success=False,
                    transaction_reference=data.get("reference", ""),
                    status=PaymentStatus.PENDING,
                    message=f"Unknown event: {event}",
                    raw_data=callback_data,
                )

        except Exception as e:
            logger.error(f"Paystack callback processing error: {e}")
            return PaymentCallbackResult(
                success=False,
                transaction_reference="",
                status=PaymentStatus.FAILED,
                message=str(e),
                raw_data=callback_data,
            )

    def verify_webhook_signature(
        self,
        payload: str,
        signature: str,
    ) -> bool:
        """
        Verify Paystack webhook signature.

        Paystack sends a SHA512 HMAC signature in the x-paystack-signature header.
        This should be verified before processing any webhook event.

        Args:
            payload: Raw request body as string
            signature: Value of x-paystack-signature header

        Returns:
            True if signature is valid, False otherwise
        """
        import hashlib
        import hmac

        try:
            expected_signature = hmac.new(
                self._secret_key.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha512,
            ).hexdigest()

            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return False

    async def refund_payment(
        self,
        transaction_reference: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
    ) -> RefundResult:
        """
        Initiate a refund.
        """
        try:
            # First verify the transaction to get the transaction ID
            verification = await self.verify_payment(transaction_reference)
            if not verification.gateway_reference:
                return RefundResult(
                    success=False,
                    transaction_reference=transaction_reference,
                    message="Could not find transaction to refund",
                )

            payload = {
                "transaction": verification.gateway_reference,
            }

            if amount:
                payload["amount"] = int(amount * 100)

            if reason:
                payload["merchant_note"] = reason

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/refund",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack refund response: {data}")

                if data.get("status"):
                    return RefundResult(
                        success=True,
                        transaction_reference=transaction_reference,
                        refund_reference=str(data["data"].get("id", "")),
                        amount=Decimal(str(data["data"].get("amount", 0))) / 100,
                        status=PaymentStatus.COMPLETED,
                        message="Refund processed",
                        raw_response=data,
                    )
                else:
                    return RefundResult(
                        success=False,
                        transaction_reference=transaction_reference,
                        message=data.get("message", "Refund failed"),
                        raw_response=data,
                    )

        except Exception as e:
            logger.error(f"Paystack refund error: {e}")
            return RefundResult(
                success=False,
                transaction_reference=transaction_reference,
                message=str(e),
            )

    async def get_balance(self) -> BalanceResult:
        """
        Get Paystack balance.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/balance",
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack balance response: {data}")

                if data.get("status") and data.get("data"):
                    balances = data["data"]
                    # Get KES balance
                    kes_balance = next(
                        (b for b in balances if b.get("currency") == "KES"),
                        balances[0] if balances else {}
                    )

                    return BalanceResult(
                        success=True,
                        available_balance=Decimal(str(kes_balance.get("balance", 0))) / 100,
                        currency=kes_balance.get("currency", "KES"),
                        raw_response=data,
                    )
                else:
                    return BalanceResult(
                        success=False,
                        message=data.get("message", "Balance query failed"),
                        raw_response=data,
                    )

        except Exception as e:
            logger.error(f"Paystack balance error: {e}")
            return BalanceResult(
                success=False,
                message=str(e),
            )

    async def create_subscription(
        self,
        email: str,
        plan_code: str,
        authorization_code: Optional[str] = None,
        start_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Create a subscription for recurring billing.
        """
        try:
            payload = {
                "customer": email,
                "plan": plan_code,
            }

            if authorization_code:
                payload["authorization"] = authorization_code

            if start_date:
                payload["start_date"] = start_date.isoformat()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/subscription",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack subscription response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack subscription error: {e}")
            return {"status": False, "message": str(e)}

    async def charge_authorization(
        self,
        email: str,
        amount: Decimal,
        authorization_code: str,
        reference: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentInitiationResult:
        """
        Charge a saved card authorization.

        Used for recurring payments.
        """
        try:
            amount_kobo = int(amount * 100)

            payload = {
                "email": email,
                "amount": amount_kobo,
                "authorization_code": authorization_code,
                "reference": reference,
                "metadata": metadata or {},
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/transaction/charge_authorization",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack charge authorization response: {data}")

                if data.get("status") and data["data"].get("status") == "success":
                    return PaymentInitiationResult(
                        success=True,
                        transaction_reference=reference,
                        gateway_reference=str(data["data"].get("id", "")),
                        status=PaymentStatus.COMPLETED,
                        message="Payment successful",
                        metadata=data["data"],
                    )
                else:
                    return PaymentInitiationResult(
                        success=False,
                        transaction_reference=reference,
                        status=PaymentStatus.FAILED,
                        message=data.get("message", "Charge failed"),
                    )

        except Exception as e:
            logger.error(f"Paystack charge authorization error: {e}")
            return PaymentInitiationResult(
                success=False,
                transaction_reference=reference,
                status=PaymentStatus.FAILED,
                message=str(e),
            )

    # ==================== SUBSCRIPTION MANAGEMENT ====================

    async def list_plans(self) -> Dict[str, Any]:
        """
        List all subscription plans.

        Returns:
            Dictionary with plans data
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/plan",
                    headers=self._headers,
                    timeout=30.0,
                )
                data = response.json()
                logger.info(f"Paystack list plans response: {data}")
                return data
        except Exception as e:
            logger.error(f"Paystack list plans error: {e}")
            return {"status": False, "message": str(e)}

    async def create_plan(
        self,
        name: str,
        amount: Decimal,
        interval: str = "monthly",
        currency: str = "KES",
        description: Optional[str] = None,
        send_invoices: bool = True,
        send_sms: bool = True,
        invoice_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a subscription plan.

        Args:
            name: Plan name
            amount: Amount in main currency unit
            interval: Billing interval (hourly, daily, weekly, monthly, annually)
            currency: Currency code
            description: Plan description
            send_invoices: Whether to send invoice emails
            send_sms: Whether to send SMS notifications
            invoice_limit: Number of times to charge subscriber

        Returns:
            Plan creation response with plan_code
        """
        try:
            payload = {
                "name": name,
                "amount": int(amount * 100),
                "interval": interval,
                "currency": currency,
                "send_invoices": send_invoices,
                "send_sms": send_sms,
            }

            if description:
                payload["description"] = description
            if invoice_limit:
                payload["invoice_limit"] = invoice_limit

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/plan",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )
                data = response.json()
                logger.info(f"Paystack create plan response: {data}")
                return data
        except Exception as e:
            logger.error(f"Paystack create plan error: {e}")
            return {"status": False, "message": str(e)}

    async def get_subscription(self, subscription_code: str) -> Dict[str, Any]:
        """
        Get subscription details.

        Args:
            subscription_code: Subscription code or ID

        Returns:
            Subscription details
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/subscription/{subscription_code}",
                    headers=self._headers,
                    timeout=30.0,
                )
                data = response.json()
                logger.info(f"Paystack get subscription response: {data}")
                return data
        except Exception as e:
            logger.error(f"Paystack get subscription error: {e}")
            return {"status": False, "message": str(e)}

    async def disable_subscription(
        self,
        subscription_code: str,
        email_token: str,
    ) -> Dict[str, Any]:
        """
        Disable a subscription.

        Args:
            subscription_code: Subscription code
            email_token: Token sent to customer email

        Returns:
            Disable response
        """
        try:
            payload = {
                "code": subscription_code,
                "token": email_token,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/subscription/disable",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )
                data = response.json()
                logger.info(f"Paystack disable subscription response: {data}")
                return data
        except Exception as e:
            logger.error(f"Paystack disable subscription error: {e}")
            return {"status": False, "message": str(e)}

    async def enable_subscription(
        self,
        subscription_code: str,
        email_token: str,
    ) -> Dict[str, Any]:
        """
        Enable a disabled subscription.

        Args:
            subscription_code: Subscription code
            email_token: Token sent to customer email

        Returns:
            Enable response
        """
        try:
            payload = {
                "code": subscription_code,
                "token": email_token,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/subscription/enable",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )
                data = response.json()
                logger.info(f"Paystack enable subscription response: {data}")
                return data
        except Exception as e:
            logger.error(f"Paystack enable subscription error: {e}")
            return {"status": False, "message": str(e)}

    # ==================== TRANSFER / PAYOUT METHODS ====================

    async def create_transfer_recipient(
        self,
        recipient_type: str,
        name: str,
        account_number: str,
        bank_code: str,
        currency: str = "KES",
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a transfer recipient for payouts.

        Args:
            recipient_type: "nuban" (bank), "mobile_money", "basa" (bank SA)
            name: Recipient name
            account_number: Bank account or mobile money number
            bank_code: Bank code from list_banks()
            currency: Currency code
            description: Recipient description
            metadata: Additional metadata

        Returns:
            Dictionary with recipient_code for transfers
        """
        try:
            payload = {
                "type": recipient_type,
                "name": name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": currency,
            }

            if description:
                payload["description"] = description
            if metadata:
                payload["metadata"] = metadata

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/transferrecipient",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack create recipient response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack create recipient error: {e}")
            return {"status": False, "message": str(e)}

    async def initiate_transfer(
        self,
        amount: Decimal,
        recipient_code: str,
        reference: Optional[str] = None,
        reason: Optional[str] = None,
        currency: str = "KES",
    ) -> Dict[str, Any]:
        """
        Initiate a transfer/payout to a recipient.

        Args:
            amount: Amount in main currency unit
            recipient_code: Recipient code from create_transfer_recipient
            reference: Unique transfer reference
            reason: Transfer reason/description
            currency: Currency code

        Returns:
            Transfer initiation response with transfer_code
        """
        try:
            payload = {
                "source": "balance",
                "amount": int(amount * 100),
                "recipient": recipient_code,
                "currency": currency,
            }

            if reference:
                payload["reference"] = reference
            if reason:
                payload["reason"] = reason

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/transfer",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack transfer response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack transfer error: {e}")
            return {"status": False, "message": str(e)}

    async def finalize_transfer(
        self,
        transfer_code: str,
        otp: str,
    ) -> Dict[str, Any]:
        """
        Finalize a transfer with OTP (when 2FA is enabled).

        Args:
            transfer_code: Transfer code from initiate_transfer
            otp: OTP sent to account holder

        Returns:
            Transfer finalization response
        """
        try:
            payload = {
                "transfer_code": transfer_code,
                "otp": otp,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/transfer/finalize_transfer",
                    json=payload,
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack finalize transfer response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack finalize transfer error: {e}")
            return {"status": False, "message": str(e)}

    async def initiate_bulk_transfer(
        self,
        transfers: List[Dict[str, Any]],
        currency: str = "KES",
    ) -> Dict[str, Any]:
        """
        Initiate multiple transfers in a single request.

        Args:
            transfers: List of transfer dicts with:
                - amount: Amount in kobo/pesewas
                - recipient: Recipient code
                - reference: Unique reference (optional)
                - reason: Transfer reason (optional)
            currency: Currency code

        Returns:
            Bulk transfer response
        """
        try:
            payload = {
                "source": "balance",
                "currency": currency,
                "transfers": transfers,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/transfer/bulk",
                    json=payload,
                    headers=self._headers,
                    timeout=60.0,  # Longer timeout for bulk
                )

                data = response.json()
                logger.info(f"Paystack bulk transfer response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack bulk transfer error: {e}")
            return {"status": False, "message": str(e)}

    async def verify_transfer(self, reference: str) -> Dict[str, Any]:
        """
        Verify a transfer status.

        Args:
            reference: Transfer reference

        Returns:
            Transfer verification response
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/transfer/verify/{reference}",
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack verify transfer response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack verify transfer error: {e}")
            return {"status": False, "message": str(e)}

    async def list_banks(self, country: str = "kenya") -> Dict[str, Any]:
        """
        Get list of banks for transfers.

        Args:
            country: Country code (nigeria, ghana, south-africa, kenya)

        Returns:
            List of supported banks with codes
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/bank?country={country}",
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack list banks response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack list banks error: {e}")
            return {"status": False, "message": str(e)}

    async def list_mobile_money_providers(self, country: str = "kenya") -> Dict[str, Any]:
        """
        Get list of mobile money providers for transfers.

        Args:
            country: Country code

        Returns:
            List of mobile money providers
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/bank?country={country}&type=mobile_money",
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack mobile money providers response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack mobile money providers error: {e}")
            return {"status": False, "message": str(e)}

    async def resolve_account_number(
        self,
        account_number: str,
        bank_code: str,
    ) -> Dict[str, Any]:
        """
        Resolve bank account to get account name.

        Args:
            account_number: Bank account number
            bank_code: Bank code

        Returns:
            Account details including account_name
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/bank/resolve?account_number={account_number}&bank_code={bank_code}",
                    headers=self._headers,
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"Paystack resolve account response: {data}")
                return data

        except Exception as e:
            logger.error(f"Paystack resolve account error: {e}")
            return {"status": False, "message": str(e)}