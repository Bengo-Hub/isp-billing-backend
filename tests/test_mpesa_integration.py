"""Tests for MPESA integration module.

This module contains comprehensive tests for the MPESA Daraja API integration
following the official Safaricom documentation.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from pathlib import Path

from app.integrations.mpesa import MpesaAPI
from app.core.exceptions import ValidationError, ExternalServiceError


class TestMpesaAPI:
    """Test cases for MpesaAPI class."""

    def test_init_with_valid_credentials(self):
        """Test MpesaAPI initialization with valid credentials."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456",
            callback_url="https://example.com/callback",
            environment="sandbox"
        )
        
        assert api.consumer_key == "test_key"
        assert api.consumer_secret == "test_secret"
        assert api.passkey == "test_passkey"
        assert api.shortcode == "123456"
        assert api.callback_url == "https://example.com/callback"
        assert api.environment == "sandbox"
        assert api.base_url == "https://sandbox.safaricom.co.ke"

    def test_init_with_invalid_credentials(self):
        """Test MpesaAPI initialization with invalid credentials."""
        with pytest.raises(ValidationError, match="Missing required MPESA credentials"):
            MpesaAPI(
                consumer_key="",
                consumer_secret="test_secret",
                passkey="test_passkey",
                shortcode="123456"
            )

    def test_init_with_invalid_shortcode(self):
        """Test MpesaAPI initialization with non-numeric shortcode."""
        with pytest.raises(ValidationError, match="MPESA shortcode must be numeric"):
            MpesaAPI(
                consumer_key="test_key",
                consumer_secret="test_secret",
                passkey="test_passkey",
                shortcode="abc123"
            )

    def test_init_with_invalid_callback_url(self):
        """Test MpesaAPI initialization with invalid callback URL."""
        with pytest.raises(ValidationError, match="MPESA callback URL must be a valid HTTP/HTTPS URL"):
            MpesaAPI(
                consumer_key="test_key",
                consumer_secret="test_secret",
                passkey="test_passkey",
                shortcode="123456",
                callback_url="invalid_url"
            )

    def test_production_environment(self):
        """Test MpesaAPI initialization for production environment."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456",
            environment="production"
        )
        
        assert api.environment == "production"
        assert api.base_url == "https://api.safaricom.co.ke"

    def test_generate_timestamp(self):
        """Test timestamp generation."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        timestamp = api.generate_timestamp()
        assert isinstance(timestamp, str)
        assert len(timestamp) == 14  # YYYYMMDDHHMMSS
        assert timestamp.isdigit()

    def test_generate_password(self):
        """Test password generation."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        timestamp = "20241201143000"
        password = api.generate_password(timestamp)
        
        assert isinstance(password, str)
        # Should be base64 encoded
        import base64
        decoded = base64.b64decode(password).decode()
        assert decoded == f"{api.shortcode}{api.passkey}{timestamp}"

    def test_generate_password_missing_data(self):
        """Test password generation with missing data."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        with pytest.raises(ValidationError, match="Missing required data for password generation"):
            api.generate_password("")

    def test_validate_phone_number_valid_formats(self):
        """Test phone number validation with valid formats."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        # Test various valid formats
        valid_numbers = [
            "254712345678",
            "0712345678",
            "+254712345678",
            "254712345678"
        ]
        
        for number in valid_numbers:
            formatted = api._validate_phone_number(number)
            assert formatted == "254712345678"

    def test_validate_phone_number_invalid_formats(self):
        """Test phone number validation with invalid formats."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        invalid_numbers = [
            "",
            "123",
            "abc123",
            "2547123456789",  # Too long
            "25471234567"     # Too short
        ]
        
        for number in invalid_numbers:
            with pytest.raises(ValidationError):
                api._validate_phone_number(number)

    def test_validate_amount_valid(self):
        """Test amount validation with valid amounts."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        valid_amounts = [1, 100, 1000, 150000]
        
        for amount in valid_amounts:
            api._validate_amount(amount)  # Should not raise

    def test_validate_amount_invalid(self):
        """Test amount validation with invalid amounts."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        invalid_amounts = [0, -1, 150001, "100", None]
        
        for amount in invalid_amounts:
            with pytest.raises(ValidationError):
                api._validate_amount(amount)

    @pytest.mark.asyncio
    async def test_get_access_token_success(self):
        """Test successful access token retrieval."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        mock_response = {
            "access_token": "test_token",
            "expires_in": 3600
        }
        
        with patch.object(api, '_make_request', return_value=mock_response):
            token = await api.get_access_token()
            
            assert token == "test_token"
            assert api.access_token == "test_token"
            assert api.token_expires_at is not None

    @pytest.mark.asyncio
    async def test_get_access_token_failure(self):
        """Test access token retrieval failure."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        with patch.object(api, '_make_request', side_effect=ExternalServiceError("API Error")):
            with pytest.raises(ExternalServiceError):
                await api.get_access_token()

    @pytest.mark.asyncio
    async def test_stk_push_success(self):
        """Test successful STK Push initiation."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456",
            callback_url="https://example.com/callback"
        )
        
        mock_response = {
            "MerchantRequestID": "test_merchant_id",
            "CheckoutRequestID": "test_checkout_id",
            "ResponseCode": "0",
            "ResponseDescription": "Success"
        }
        
        with patch.object(api, 'get_access_token', return_value="test_token"), \
             patch.object(api, '_make_request', return_value=mock_response):
            
            result = await api.stk_push(
                phone_number="254712345678",
                amount=1000,
                account_reference="ISP123456",
                transaction_desc="Test Payment"
            )
            
            assert result["success"] is True
            assert result["amount"] == 1000
            assert result["phone_number"] == "254712345678"

    @pytest.mark.asyncio
    async def test_stk_push_validation_error(self):
        """Test STK Push with validation error."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        with pytest.raises(ValidationError):
            await api.stk_push(
                phone_number="invalid_phone",
                amount=1000,
                account_reference="ISP123456",
                transaction_desc="Test Payment"
            )

    @pytest.mark.asyncio
    async def test_query_stk_push_status_success(self):
        """Test successful STK Push status query."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        mock_response = {
            "ResponseCode": "0",
            "ResponseDescription": "The service request is processed successfully",
            "MerchantRequestID": "test_merchant_id",
            "CheckoutRequestID": "test_checkout_id",
            "ResultCode": "0",
            "ResultDesc": "The service request is processed successfully"
        }
        
        with patch.object(api, 'get_access_token', return_value="test_token"), \
             patch.object(api, '_make_request', return_value=mock_response):
            
            result = await api.query_stk_push_status("test_checkout_id")
            
            assert result["success"] is True
            assert result["checkout_request_id"] == "test_checkout_id"

    def test_verify_callback_signature_no_public_key(self):
        """Test callback signature verification without public key."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        # Mock no public key loaded
        api._public_key = None
        
        callback_data = {
            "signature": "test_signature",
            "Body": {"stkCallback": {
                "MerchantRequestID": "test_id",
                "CheckoutRequestID": "test_checkout",
                "ResultCode": 0,
                "ResultDesc": "Success"
            }}
        }
        
        with patch.object(api, '_basic_signature_validation', return_value=True):
            result = api.verify_callback_signature(callback_data)
            assert result is True

    def test_verify_callback_signature_invalid_data(self):
        """Test callback signature verification with invalid data."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        # Test with invalid callback data
        invalid_data = [
            None,
            {},
            {"signature": ""},
            {"Body": {}},
            {"Body": {"stkCallback": {}}}
        ]
        
        for data in invalid_data:
            result = api.verify_callback_signature(data)
            assert result is False

    def test_parse_stk_callback_success(self):
        """Test successful STK callback parsing."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        callback_data = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "test_checkout_id",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": "1000"},
                            {"Name": "MpesaReceiptNumber", "Value": "test_receipt"}
                        ]
                    }
                }
            }
        }
        
        result = api.parse_stk_callback(callback_data)
        
        assert result["success"] is True
        assert result["merchant_request_id"] == "test_merchant_id"
        assert result["checkout_request_id"] == "test_checkout_id"
        assert result["result_code"] == 0
        assert result["callback_metadata"]["Amount"] == "1000"

    def test_parse_stk_callback_invalid_data(self):
        """Test STK callback parsing with invalid data."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        invalid_data = [
            None,
            {},
            {"Body": {}},
            {"Body": {"stkCallback": {}}}
        ]
        
        for data in invalid_data:
            result = api.parse_stk_callback(data)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_transaction_status_success(self):
        """Test successful transaction status query."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456",
            callback_url="https://example.com/callback"
        )
        
        mock_response = {
            "ResponseCode": "0",
            "ResponseDescription": "Success",
            "ResultCode": "0",
            "ResultDesc": "The service request is processed successfully"
        }
        
        with patch.object(api, 'get_access_token', return_value="test_token"), \
             patch.object(api, '_make_request', return_value=mock_response):
            
            result = await api.get_transaction_status("test_transaction_id")
            
            assert result["success"] is True
            assert result["transaction_id"] == "test_transaction_id"

    @pytest.mark.asyncio
    async def test_reverse_transaction_success(self):
        """Test successful transaction reversal."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456",
            callback_url="https://example.com/callback"
        )
        
        mock_response = {
            "ResponseCode": "0",
            "ResponseDescription": "Success",
            "OriginatorConversationID": "test_originator_id",
            "ConversationID": "test_conversation_id"
        }
        
        with patch.object(api, 'get_access_token', return_value="test_token"), \
             patch.object(api, '_make_request', return_value=mock_response):
            
            result = await api.reverse_transaction(
                transaction_id="test_transaction_id",
                amount=1000,
                receiver_party="254712345678"
            )
            
            assert result["success"] is True
            assert result["transaction_id"] == "test_transaction_id"
            assert result["amount"] == 1000

    def test_load_public_key_success(self):
        """Test successful public key loading."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        # Mock public key file
        mock_key_path = Path("test_key.pem")
        mock_key_content = b"-----BEGIN PUBLIC KEY-----\nMOCK_KEY\n-----END PUBLIC KEY-----"
        
        with patch.object(Path, 'exists', return_value=True), \
             patch('builtins.open', create=True) as mock_open, \
             patch('app.integrations.mpesa.serialization.load_pem_public_key') as mock_load:
            
            mock_open.return_value.__enter__.return_value.read.return_value = mock_key_content
            mock_load.return_value = "mock_public_key"
            
            api._load_public_key()
            
            assert api._public_key == "mock_public_key"

    def test_load_public_key_file_not_found(self):
        """Test public key loading when file not found."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        with patch.object(Path, 'exists', return_value=False):
            api._load_public_key()
            
            assert api._public_key is None

    def test_load_public_key_invalid_format(self):
        """Test public key loading with invalid format."""
        api = MpesaAPI(
            consumer_key="test_key",
            consumer_secret="test_secret",
            passkey="test_passkey",
            shortcode="123456"
        )
        
        mock_key_path = Path("test_key.pem")
        
        with patch.object(Path, 'exists', return_value=True), \
             patch('builtins.open', create=True) as mock_open, \
             patch('app.integrations.mpesa.serialization.load_pem_public_key', 
                   side_effect=Exception("Invalid key format")):
            
            mock_open.return_value.__enter__.return_value.read.return_value = b"invalid_key"
            
            api._load_public_key()
            
            assert api._public_key is None
