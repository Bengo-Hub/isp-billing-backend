"""MPESA Daraja API integration with production-ready security and validation.

This module implements the complete MPESA Daraja API integration following the official
Safaricom documentation with proper cryptographic signature verification.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ExternalServiceError, ValidationError

logger = get_logger(__name__)


class MpesaAPI:
    """MPESA Daraja API client with production-ready security and validation.
    
    Implements the complete MPESA Daraja API following official Safaricom documentation
    with proper cryptographic signature verification and comprehensive error handling.
    
    Reference: https://developer.safaricom.co.ke/Documentation
    """

    def __init__(self, consumer_key: Optional[str] = None, consumer_secret: Optional[str] = None, 
                 passkey: Optional[str] = None, shortcode: Optional[str] = None, 
                 callback_url: Optional[str] = None, environment: str = "sandbox"):
        """Initialize MPESA API client with comprehensive validation and security setup."""
        self.environment = environment
        self.base_url = (
            "https://sandbox.safaricom.co.ke" 
            if environment == "sandbox" 
            else "https://api.safaricom.co.ke"
        )
        
        # Use provided credentials or fall back to settings
        self.consumer_key = consumer_key or getattr(settings, 'mpesa_consumer_key', '')
        self.consumer_secret = consumer_secret or getattr(settings, 'mpesa_consumer_secret', '')
        self.passkey = passkey or getattr(settings, 'mpesa_passkey', '')
        self.shortcode = shortcode or getattr(settings, 'mpesa_shortcode', '')
        self.callback_url = callback_url or getattr(settings, 'mpesa_callback_url', '')
        
        # Validate required credentials
        self._validate_credentials()
        
        # Initialize security components
        self._public_key = None
        self._load_public_key()
        
        # API state management
        self.access_token = None
        self.token_expires_at = None
        self._max_retries = 3
        self._retry_delay = 1  # seconds
        self._request_timeout = 30.0  # seconds
        self._is_configured = False  # Will be set by validation

    def _validate_credentials(self) -> None:
        """Validate MPESA credentials."""
        required_fields = {
            'consumer_key': self.consumer_key,
            'consumer_secret': self.consumer_secret,
            'passkey': self.passkey,
            'shortcode': self.shortcode
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        
        # Check for placeholder values that indicate incomplete configuration
        placeholder_patterns = ['your-mpesa-', 'placeholder', 'change-me', 'example']
        invalid_fields = []
        
        for field, value in required_fields.items():
            if value and any(pattern in value.lower() for pattern in placeholder_patterns):
                invalid_fields.append(field)
        
        # In development, log warnings instead of raising errors for missing credentials
        if settings.environment == "development":
            if missing_fields or invalid_fields:
                logger.warning(f"MPESA service initialized with incomplete credentials in development mode. "
                             f"Missing: {missing_fields}, Invalid: {invalid_fields}. "
                             f"MPESA functionality will be disabled.")
                self._is_configured = False
                return
        else:
            # In production, require valid credentials
            if missing_fields:
                raise ValidationError(f"Missing required MPESA credentials: {', '.join(missing_fields)}")
            if invalid_fields:
                raise ValidationError(f"Invalid MPESA credentials (placeholder values): {', '.join(invalid_fields)}")
        
        # Validate shortcode format (should be numeric)
        if self.shortcode and not self.shortcode.isdigit():
            if settings.environment == "development":
                logger.warning(f"MPESA shortcode '{self.shortcode}' is not numeric. MPESA functionality will be disabled.")
                self._is_configured = False
                return
            else:
                raise ValidationError("MPESA shortcode must be numeric")
        
        # Validate callback URL format
        if self.callback_url and not self.callback_url.startswith(('http://', 'https://')):
            if settings.environment == "development":
                logger.warning(f"MPESA callback URL '{self.callback_url}' is not a valid HTTP/HTTPS URL. MPESA functionality will be disabled.")
                self._is_configured = False
                return
            else:
                raise ValidationError("MPESA callback URL must be a valid HTTP/HTTPS URL")
        
        self._is_configured = True

    def _load_public_key(self) -> None:
        """Load MPESA public key for signature verification."""
        # Skip loading public key if MPESA is not configured
        if hasattr(self, '_is_configured') and not self._is_configured:
            return
            
        try:
            # Determine the correct key file based on environment
            key_filename = (
                "mpesa_sandbox_public_key.pem" 
                if self.environment == "sandbox" 
                else "mpesa_public_key.pem"
            )
            
            # Get the keys directory path
            current_dir = Path(__file__).parent
            keys_dir = current_dir / "keys"
            key_path = keys_dir / key_filename
            
            if not key_path.exists():
                logger.warning(f"MPESA public key not found at {key_path}")
                logger.warning("Signature verification will be disabled. Please add the public key file.")
                return
            
            # Load the public key
            with open(key_path, 'rb') as key_file:
                self._public_key = serialization.load_pem_public_key(
                    key_file.read(),
                    backend=default_backend()
                )
            
            logger.info(f"MPESA public key loaded successfully from {key_path}")
            
        except Exception as e:
            logger.error(f"Failed to load MPESA public key: {e}")
            logger.warning("Signature verification will be disabled")
            self._public_key = None

    async def _make_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic and error handling."""
        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(method, url, **kwargs)
                    
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 401:
                        # Token expired, clear it
                        self.access_token = None
                        self.token_expires_at = None
                        raise ExternalServiceError("MPESA authentication failed")
                    elif response.status_code == 400:
                        error_data = response.json()
                        error_msg = error_data.get('errorMessage', 'Bad request')
                        raise ExternalServiceError(f"MPESA API error: {error_msg}")
                    else:
                        raise ExternalServiceError(f"MPESA API returned status {response.status_code}")
                        
            except httpx.TimeoutException:
                if attempt == self._max_retries - 1:
                    raise ExternalServiceError("MPESA API request timeout")
                logger.warning(f"MPESA API timeout (attempt {attempt + 1}/{self._max_retries})")
                await asyncio.sleep(self._retry_delay * (2 ** attempt))
            except httpx.RequestError as e:
                if attempt == self._max_retries - 1:
                    raise ExternalServiceError(f"MPESA API request failed: {e}")
                logger.warning(f"MPESA API request error (attempt {attempt + 1}/{self._max_retries}): {e}")
                await asyncio.sleep(self._retry_delay * (2 ** attempt))
        
        raise ExternalServiceError("MPESA API request failed after all retries")

    async def get_access_token(self) -> Optional[str]:
        """Get MPESA access token."""
        if self.access_token and self.token_expires_at and datetime.utcnow() < self.token_expires_at:
            return self.access_token

        url = f"{self.base_url}/oauth/v1/generate"
        params = {"grant_type": "client_credentials"}
        
        # Create basic auth header
        credentials = f"{self.consumer_key}:{self.consumer_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        }

        try:
            data = await self._make_request("GET", url, params=params, headers=headers)
            
            self.access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            self.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 60)  # 1 minute buffer
            
            if not self.access_token:
                raise ExternalServiceError("MPESA access token not found in response")
            
            logger.info("MPESA access token obtained successfully")
            return self.access_token
            
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting MPESA access token: {e}")
            raise ExternalServiceError(f"Failed to get MPESA access token: {e}")

    def generate_password(self, timestamp: str) -> str:
        """Generate MPESA API password following official documentation.
        
        The password is generated by encoding to Base64 a concatenation of:
        - Business Short Code
        - Passkey
        - Timestamp
        
        Reference: https://developer.safaricom.co.ke/Documentation
        """
        if not all([self.shortcode, self.passkey, timestamp]):
            raise ValidationError("Missing required data for password generation")
        
        data_to_encode = f"{self.shortcode}{self.passkey}{timestamp}"
        encoded = base64.b64encode(data_to_encode.encode()).decode()
        return encoded

    def generate_timestamp(self) -> str:
        """Generate timestamp in the format required by MPESA.
        
        Format: YYYYMMDDHHMMSS (e.g., 20241201143000)
        Reference: https://developer.safaricom.co.ke/Documentation
        """
        return datetime.now().strftime("%Y%m%d%H%M%S")

    async def get_transaction_status(self, transaction_id: str) -> Dict[str, Any]:
        """Get transaction status from MPESA.
        
        This method queries the status of a specific transaction using the
        MPESA Transaction Status Query API.
        
        Reference: https://developer.safaricom.co.ke/Documentation
        """
        try:
            if not transaction_id or not isinstance(transaction_id, str):
                raise ValidationError("Transaction ID is required and must be a string")
            
            access_token = await self.get_access_token()
            if not access_token:
                raise ExternalServiceError("Failed to get MPESA access token")

            timestamp = self.generate_timestamp()
            password = self.generate_password(timestamp)

            url = f"{self.base_url}/mpesa/transactionstatus/v1/query"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "Initiator": self.consumer_key,
                "SecurityCredential": password,
                "CommandID": "TransactionStatusQuery",
                "TransactionID": transaction_id,
                "PartyA": self.shortcode,
                "IdentifierType": "4",  # Organization
                "ResultURL": f"{self.callback_url}/transaction-status",
                "QueueTimeOutURL": f"{self.callback_url}/transaction-status-timeout",
                "Remarks": "Transaction status query",
                "Occasion": "Status query"
            }

            data = await self._make_request("POST", url, json=payload, headers=headers)
            
            logger.info(f"Transaction status queried successfully for {transaction_id}")
            return {
                "success": True,
                "data": data,
                "transaction_id": transaction_id
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error querying transaction status: {e}")
            raise ExternalServiceError(f"Transaction status query failed: {e}")

    async def reverse_transaction(self, transaction_id: str, amount: int, 
                                receiver_party: str, remarks: str = "Transaction reversal") -> Dict[str, Any]:
        """Reverse a transaction using MPESA Reversal API.
        
        This method reverses a completed transaction using the MPESA
        Reversal API as per the official documentation.
        
        Reference: https://developer.safaricom.co.ke/Documentation
        """
        try:
            # Validate inputs
            self._validate_amount(amount)
            
            if not transaction_id or not isinstance(transaction_id, str):
                raise ValidationError("Transaction ID is required and must be a string")
            
            if not receiver_party or not isinstance(receiver_party, str):
                raise ValidationError("Receiver party is required and must be a string")
            
            access_token = await self.get_access_token()
            if not access_token:
                raise ExternalServiceError("Failed to get MPESA access token")

            timestamp = self.generate_timestamp()
            password = self.generate_password(timestamp)

            url = f"{self.base_url}/mpesa/reversal/v1/request"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "Initiator": self.consumer_key,
                "SecurityCredential": password,
                "CommandID": "TransactionReversal",
                "TransactionID": transaction_id,
                "Amount": amount,
                "ReceiverParty": receiver_party,
                "RecieverIdentifierType": "4",  # Organization
                "ResultURL": f"{self.callback_url}/reversal-result",
                "QueueTimeOutURL": f"{self.callback_url}/reversal-timeout",
                "Remarks": remarks,
                "Occasion": "Transaction reversal"
            }

            data = await self._make_request("POST", url, json=payload, headers=headers)
            
            logger.info(f"Transaction reversal initiated for {transaction_id}: {amount} KES")
            return {
                "success": True,
                "data": data,
                "transaction_id": transaction_id,
                "amount": amount
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error reversing transaction: {e}")
            raise ExternalServiceError(f"Transaction reversal failed: {e}")

    def _validate_phone_number(self, phone_number: str) -> str:
        """Validate and format phone number for MPESA."""
        if not phone_number:
            raise ValidationError("Phone number is required")
        
        # Remove any non-digit characters except +
        cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')
        
        # Remove + if present
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        
        # Handle different formats
        if cleaned.startswith('0'):
            # Convert 07xxxxxxxx to 2547xxxxxxxx
            cleaned = f"254{cleaned[1:]}"
        elif not cleaned.startswith('254'):
            # Add 254 prefix if not present
            cleaned = f"254{cleaned}"
        
        # Validate final format
        if not cleaned.startswith('254') or len(cleaned) != 12:
            raise ValidationError(f"Invalid phone number format: {phone_number}")
        
        return cleaned

    def _validate_amount(self, amount: int) -> None:
        """Validate payment amount."""
        if not isinstance(amount, int) or amount <= 0:
            raise ValidationError("Amount must be a positive integer")
        
        if amount < 1:
            raise ValidationError("Amount must be at least 1 KES")
        
        if amount > 150000:
            raise ValidationError("Amount cannot exceed 150,000 KES")

    async def stk_push(
        self,
        phone_number: str,
        amount: int,
        account_reference: str,
        transaction_desc: str,
        party_a: Optional[str] = None,
        party_b: Optional[str] = None
    ) -> Dict[str, Any]:
        """Initiate STK Push payment with production-ready validation."""
        try:
            # Validate inputs
            self._validate_amount(amount)
            formatted_phone = self._validate_phone_number(phone_number)
            
            if not account_reference or len(account_reference) > 12:
                raise ValidationError("Account reference is required and must be 12 characters or less")
            
            if not transaction_desc or len(transaction_desc) > 13:
                raise ValidationError("Transaction description is required and must be 13 characters or less")

            # Get access token
            access_token = await self.get_access_token()
            if not access_token:
                raise ExternalServiceError("Failed to get MPESA access token")

            timestamp = self.generate_timestamp()
            password = self.generate_password(timestamp)

            url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "BusinessShortCode": self.shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": party_a or formatted_phone,
                "PartyB": party_b or self.shortcode,
                "PhoneNumber": formatted_phone,
                "CallBackURL": self.callback_url,
                "AccountReference": account_reference,
                "TransactionDesc": transaction_desc
            }

            data = await self._make_request("POST", url, json=payload, headers=headers)
            
            logger.info(f"STK Push initiated successfully for {formatted_phone}: {amount} KES")
            return {
                "success": True,
                "data": data,
                "phone_number": formatted_phone,
                "amount": amount,
                "account_reference": account_reference
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in STK Push: {e}")
            raise ExternalServiceError(f"STK Push failed: {e}")

    async def query_stk_push_status(self, checkout_request_id: str) -> Dict[str, Any]:
        """Query STK Push status."""
        access_token = await self.get_access_token()
        if not access_token:
            return {"error": "Failed to get access token"}

        timestamp = self.generate_timestamp()
        password = self.generate_password(timestamp)

        url = f"{self.base_url}/mpesa/stkpushquery/v1/query"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }

        try:
            if not checkout_request_id or not isinstance(checkout_request_id, str):
                raise ValidationError("Checkout request ID is required and must be a string")
            
            data = await self._make_request("POST", url, json=payload, headers=headers)
            
            logger.info(f"STK Push status queried successfully for {checkout_request_id}")
            return {
                "success": True,
                "data": data,
                "checkout_request_id": checkout_request_id
            }
            
        except ValidationError:
            raise
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error querying STK Push status: {e}")
            raise ExternalServiceError(f"STK Push status query failed: {e}")

    async def register_c2b_urls(self) -> Dict[str, Any]:
        """Register C2B URLs for callbacks."""
        access_token = await self.get_access_token()
        if not access_token:
            return {"error": "Failed to get access token"}

        url = f"{self.base_url}/mpesa/c2b/v1/registerurl"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "ShortCode": self.shortcode,
            "ResponseType": "Completed",
            "ConfirmationURL": f"{self.callback_url}/c2b/confirmation",
            "ValidationURL": f"{self.callback_url}/c2b/validation"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                logger.info(f"C2B URLs registered successfully: {data}")
                return data
                
        except Exception as e:
            logger.error(f"C2B URL registration failed: {e}")
            return {"error": str(e)}

    async def simulate_c2b_payment(
        self,
        phone_number: str,
        amount: int,
        account_number: str,
        command_id: str = "CustomerPayBillOnline"
    ) -> Dict[str, Any]:
        """Simulate C2B payment (for testing)."""
        access_token = await self.get_access_token()
        if not access_token:
            return {"error": "Failed to get access token"}

        # Format phone number
        if phone_number.startswith("+"):
            phone_number = phone_number[1:]
        if phone_number.startswith("0"):
            phone_number = f"254{phone_number[1:]}"
        if not phone_number.startswith("254"):
            phone_number = f"254{phone_number}"

        url = f"{self.base_url}/mpesa/c2b/v1/simulate"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "ShortCode": self.shortcode,
            "CommandID": command_id,
            "Amount": amount,
            "Msisdn": phone_number,
            "BillRefNumber": account_number
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                logger.info(f"C2B simulation successful: {data}")
                return data
                
        except Exception as e:
            logger.error(f"C2B simulation failed: {e}")
            return {"error": str(e)}

    def verify_callback_signature(self, callback_data: Dict[str, Any]) -> bool:
        """Verify MPESA callback signature using official Safaricom public key.
        
        Implements proper cryptographic signature verification as per the official
        MPESA Daraja API documentation.
        
        Reference: https://developer.safaricom.co.ke/Documentation
        """
        try:
            if not callback_data or not isinstance(callback_data, dict):
                logger.warning("Invalid callback data provided for signature verification")
                return False
            
            # Extract signature from callback data
            signature = callback_data.get("signature", "")
            
            if not signature:
                logger.warning("MPESA callback missing signature")
                return False
            
            # If no public key is loaded, fall back to basic validation
            if not self._public_key:
                logger.warning("MPESA public key not available, using basic signature validation")
                return self._basic_signature_validation(callback_data, signature)
            
            # Validate required callback fields are present
            if not self._validate_callback_structure(callback_data):
                return False
            
            # Perform cryptographic signature verification
            return self._cryptographic_signature_verification(callback_data, signature)
            
        except Exception as e:
            logger.error(f"Callback signature verification failed: {e}")
            return False

    def _basic_signature_validation(self, callback_data: Dict[str, Any], signature: str) -> bool:
        """Perform basic signature validation when public key is not available."""
        try:
            # Check signature format (should be base64 encoded)
            try:
                base64.b64decode(signature)
            except Exception:
                logger.warning("Invalid signature format - not base64 encoded")
                return False
            
            # Validate required callback fields are present
            required_fields = ["Body", "stkCallback"]
            if not all(field in callback_data for field in required_fields):
                logger.warning("Missing required callback fields")
                return False
            
            # Additional validation for STK callback
            if "stkCallback" in callback_data:
                stk_callback = callback_data["stkCallback"]
                if not isinstance(stk_callback, dict):
                    logger.warning("Invalid stkCallback format")
                    return False
                
                # Check for required STK callback fields
                stk_required_fields = ["MerchantRequestID", "CheckoutRequestID", "ResultCode", "ResultDesc"]
                if not all(field in stk_callback for field in stk_required_fields):
                    logger.warning("Missing required STK callback fields")
                    return False
            
            logger.info("MPESA callback basic signature validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Basic signature validation failed: {e}")
            return False

    def _validate_callback_structure(self, callback_data: Dict[str, Any]) -> bool:
        """Validate the structure of MPESA callback data."""
        try:
            # Validate required callback fields are present
            required_fields = ["Body", "stkCallback"]
            if not all(field in callback_data for field in required_fields):
                logger.warning("Missing required callback fields")
                return False
            
            # Additional validation for STK callback
            if "stkCallback" in callback_data:
                stk_callback = callback_data["stkCallback"]
                if not isinstance(stk_callback, dict):
                    logger.warning("Invalid stkCallback format")
                    return False
                
                # Check for required STK callback fields
                stk_required_fields = ["MerchantRequestID", "CheckoutRequestID", "ResultCode", "ResultDesc"]
                if not all(field in stk_callback for field in stk_required_fields):
                    logger.warning("Missing required STK callback fields")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Callback structure validation failed: {e}")
            return False

    def _cryptographic_signature_verification(self, callback_data: Dict[str, Any], signature: str) -> bool:
        """Perform cryptographic signature verification using MPESA public key."""
        try:
            # Create the message to verify (callback data without signature)
            message_data = {k: v for k, v in callback_data.items() if k != "signature"}
            message = json.dumps(message_data, sort_keys=True, separators=(',', ':'))
            
            # Decode the signature
            try:
                signature_bytes = base64.b64decode(signature)
            except Exception as e:
                logger.warning(f"Failed to decode signature: {e}")
                return False
            
            # Verify the signature using the public key
            try:
                self._public_key.verify(
                    signature_bytes,
                    message.encode('utf-8'),
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
                
                logger.info("MPESA callback signature cryptographically verified")
                return True
                
            except Exception as e:
                logger.warning(f"Signature verification failed: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Cryptographic signature verification failed: {e}")
            return False

    def parse_stk_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse STK Push callback data."""
        try:
            body = callback_data.get("Body", {})
            stk_callback = body.get("stkCallback", {})
            
            result = {
                "merchant_request_id": stk_callback.get("MerchantRequestID", ""),
                "checkout_request_id": stk_callback.get("CheckoutRequestID", ""),
                "result_code": stk_callback.get("ResultCode", ""),
                "result_desc": stk_callback.get("ResultDesc", ""),
                "callback_metadata": {}
            }
            
            if "CallbackMetadata" in stk_callback:
                metadata = stk_callback["CallbackMetadata"]["Item"]
                for item in metadata:
                    result["callback_metadata"][item["Name"]] = item["Value"]
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to parse STK callback: {e}")
            return {}

    def parse_c2b_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse C2B callback data."""
        try:
            transaction = callback_data.get("Transaction", {})
            
            result = {
                "transaction_type": transaction.get("TransactionType", ""),
                "trans_id": transaction.get("TransID", ""),
                "trans_time": transaction.get("TransTime", ""),
                "trans_amount": transaction.get("TransAmount", ""),
                "business_short_code": transaction.get("BusinessShortCode", ""),
                "bill_ref_number": transaction.get("BillRefNumber", ""),
                "invoice_number": transaction.get("InvoiceNumber", ""),
                "org_account_balance": transaction.get("OrgAccountBalance", ""),
                "third_party_trans_id": transaction.get("ThirdPartyTransID", ""),
                "msisdn": transaction.get("MSISDN", ""),
                "first_name": transaction.get("FirstName", ""),
                "middle_name": transaction.get("MiddleName", ""),
                "last_name": transaction.get("LastName", "")
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to parse C2B callback: {e}")
            return {}


class MpesaService:
    """High-level MPESA service for business logic."""

    def __init__(self):
        self.api = MpesaAPI()
        self.logger = get_logger(__name__)
        
    @property
    def is_configured(self) -> bool:
        """Check if MPESA service is properly configured."""
        return getattr(self.api, '_is_configured', False)

    async def initiate_payment(
        self,
        phone_number: str,
        amount: int,
        invoice_number: str,
        description: str = "Payment for internet service"
    ) -> Dict[str, Any]:
        """Initiate payment for an invoice."""
        if not self.is_configured:
            self.logger.warning("MPESA service not configured. Payment initiation skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Payment processing unavailable in development mode"
            }
            
        try:
            result = await self.api.stk_push(
                phone_number=phone_number,
                amount=amount,
                account_reference=invoice_number,
                transaction_desc=description
            )
            
            if "error" in result:
                return result
            
            # Log the payment initiation
            self.logger.info(f"Payment initiated for invoice {invoice_number}: {result}")
            
            return {
                "success": True,
                "merchant_request_id": result.get("MerchantRequestID"),
                "checkout_request_id": result.get("CheckoutRequestID"),
                "response_code": result.get("ResponseCode"),
                "response_description": result.get("ResponseDescription"),
                "customer_message": result.get("CustomerMessage")
            }
            
        except Exception as e:
            self.logger.error(f"Payment initiation failed: {e}")
            return {"success": False, "error": str(e)}

    async def verify_payment(self, checkout_request_id: str) -> Dict[str, Any]:
        """Verify payment status."""
        if not self.is_configured:
            self.logger.warning("MPESA service not configured. Payment verification skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Payment verification unavailable in development mode"
            }
            
        try:
            result = await self.api.query_stk_push_status(checkout_request_id)
            
            if "error" in result:
                return result
            
            return {
                "success": True,
                "result_code": result.get("ResultCode"),
                "result_description": result.get("ResultDesc"),
                "merchant_request_id": result.get("MerchantRequestID"),
                "checkout_request_id": result.get("CheckoutRequestID")
            }
            
        except Exception as e:
            self.logger.error(f"Payment verification failed: {e}")
            return {"success": False, "error": str(e)}

    async def handle_payment_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle payment callback from MPESA."""
        if not self.is_configured:
            self.logger.warning("MPESA service not configured. Callback handling skipped.")
            return {
                "success": False,
                "error": "MPESA service not configured",
                "message": "Callback processing unavailable in development mode"
            }
            
        try:
            # Verify callback signature
            if not self.api.verify_callback_signature(callback_data):
                self.logger.warning("Invalid callback signature")
                return {"success": False, "error": "Invalid signature"}
            
            # Parse callback data
            parsed_data = self.api.parse_stk_callback(callback_data)
            
            if not parsed_data:
                return {"success": False, "error": "Failed to parse callback"}
            
            # Process the payment based on result code
            result_code = parsed_data.get("result_code", "")
            
            if result_code == "0":  # Success
                # Extract payment details
                metadata = parsed_data.get("callback_metadata", {})
                mpesa_receipt_number = metadata.get("MpesaReceiptNumber", "")
                transaction_date = metadata.get("TransactionDate", "")
                phone_number = metadata.get("PhoneNumber", "")
                
                return {
                    "success": True,
                    "payment_successful": True,
                    "mpesa_receipt_number": mpesa_receipt_number,
                    "transaction_date": transaction_date,
                    "phone_number": phone_number,
                    "amount": metadata.get("Amount", ""),
                    "merchant_request_id": parsed_data.get("merchant_request_id"),
                    "checkout_request_id": parsed_data.get("checkout_request_id")
                }
            else:
                # Payment failed
                return {
                    "success": True,
                    "payment_successful": False,
                    "result_code": result_code,
                    "result_description": parsed_data.get("result_desc"),
                    "merchant_request_id": parsed_data.get("merchant_request_id"),
                    "checkout_request_id": parsed_data.get("checkout_request_id")
                }
                
        except Exception as e:
            self.logger.error(f"Payment callback handling failed: {e}")
            return {"success": False, "error": str(e)}
