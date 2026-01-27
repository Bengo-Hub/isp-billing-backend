"""
M-PESA Daraja API integration.

Implements the complete Safaricom M-PESA Daraja API including:
- OAuth Token Generation
- STK Push (Lipa na M-Pesa)
- STK Push Query
- C2B URL Registration
- C2B Simulation
- B2C Payment (refunds/disbursements)
- B2B Payment
- Transaction Status Query
- Transaction Reversal
- Account Balance Query
"""

import base64
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

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
    TransactionHistoryResult,
)
from .factory import PaymentGatewayFactory

logger = logging.getLogger(__name__)


class MPesaAPIError(Exception):
    """M-PESA API error."""

    def __init__(self, message: str, response_code: Optional[str] = None, response: Optional[Dict] = None):
        super().__init__(message)
        self.response_code = response_code
        self.response = response or {}


@PaymentGatewayFactory.register(GatewayType.MPESA_PAYBILL)
class MPesaPaybillGateway(PaymentGatewayInterface):
    """
    M-PESA Paybill gateway implementation.

    Supports STK Push, C2B, B2C, and all Daraja APIs.
    """

    # API endpoints
    SANDBOX_BASE_URL = "https://sandbox.safaricom.co.ke"
    PRODUCTION_BASE_URL = "https://api.safaricom.co.ke"

    def __init__(self, config: Dict[str, Any]):
        """Initialize M-PESA Paybill gateway."""
        super().__init__(config)
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None

    def _validate_config(self) -> None:
        """Validate M-PESA configuration."""
        credentials = self.config.get("credentials", {})
        required = ["consumer_key", "consumer_secret", "passkey"]

        missing = [f for f in required if not credentials.get(f)]
        if missing:
            raise ValueError(f"Missing required M-PESA credentials: {missing}")

        # Shortcode required for Paybill
        if not (credentials.get("shortcode") or self.config.get("paybill_number")):
            raise ValueError("Shortcode or paybill_number is required")

    @property
    def gateway_name(self) -> str:
        return "M-PESA Paybill"

    @property
    def supports_stk_push(self) -> bool:
        return True

    @property
    def supports_c2b(self) -> bool:
        return True

    @property
    def supports_b2c(self) -> bool:
        return True

    @property
    def supports_refunds(self) -> bool:
        return True

    @property
    def _base_url(self) -> str:
        """Get base URL based on environment."""
        credentials = self.config.get("credentials", {})
        is_sandbox = credentials.get("environment", "sandbox") == "sandbox"
        return self.SANDBOX_BASE_URL if is_sandbox else self.PRODUCTION_BASE_URL

    @property
    def _shortcode(self) -> str:
        """Get the shortcode."""
        credentials = self.config.get("credentials", {})
        return credentials.get("shortcode") or self.config.get("paybill_number", "")

    async def _get_access_token(self) -> str:
        """
        Get OAuth access token from Safaricom.

        Caches the token and refreshes when expired.
        """
        # Check if cached token is still valid
        if self._access_token and self._token_expires:
            if datetime.utcnow() < self._token_expires:
                return self._access_token

        credentials = self.config.get("credentials", {})
        consumer_key = credentials.get("consumer_key")
        consumer_secret = credentials.get("consumer_secret")

        # Create Basic Auth header
        auth_string = f"{consumer_key}:{consumer_secret}"
        auth_bytes = base64.b64encode(auth_string.encode()).decode()

        url = f"{self._base_url}/oauth/v1/generate?grant_type=client_credentials"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Basic {auth_bytes}"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                self._access_token = data.get("access_token")
                expires_in = int(data.get("expires_in", 3600))

                # Set expiry with 60 second buffer
                from datetime import timedelta
                self._token_expires = datetime.utcnow() + timedelta(seconds=expires_in - 60)

                return self._access_token

            except httpx.HTTPError as e:
                logger.error(f"M-PESA OAuth error: {e}")
                raise MPesaAPIError(f"Failed to get access token: {e}")

    def _generate_password(self, timestamp: str) -> str:
        """Generate STK push password."""
        credentials = self.config.get("credentials", {})
        passkey = credentials.get("passkey", "")
        shortcode = self._shortcode

        password_string = f"{shortcode}{passkey}{timestamp}"
        return base64.b64encode(password_string.encode()).decode()

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
        Initiate STK Push payment.

        Sends a payment prompt to the customer's phone.
        """
        try:
            access_token = await self._get_access_token()

            # Format phone number
            phone = self.format_phone_number(phone_number)

            # Generate timestamp and password
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            password = self._generate_password(timestamp)

            # Get callback URL
            callback = callback_url or self.config.get("callback_url", "")

            # Prepare request
            url = f"{self._base_url}/mpesa/stkpush/v1/processrequest"
            payload = {
                "BusinessShortCode": self._shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": int(amount),
                "PartyA": phone,
                "PartyB": self._shortcode,
                "PhoneNumber": phone,
                "CallBackURL": callback,
                "AccountReference": reference[:12],  # Max 12 chars
                "TransactionDesc": description[:13],  # Max 13 chars
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA STK Push response: {data}")

                # Check response
                response_code = data.get("ResponseCode", "")
                if response_code == "0":
                    return PaymentInitiationResult(
                        success=True,
                        transaction_reference=reference,
                        gateway_reference=data.get("CheckoutRequestID", ""),
                        status=PaymentStatus.PENDING,
                        message=data.get("ResponseDescription", "STK Push sent"),
                        metadata={
                            "merchant_request_id": data.get("MerchantRequestID"),
                            "checkout_request_id": data.get("CheckoutRequestID"),
                            **(metadata or {}),
                        },
                    )
                else:
                    return PaymentInitiationResult(
                        success=False,
                        transaction_reference=reference,
                        status=PaymentStatus.FAILED,
                        message=data.get("ResponseDescription", "STK Push failed"),
                        metadata={"raw_response": data},
                    )

        except Exception as e:
            logger.error(f"M-PESA STK Push error: {e}")
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
        Query STK Push status.

        Uses the CheckoutRequestID to check payment status.
        """
        try:
            access_token = await self._get_access_token()

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            password = self._generate_password(timestamp)

            url = f"{self._base_url}/mpesa/stkpushquery/v1/query"
            payload = {
                "BusinessShortCode": self._shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": transaction_reference,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA STK Query response: {data}")

                result_code = data.get("ResultCode", "")

                if result_code == "0":
                    return PaymentVerificationResult(
                        success=True,
                        transaction_reference=transaction_reference,
                        status=PaymentStatus.COMPLETED,
                        message="Payment successful",
                        raw_response=data,
                    )
                elif result_code == "1032":
                    return PaymentVerificationResult(
                        success=False,
                        transaction_reference=transaction_reference,
                        status=PaymentStatus.CANCELLED,
                        message="Payment cancelled by user",
                        raw_response=data,
                    )
                elif result_code == "1":
                    return PaymentVerificationResult(
                        success=False,
                        transaction_reference=transaction_reference,
                        status=PaymentStatus.FAILED,
                        message="Insufficient balance",
                        raw_response=data,
                    )
                else:
                    return PaymentVerificationResult(
                        success=False,
                        transaction_reference=transaction_reference,
                        status=PaymentStatus.PENDING,
                        message=data.get("ResultDesc", "Status unknown"),
                        raw_response=data,
                    )

        except Exception as e:
            logger.error(f"M-PESA STK Query error: {e}")
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
        Process M-PESA callback.

        Parses the callback data and extracts payment details.
        """
        try:
            # Extract data from nested structure
            body = callback_data.get("Body", {})
            stk_callback = body.get("stkCallback", {})

            result_code = stk_callback.get("ResultCode", -1)
            checkout_request_id = stk_callback.get("CheckoutRequestID", "")

            if result_code == 0:
                # Payment successful - extract details
                callback_metadata = stk_callback.get("CallbackMetadata", {})
                items = callback_metadata.get("Item", [])

                amount = None
                mpesa_receipt = None
                phone = None
                transaction_date = None

                for item in items:
                    name = item.get("Name", "")
                    value = item.get("Value")

                    if name == "Amount":
                        amount = Decimal(str(value))
                    elif name == "MpesaReceiptNumber":
                        mpesa_receipt = value
                    elif name == "PhoneNumber":
                        phone = str(value)
                    elif name == "TransactionDate":
                        transaction_date = datetime.strptime(str(value), "%Y%m%d%H%M%S")

                return PaymentCallbackResult(
                    success=True,
                    transaction_reference=checkout_request_id,
                    status=PaymentStatus.COMPLETED,
                    amount=amount,
                    currency="KES",
                    gateway_reference=mpesa_receipt,
                    paid_at=transaction_date,
                    payer_phone=phone,
                    message="Payment completed successfully",
                    raw_data=callback_data,
                )
            else:
                return PaymentCallbackResult(
                    success=False,
                    transaction_reference=checkout_request_id,
                    status=PaymentStatus.FAILED,
                    message=stk_callback.get("ResultDesc", "Payment failed"),
                    raw_data=callback_data,
                )

        except Exception as e:
            logger.error(f"M-PESA callback processing error: {e}")
            return PaymentCallbackResult(
                success=False,
                transaction_reference="",
                status=PaymentStatus.FAILED,
                message=str(e),
                raw_data=callback_data,
            )

    async def get_balance(self) -> BalanceResult:
        """
        Query M-PESA account balance.

        Uses the Account Balance API.
        """
        try:
            access_token = await self._get_access_token()
            credentials = self.config.get("credentials", {})

            url = f"{self._base_url}/mpesa/accountbalance/v1/query"
            payload = {
                "Initiator": credentials.get("initiator_name", ""),
                "SecurityCredential": credentials.get("security_credential", ""),
                "CommandID": "AccountBalance",
                "PartyA": self._shortcode,
                "IdentifierType": "4",  # Shortcode
                "Remarks": "Balance query",
                "QueueTimeOutURL": self.config.get("timeout_url", ""),
                "ResultURL": self.config.get("result_url", ""),
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA Balance response: {data}")

                if data.get("ResponseCode") == "0":
                    return BalanceResult(
                        success=True,
                        message="Balance request submitted. Check callback for results.",
                        raw_response=data,
                    )
                else:
                    return BalanceResult(
                        success=False,
                        message=data.get("ResponseDescription", "Balance query failed"),
                        raw_response=data,
                    )

        except Exception as e:
            logger.error(f"M-PESA balance query error: {e}")
            return BalanceResult(
                success=False,
                message=str(e),
            )

    async def refund_payment(
        self,
        transaction_reference: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
    ) -> RefundResult:
        """
        Initiate payment reversal.

        Uses the Transaction Reversal API.
        """
        try:
            access_token = await self._get_access_token()
            credentials = self.config.get("credentials", {})

            url = f"{self._base_url}/mpesa/reversal/v1/request"
            payload = {
                "Initiator": credentials.get("initiator_name", ""),
                "SecurityCredential": credentials.get("security_credential", ""),
                "CommandID": "TransactionReversal",
                "TransactionID": transaction_reference,
                "Amount": int(amount) if amount else 0,
                "ReceiverParty": self._shortcode,
                "RecieverIdentifierType": "4",  # Shortcode
                "Remarks": reason or "Payment reversal",
                "QueueTimeOutURL": self.config.get("timeout_url", ""),
                "ResultURL": self.config.get("result_url", ""),
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA Reversal response: {data}")

                if data.get("ResponseCode") == "0":
                    return RefundResult(
                        success=True,
                        transaction_reference=transaction_reference,
                        refund_reference=data.get("ConversationID"),
                        status=PaymentStatus.PENDING,
                        message="Reversal request submitted",
                        raw_response=data,
                    )
                else:
                    return RefundResult(
                        success=False,
                        transaction_reference=transaction_reference,
                        message=data.get("ResponseDescription", "Reversal failed"),
                        raw_response=data,
                    )

        except Exception as e:
            logger.error(f"M-PESA reversal error: {e}")
            return RefundResult(
                success=False,
                transaction_reference=transaction_reference,
                message=str(e),
            )

    async def register_c2b_urls(
        self,
        validation_url: str,
        confirmation_url: str,
        response_type: str = "Completed",
    ) -> Dict[str, Any]:
        """
        Register C2B callback URLs.

        Must be called once to register validation and confirmation URLs.
        """
        try:
            access_token = await self._get_access_token()

            url = f"{self._base_url}/mpesa/c2b/v1/registerurl"
            payload = {
                "ShortCode": self._shortcode,
                "ResponseType": response_type,  # "Completed" or "Cancelled"
                "ConfirmationURL": confirmation_url,
                "ValidationURL": validation_url,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA C2B URL registration response: {data}")
                return data

        except Exception as e:
            logger.error(f"M-PESA C2B URL registration error: {e}")
            return {"error": str(e)}

    async def b2c_payment(
        self,
        phone_number: str,
        amount: Decimal,
        reference: str,
        occasion: str = "Business Payment",
    ) -> Dict[str, Any]:
        """
        Initiate B2C payment (business to customer).

        Used for disbursements, refunds, salary payments, etc.
        """
        try:
            access_token = await self._get_access_token()
            credentials = self.config.get("credentials", {})

            phone = self.format_phone_number(phone_number)

            url = f"{self._base_url}/mpesa/b2c/v1/paymentrequest"
            payload = {
                "InitiatorName": credentials.get("initiator_name", ""),
                "SecurityCredential": credentials.get("security_credential", ""),
                "CommandID": "BusinessPayment",  # or SalaryPayment, PromotionPayment
                "Amount": int(amount),
                "PartyA": self._shortcode,
                "PartyB": phone,
                "Remarks": reference,
                "QueueTimeOutURL": self.config.get("timeout_url", ""),
                "ResultURL": self.config.get("result_url", ""),
                "Occasion": occasion,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA B2C response: {data}")
                return data

        except Exception as e:
            logger.error(f"M-PESA B2C error: {e}")
            return {"error": str(e)}

    async def transaction_status(
        self,
        transaction_id: str,
        identifier_type: str = "4",  # 1=MSISDN, 2=TillNumber, 4=Shortcode
    ) -> Dict[str, Any]:
        """
        Query transaction status.

        Checks the status of any M-PESA transaction.
        """
        try:
            access_token = await self._get_access_token()
            credentials = self.config.get("credentials", {})

            url = f"{self._base_url}/mpesa/transactionstatus/v1/query"
            payload = {
                "Initiator": credentials.get("initiator_name", ""),
                "SecurityCredential": credentials.get("security_credential", ""),
                "CommandID": "TransactionStatusQuery",
                "TransactionID": transaction_id,
                "PartyA": self._shortcode,
                "IdentifierType": identifier_type,
                "Remarks": "Transaction status query",
                "QueueTimeOutURL": self.config.get("timeout_url", ""),
                "ResultURL": self.config.get("result_url", ""),
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA Transaction Status response: {data}")
                return data

        except Exception as e:
            logger.error(f"M-PESA transaction status error: {e}")
            return {"error": str(e)}


@PaymentGatewayFactory.register(GatewayType.MPESA_TILL)
class MPesaTillGateway(MPesaPaybillGateway):
    """
    M-PESA Till/Buy Goods gateway implementation.

    Similar to Paybill but uses Till number and different transaction type.
    """

    @property
    def gateway_name(self) -> str:
        return "M-PESA Till"

    @property
    def supports_b2c(self) -> bool:
        return False

    @property
    def supports_refunds(self) -> bool:
        return False

    @property
    def _shortcode(self) -> str:
        """Get the till number."""
        credentials = self.config.get("credentials", {})
        return credentials.get("till_number") or self.config.get("till_number", "")

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
        Initiate STK Push for Till payment.

        Uses CustomerBuyGoodsOnline transaction type.
        """
        try:
            access_token = await self._get_access_token()

            phone = self.format_phone_number(phone_number)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            password = self._generate_password(timestamp)
            callback = callback_url or self.config.get("callback_url", "")

            url = f"{self._base_url}/mpesa/stkpush/v1/processrequest"
            payload = {
                "BusinessShortCode": self._shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerBuyGoodsOnline",  # Different from Paybill
                "Amount": int(amount),
                "PartyA": phone,
                "PartyB": self._shortcode,
                "PhoneNumber": phone,
                "CallBackURL": callback,
                "AccountReference": reference[:12],
                "TransactionDesc": description[:13],
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                data = response.json()
                logger.info(f"M-PESA Till STK Push response: {data}")

                response_code = data.get("ResponseCode", "")
                if response_code == "0":
                    return PaymentInitiationResult(
                        success=True,
                        transaction_reference=reference,
                        gateway_reference=data.get("CheckoutRequestID", ""),
                        status=PaymentStatus.PENDING,
                        message=data.get("ResponseDescription", "STK Push sent"),
                        metadata={
                            "merchant_request_id": data.get("MerchantRequestID"),
                            "checkout_request_id": data.get("CheckoutRequestID"),
                            **(metadata or {}),
                        },
                    )
                else:
                    return PaymentInitiationResult(
                        success=False,
                        transaction_reference=reference,
                        status=PaymentStatus.FAILED,
                        message=data.get("ResponseDescription", "STK Push failed"),
                        metadata={"raw_response": data},
                    )

        except Exception as e:
            logger.error(f"M-PESA Till STK Push error: {e}")
            return PaymentInitiationResult(
                success=False,
                transaction_reference=reference,
                status=PaymentStatus.FAILED,
                message=str(e),
            )
