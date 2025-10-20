"""Tests for MPESA Pydantic schemas.

This module contains comprehensive tests for the MPESA data models
and validation schemas.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import pytest
from pydantic import ValidationError

from app.schemas.mpesa import (
    MpesaPaymentRequest,
    MpesaPaymentResponse,
    MpesaStatusResponse,
    MpesaCallbackResponse,
    MpesaReversalRequest,
    MpesaReversalResponse,
    MpesaStatisticsResponse,
    MpesaTransactionStatusRequest,
    MpesaTransactionStatusResponse,
    MpesaErrorResponse,
    MpesaCallbackData,
    MpesaStkCallbackData,
    MpesaCallbackMetadata,
    MpesaMetadataItem
)


class TestMpesaPaymentRequest:
    """Test cases for MpesaPaymentRequest schema."""

    def test_valid_payment_request(self):
        """Test valid payment request."""
        data = {
            "amount": 1000,
            "account_reference": "ISP123456",
            "description": "Test Payment"
        }
        
        request = MpesaPaymentRequest(**data)
        
        assert request.amount == 1000
        assert request.account_reference == "ISP123456"
        assert request.description == "Test Payment"

    def test_payment_request_minimal(self):
        """Test payment request with minimal data."""
        data = {"amount": 1000}
        
        request = MpesaPaymentRequest(**data)
        
        assert request.amount == 1000
        assert request.account_reference is None
        assert request.description is None

    def test_payment_request_amount_validation(self):
        """Test amount validation."""
        # Valid amounts
        valid_amounts = [1, 100, 1000, 150000]
        for amount in valid_amounts:
            request = MpesaPaymentRequest(amount=amount)
            assert request.amount == amount

        # Invalid amounts
        invalid_amounts = [0, -1, 150001]
        for amount in invalid_amounts:
            with pytest.raises(ValidationError):
                MpesaPaymentRequest(amount=amount)

    def test_payment_request_account_reference_validation(self):
        """Test account reference validation."""
        # Valid account references
        valid_refs = ["ISP123456", "123456789012", "A1B2C3D4E5F6"]
        for ref in valid_refs:
            request = MpesaPaymentRequest(amount=1000, account_reference=ref)
            assert request.account_reference == ref

        # Invalid account references (too long)
        with pytest.raises(ValidationError):
            MpesaPaymentRequest(amount=1000, account_reference="1234567890123")

    def test_payment_request_description_validation(self):
        """Test description validation."""
        # Valid descriptions
        valid_descs = ["Test", "Internet Bill", "1234567890123"]
        for desc in valid_descs:
            request = MpesaPaymentRequest(amount=1000, description=desc)
            assert request.description == desc

        # Invalid descriptions (too long)
        with pytest.raises(ValidationError):
            MpesaPaymentRequest(amount=1000, description="12345678901234")


class TestMpesaPaymentResponse:
    """Test cases for MpesaPaymentResponse schema."""

    def test_valid_payment_response(self):
        """Test valid payment response."""
        data = {
            "success": True,
            "payment_id": 1,
            "checkout_request_id": "ws_CO_123456789",
            "amount": 1000,
            "phone_number": "254712345678",
            "message": "Payment request sent to your phone"
        }
        
        response = MpesaPaymentResponse(**data)
        
        assert response.success is True
        assert response.payment_id == 1
        assert response.checkout_request_id == "ws_CO_123456789"
        assert response.amount == 1000
        assert response.phone_number == "254712345678"
        assert response.message == "Payment request sent to your phone"

    def test_payment_response_failure(self):
        """Test payment response for failure."""
        data = {
            "success": False,
            "payment_id": 0,
            "checkout_request_id": "",
            "amount": 0,
            "phone_number": "",
            "message": "Payment failed"
        }
        
        response = MpesaPaymentResponse(**data)
        
        assert response.success is False
        assert response.payment_id == 0
        assert response.message == "Payment failed"


class TestMpesaStatusResponse:
    """Test cases for MpesaStatusResponse schema."""

    def test_valid_status_response(self):
        """Test valid status response."""
        data = {
            "success": True,
            "payment_id": 1,
            "status": "completed",
            "amount": 1000,
            "mpesa_response": {
                "ResultCode": 0,
                "ResultDesc": "Success"
            }
        }
        
        response = MpesaStatusResponse(**data)
        
        assert response.success is True
        assert response.payment_id == 1
        assert response.status == "completed"
        assert response.amount == 1000
        assert response.mpesa_response["ResultCode"] == 0


class TestMpesaCallbackResponse:
    """Test cases for MpesaCallbackResponse schema."""

    def test_valid_callback_response(self):
        """Test valid callback response."""
        data = {
            "success": True,
            "payment_id": 1,
            "status": "completed",
            "result_code": 0
        }
        
        response = MpesaCallbackResponse(**data)
        
        assert response.success is True
        assert response.payment_id == 1
        assert response.status == "completed"
        assert response.result_code == 0

    def test_callback_response_failure(self):
        """Test callback response for failure."""
        data = {
            "success": False,
            "payment_id": 1,
            "status": "failed",
            "result_code": 1
        }
        
        response = MpesaCallbackResponse(**data)
        
        assert response.success is False
        assert response.status == "failed"
        assert response.result_code == 1


class TestMpesaReversalRequest:
    """Test cases for MpesaReversalRequest schema."""

    def test_valid_reversal_request(self):
        """Test valid reversal request."""
        data = {
            "payment_id": 1,
            "reason": "Customer requested refund"
        }
        
        request = MpesaReversalRequest(**data)
        
        assert request.payment_id == 1
        assert request.reason == "Customer requested refund"

    def test_reversal_request_default_reason(self):
        """Test reversal request with default reason."""
        data = {"payment_id": 1}
        
        request = MpesaReversalRequest(**data)
        
        assert request.payment_id == 1
        assert request.reason == "Payment reversal"

    def test_reversal_request_validation(self):
        """Test reversal request validation."""
        # Valid payment IDs
        valid_ids = [1, 100, 1000]
        for payment_id in valid_ids:
            request = MpesaReversalRequest(payment_id=payment_id)
            assert request.payment_id == payment_id

        # Invalid payment IDs
        invalid_ids = [0, -1]
        for payment_id in invalid_ids:
            with pytest.raises(ValidationError):
                MpesaReversalRequest(payment_id=payment_id)

    def test_reversal_request_reason_length(self):
        """Test reversal request reason length validation."""
        # Valid reason length
        valid_reason = "A" * 100
        request = MpesaReversalRequest(payment_id=1, reason=valid_reason)
        assert request.reason == valid_reason

        # Invalid reason length (too long)
        with pytest.raises(ValidationError):
            MpesaReversalRequest(payment_id=1, reason="A" * 101)


class TestMpesaReversalResponse:
    """Test cases for MpesaReversalResponse schema."""

    def test_valid_reversal_response(self):
        """Test valid reversal response."""
        data = {
            "success": True,
            "payment_id": 1,
            "reversal_data": {
                "ResponseCode": "0",
                "ResponseDescription": "Success"
            }
        }
        
        response = MpesaReversalResponse(**data)
        
        assert response.success is True
        assert response.payment_id == 1
        assert response.reversal_data["ResponseCode"] == "0"


class TestMpesaStatisticsResponse:
    """Test cases for MpesaStatisticsResponse schema."""

    def test_valid_statistics_response(self):
        """Test valid statistics response."""
        data = {
            "success": True,
            "statistics": {
                "total_payments": 100,
                "completed_payments": 95,
                "pending_payments": 3,
                "failed_payments": 2,
                "total_amount": 50000,
                "success_rate": 95.0
            }
        }
        
        response = MpesaStatisticsResponse(**data)
        
        assert response.success is True
        assert response.statistics["total_payments"] == 100
        assert response.statistics["success_rate"] == 95.0


class TestMpesaTransactionStatusRequest:
    """Test cases for MpesaTransactionStatusRequest schema."""

    def test_valid_transaction_status_request(self):
        """Test valid transaction status request."""
        data = {"transaction_id": "test_transaction_id"}
        
        request = MpesaTransactionStatusRequest(**data)
        
        assert request.transaction_id == "test_transaction_id"

    def test_transaction_status_request_validation(self):
        """Test transaction status request validation."""
        # Valid transaction IDs
        valid_ids = ["test_id", "123456789", "ws_CO_123456789"]
        for transaction_id in valid_ids:
            request = MpesaTransactionStatusRequest(transaction_id=transaction_id)
            assert request.transaction_id == transaction_id

        # Invalid transaction IDs
        invalid_ids = ["", None]
        for transaction_id in invalid_ids:
            with pytest.raises(ValidationError):
                MpesaTransactionStatusRequest(transaction_id=transaction_id)


class TestMpesaTransactionStatusResponse:
    """Test cases for MpesaTransactionStatusResponse schema."""

    def test_valid_transaction_status_response(self):
        """Test valid transaction status response."""
        data = {
            "success": True,
            "transaction_id": "test_transaction_id",
            "status_data": {
                "ResponseCode": "0",
                "ResponseDescription": "Success"
            }
        }
        
        response = MpesaTransactionStatusResponse(**data)
        
        assert response.success is True
        assert response.transaction_id == "test_transaction_id"
        assert response.status_data["ResponseCode"] == "0"


class TestMpesaErrorResponse:
    """Test cases for MpesaErrorResponse schema."""

    def test_valid_error_response(self):
        """Test valid error response."""
        data = {
            "success": False,
            "error": "Payment failed",
            "error_code": "PAYMENT_ERROR",
            "details": {"code": 1001, "message": "Insufficient funds"}
        }
        
        response = MpesaErrorResponse(**data)
        
        assert response.success is False
        assert response.error == "Payment failed"
        assert response.error_code == "PAYMENT_ERROR"
        assert response.details["code"] == 1001

    def test_error_response_minimal(self):
        """Test error response with minimal data."""
        data = {"error": "Unknown error"}
        
        response = MpesaErrorResponse(**data)
        
        assert response.success is False
        assert response.error == "Unknown error"
        assert response.error_code is None
        assert response.details is None


class TestMpesaCallbackData:
    """Test cases for MpesaCallbackData schema."""

    def test_valid_callback_data(self):
        """Test valid callback data."""
        data = {
            "signature": "test_signature",
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "test_checkout_id",
                    "ResultCode": 0,
                    "ResultDesc": "Success"
                }
            }
        }
        
        callback = MpesaCallbackData(**data)
        
        assert callback.signature == "test_signature"
        assert callback.Body["stkCallback"]["MerchantRequestID"] == "test_merchant_id"
        assert callback.stkCallback["CheckoutRequestID"] == "test_checkout_id"

    def test_callback_data_extra_fields(self):
        """Test callback data with extra fields."""
        data = {
            "signature": "test_signature",
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "test_checkout_id",
                    "ResultCode": 0,
                    "ResultDesc": "Success"
                }
            },
            "extra_field": "extra_value"
        }
        
        callback = MpesaCallbackData(**data)
        
        assert callback.signature == "test_signature"
        assert hasattr(callback, "extra_field")
        assert callback.extra_field == "extra_value"


class TestMpesaStkCallbackData:
    """Test cases for MpesaStkCallbackData schema."""

    def test_valid_stk_callback_data(self):
        """Test valid STK callback data."""
        data = {
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
        
        callback = MpesaStkCallbackData(**data)
        
        assert callback.MerchantRequestID == "test_merchant_id"
        assert callback.CheckoutRequestID == "test_checkout_id"
        assert callback.ResultCode == 0
        assert callback.ResultDesc == "Success"
        assert callback.CallbackMetadata["Item"][0]["Name"] == "Amount"

    def test_stk_callback_data_minimal(self):
        """Test STK callback data with minimal required fields."""
        data = {
            "MerchantRequestID": "test_merchant_id",
            "CheckoutRequestID": "test_checkout_id",
            "ResultCode": 0,
            "ResultDesc": "Success"
        }
        
        callback = MpesaStkCallbackData(**data)
        
        assert callback.MerchantRequestID == "test_merchant_id"
        assert callback.CallbackMetadata is None


class TestMpesaCallbackMetadata:
    """Test cases for MpesaCallbackMetadata schema."""

    def test_valid_callback_metadata(self):
        """Test valid callback metadata."""
        data = {
            "Item": [
                {"Name": "Amount", "Value": "1000"},
                {"Name": "MpesaReceiptNumber", "Value": "test_receipt"},
                {"Name": "TransactionDate", "Value": "20241201"}
            ]
        }
        
        metadata = MpesaCallbackMetadata(**data)
        
        assert len(metadata.Item) == 3
        assert metadata.Item[0]["Name"] == "Amount"
        assert metadata.Item[0]["Value"] == "1000"

    def test_callback_metadata_empty(self):
        """Test callback metadata with empty items."""
        data = {"Item": []}
        
        metadata = MpesaCallbackMetadata(**data)
        
        assert metadata.Item == []


class TestMpesaMetadataItem:
    """Test cases for MpesaMetadataItem schema."""

    def test_valid_metadata_item(self):
        """Test valid metadata item."""
        data = {
            "Name": "Amount",
            "Value": "1000"
        }
        
        item = MpesaMetadataItem(**data)
        
        assert item.Name == "Amount"
        assert item.Value == "1000"

    def test_metadata_item_extra_fields(self):
        """Test metadata item with extra fields."""
        data = {
            "Name": "Amount",
            "Value": "1000",
            "extra_field": "extra_value"
        }
        
        item = MpesaMetadataItem(**data)
        
        assert item.Name == "Amount"
        assert item.Value == "1000"
        assert hasattr(item, "extra_field")
        assert item.extra_field == "extra_value"
