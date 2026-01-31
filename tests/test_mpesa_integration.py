"""Tests for MPESA integration module.

This module contains comprehensive tests for the MPESA Daraja API integration
following the official Safaricom documentation.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import pytest
import asyncio
import base64
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from pathlib import Path

from app.integrations.payment_gateways.mpesa import (
    MPesaPaybillGateway,
    MPesaTillGateway,
    MPesaAPIError,
    MPesaValidationError,
)
from app.integrations.payment_gateways.base import PaymentStatus


def _create_gateway_config(environment: str = "sandbox") -> dict:
    """Create a test gateway configuration."""
    return {
        "credentials": {
            "consumer_key": "test_key",
            "consumer_secret": "test_secret",
            "passkey": "test_passkey",
            "shortcode": "123456",
            "environment": environment,
            "initiator_name": "test_initiator",
            "security_credential": "test_credential",
        },
        "callback_url": "https://example.com/callback",
        "timeout_url": "https://example.com/timeout",
        "result_url": "https://example.com/result",
    }


class TestMPesaPaybillGateway:
    """Test cases for MPesaPaybillGateway class."""

    def test_init_with_valid_config(self):
        """Test gateway initialization with valid configuration."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        assert gateway.gateway_name == "M-PESA Paybill"
        assert gateway._shortcode == "123456"
        assert gateway._base_url == "https://sandbox.safaricom.co.ke"

    def test_init_production_environment(self):
        """Test gateway initialization for production environment."""
        config = _create_gateway_config(environment="production")
        gateway = MPesaPaybillGateway(config)

        assert gateway._base_url == "https://api.safaricom.co.ke"

    def test_supports_properties(self):
        """Test gateway support properties."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        assert gateway.supports_stk_push is True
        assert gateway.supports_c2b is True
        assert gateway.supports_b2c is True
        assert gateway.supports_refunds is True

    def test_generate_password(self):
        """Test password generation."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        timestamp = "20241201143000"
        password = gateway._generate_password(timestamp)

        assert isinstance(password, str)
        # Should be base64 encoded
        decoded = base64.b64decode(password).decode()
        assert decoded == f"123456test_passkey{timestamp}"

    def test_format_phone_number_valid_formats(self):
        """Test phone number formatting with valid formats."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        # Test various valid formats
        valid_numbers = [
            ("254712345678", "254712345678"),
            ("0712345678", "254712345678"),
            ("+254712345678", "254712345678"),
            ("712345678", "254712345678"),
        ]

        for input_num, expected in valid_numbers:
            formatted = gateway.format_phone_number(input_num)
            assert formatted == expected

    def test_validate_phone_number_valid(self):
        """Test phone number validation with valid formats."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        valid_numbers = [
            "254712345678",
            "0712345678",
            "+254712345678",
        ]

        for number in valid_numbers:
            formatted = gateway.validate_phone_number(number)
            assert formatted == "254712345678"

    def test_validate_phone_number_invalid(self):
        """Test phone number validation with invalid formats."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        invalid_numbers = [
            "",
            "123",
            "2547123456789",  # Too long
            "25471234567",  # Too short
        ]

        for number in invalid_numbers:
            with pytest.raises(MPesaValidationError):
                gateway.validate_phone_number(number)

    def test_validate_amount_valid(self):
        """Test amount validation with valid amounts."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        valid_amounts = [1, 100, 1000, 150000]

        for amount in valid_amounts:
            gateway.validate_amount(amount)  # Should not raise

    def test_validate_amount_invalid(self):
        """Test amount validation with invalid amounts."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        invalid_amounts = [0, -1, 150001]

        for amount in invalid_amounts:
            with pytest.raises(MPesaValidationError):
                gateway.validate_amount(amount)

    @pytest.mark.asyncio
    async def test_initiate_payment_success(self):
        """Test successful STK Push initiation."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "MerchantRequestID": "test_merchant_id",
            "CheckoutRequestID": "test_checkout_id",
            "ResponseCode": "0",
            "ResponseDescription": "Success",
        }

        with patch.object(gateway, "_get_access_token", return_value="test_token"), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

            result = await gateway.initiate_payment(
                amount=Decimal("1000"),
                phone_number="254712345678",
                reference="ISP123456",
                description="Test Payment",
            )

            assert result.success is True
            assert result.transaction_reference == "ISP123456"
            assert result.gateway_reference == "test_checkout_id"
            assert result.status == PaymentStatus.PENDING

    @pytest.mark.asyncio
    async def test_verify_payment_success(self):
        """Test successful payment verification."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ResponseCode": "0",
            "ResponseDescription": "Success",
            "MerchantRequestID": "test_merchant_id",
            "CheckoutRequestID": "test_checkout_id",
            "ResultCode": "0",
            "ResultDesc": "The service request is processed successfully",
        }

        with patch.object(gateway, "_get_access_token", return_value="test_token"), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

            result = await gateway.verify_payment("test_checkout_id")

            assert result.success is True
            assert result.status == PaymentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_verify_payment_cancelled(self):
        """Test payment verification for cancelled payment."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ResponseCode": "0",
            "ResultCode": "1032",
            "ResultDesc": "Request cancelled by user",
        }

        with patch.object(gateway, "_get_access_token", return_value="test_token"), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

            result = await gateway.verify_payment("test_checkout_id")

            assert result.success is False
            assert result.status == PaymentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_process_callback_success(self):
        """Test successful callback processing."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        callback_data = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "test_checkout_id",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 1000},
                            {"Name": "MpesaReceiptNumber", "Value": "test_receipt"},
                            {"Name": "PhoneNumber", "Value": "254712345678"},
                            {"Name": "TransactionDate", "Value": "20241201143000"},
                        ]
                    }
                }
            }
        }

        result = await gateway.process_callback(callback_data)

        assert result.success is True
        assert result.status == PaymentStatus.COMPLETED
        assert result.gateway_reference == "test_receipt"
        assert result.amount == Decimal("1000")

    @pytest.mark.asyncio
    async def test_process_callback_failed(self):
        """Test callback processing for failed payment."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        callback_data = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "test_checkout_id",
                    "ResultCode": 1,
                    "ResultDesc": "Insufficient balance",
                }
            }
        }

        result = await gateway.process_callback(callback_data)

        assert result.success is False
        assert result.status == PaymentStatus.FAILED

    def test_parse_stk_callback_success(self):
        """Test successful STK callback parsing."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

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

        result = gateway.parse_stk_callback(callback_data)

        assert result["merchant_request_id"] == "test_merchant_id"
        assert result["checkout_request_id"] == "test_checkout_id"
        assert result["result_code"] == 0
        assert result["callback_metadata"]["Amount"] == "1000"

    def test_parse_stk_callback_empty(self):
        """Test STK callback parsing with empty data."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        result = gateway.parse_stk_callback({})
        assert result == {}

    def test_parse_c2b_callback(self):
        """Test C2B callback parsing."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        callback_data = {
            "TransactionType": "PayBill",
            "TransID": "test_trans_id",
            "TransTime": "20241201143000",
            "TransAmount": "1000",
            "BusinessShortCode": "123456",
            "BillRefNumber": "ISP123",
            "MSISDN": "254712345678",
            "FirstName": "John",
            "LastName": "Doe",
        }

        result = gateway.parse_c2b_callback(callback_data)

        assert result["trans_id"] == "test_trans_id"
        assert result["trans_amount"] == "1000"
        assert result["msisdn"] == "254712345678"

    def test_validate_callback_structure_valid(self):
        """Test callback structure validation with valid data."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        callback_data = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_id",
                    "CheckoutRequestID": "test_checkout",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                }
            }
        }

        result = gateway._validate_callback_structure(callback_data)
        assert result is True

    def test_validate_callback_structure_invalid(self):
        """Test callback structure validation with invalid data."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        invalid_data = [
            {},
            {"Body": {}},
            {"Body": {"stkCallback": {}}},
            {"Body": {"stkCallback": {"MerchantRequestID": "test"}}},
        ]

        for data in invalid_data:
            result = gateway._validate_callback_structure(data)
            assert result is False

    def test_verify_callback_signature_missing_signature(self):
        """Test callback signature verification with missing signature."""
        config = _create_gateway_config()
        gateway = MPesaPaybillGateway(config)

        callback_data = {"Body": {"stkCallback": {}}}
        result = gateway.verify_callback_signature(callback_data)
        assert result is False


class TestMPesaTillGateway:
    """Test cases for MPesaTillGateway class."""

    def test_init_with_valid_config(self):
        """Test Till gateway initialization."""
        config = {
            "credentials": {
                "consumer_key": "test_key",
                "consumer_secret": "test_secret",
                "passkey": "test_passkey",
                "till_number": "654321",
                "environment": "sandbox",
            },
            "callback_url": "https://example.com/callback",
        }
        gateway = MPesaTillGateway(config)

        assert gateway.gateway_name == "M-PESA Till"
        assert gateway._shortcode == "654321"

    def test_supports_properties(self):
        """Test Till gateway support properties."""
        config = {
            "credentials": {
                "consumer_key": "test_key",
                "consumer_secret": "test_secret",
                "passkey": "test_passkey",
                "till_number": "654321",
                "environment": "sandbox",
            },
            "callback_url": "https://example.com/callback",
        }
        gateway = MPesaTillGateway(config)

        assert gateway.supports_stk_push is True
        assert gateway.supports_c2b is True
        assert gateway.supports_b2c is False  # Different from Paybill
        assert gateway.supports_refunds is False  # Different from Paybill

    @pytest.mark.asyncio
    async def test_initiate_payment_uses_buy_goods_type(self):
        """Test that Till gateway uses CustomerBuyGoodsOnline transaction type."""
        config = {
            "credentials": {
                "consumer_key": "test_key",
                "consumer_secret": "test_secret",
                "passkey": "test_passkey",
                "till_number": "654321",
                "environment": "sandbox",
            },
            "callback_url": "https://example.com/callback",
        }
        gateway = MPesaTillGateway(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "MerchantRequestID": "test_merchant_id",
            "CheckoutRequestID": "test_checkout_id",
            "ResponseCode": "0",
            "ResponseDescription": "Success",
        }

        with patch.object(gateway, "_get_access_token", return_value="test_token"), \
             patch("httpx.AsyncClient") as mock_client:
            mock_post = mock_client.return_value.__aenter__.return_value.post
            mock_post.return_value = mock_response

            await gateway.initiate_payment(
                amount=Decimal("1000"),
                phone_number="254712345678",
                reference="TILL123",
                description="Test Till Payment",
            )

            # Verify the payload uses CustomerBuyGoodsOnline
            call_args = mock_post.call_args
            payload = call_args.kwargs.get("json", call_args[1].get("json"))
            assert payload["TransactionType"] == "CustomerBuyGoodsOnline"
