"""Tests for MPESA service module.

This module contains comprehensive tests for the high-level MPESA service
that integrates with the billing system.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.modules.billing import MpesaService
from app.core.exceptions import ValidationError, ExternalServiceError, BillingError
from app.models.user import User, UserRole, UserStatus
from app.models.billing import Payment, PaymentStatus, PaymentMethod


class TestMpesaService:
    """Test cases for MpesaService class."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_user(self):
        """Mock user object."""
        user = MagicMock(spec=User)
        user.id = 1
        user.phone_number = "254712345678"
        user.email = "test@example.com"
        user.username = "testuser"
        user.role = UserRole.CUSTOMER
        user.status = UserStatus.ACTIVE
        return user

    @pytest.fixture
    def mpesa_service(self, mock_db):
        """Create MpesaService instance."""
        return MpesaService(mock_db, environment="sandbox")

    @pytest.mark.asyncio
    async def test_initiate_payment_success(self, mpesa_service, mock_user):
        """Test successful payment initiation."""
        mock_stk_response = {
            "success": True,
            "data": {
                "CheckoutRequestID": "test_checkout_id",
                "MerchantRequestID": "test_merchant_id"
            },
            "phone_number": "254712345678",
            "amount": 1000
        }
        
        with patch.object(mpesa_service.mpesa_api, 'stk_push', return_value=mock_stk_response):
            result = await mpesa_service.initiate_payment(
                user=mock_user,
                amount=1000,
                account_reference="ISP123456",
                description="Test Payment"
            )
            
            assert result["success"] is True
            assert result["amount"] == 1000
            assert result["phone_number"] == "254712345678"
            assert "payment_id" in result
            assert "checkout_request_id" in result

    @pytest.mark.asyncio
    async def test_initiate_payment_no_phone(self, mpesa_service):
        """Test payment initiation with user having no phone number."""
        mock_user = MagicMock(spec=User)
        mock_user.phone_number = None
        
        with pytest.raises(ValidationError, match="User phone number is required"):
            await mpesa_service.initiate_payment(
                user=mock_user,
                amount=1000,
                account_reference="ISP123456"
            )

    @pytest.mark.asyncio
    async def test_initiate_payment_invalid_amount(self, mpesa_service, mock_user):
        """Test payment initiation with invalid amount."""
        with pytest.raises(ValidationError, match="Payment amount must be positive"):
            await mpesa_service.initiate_payment(
                user=mock_user,
                amount=0,
                account_reference="ISP123456"
            )

    @pytest.mark.asyncio
    async def test_initiate_payment_stk_failure(self, mpesa_service, mock_user):
        """Test payment initiation when STK Push fails."""
        mock_stk_response = {
            "success": False,
            "error": "STK Push failed"
        }
        
        with patch.object(mpesa_service.mpesa_api, 'stk_push', return_value=mock_stk_response):
            with pytest.raises(ExternalServiceError, match="STK Push failed"):
                await mpesa_service.initiate_payment(
                    user=mock_user,
                    amount=1000,
                    account_reference="ISP123456"
                )

    @pytest.mark.asyncio
    async def test_query_payment_status_success(self, mpesa_service):
        """Test successful payment status query."""
        mock_status_response = {
            "success": True,
            "data": {
                "ResultCode": 0,
                "ResultDesc": "Success"
            }
        }
        
        mock_payment = MagicMock(spec=Payment)
        mock_payment.id = 1
        mock_payment.status = PaymentStatus.PENDING
        mock_payment.amount = 1000
        mock_payment.metadata = {}
        
        with patch.object(mpesa_service.mpesa_api, 'query_stk_push_status', return_value=mock_status_response), \
             patch.object(mpesa_service.db, 'execute') as mock_execute:
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_payment
            mock_execute.return_value = mock_result
            
            result = await mpesa_service.query_payment_status("test_checkout_id")
            
            assert result["success"] is True
            assert result["payment_id"] == 1
            assert result["status"] == PaymentStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_query_payment_status_not_found(self, mpesa_service):
        """Test payment status query when payment not found."""
        mock_status_response = {
            "success": True,
            "data": {
                "ResultCode": 0,
                "ResultDesc": "Success"
            }
        }
        
        with patch.object(mpesa_service.mpesa_api, 'query_stk_push_status', return_value=mock_status_response), \
             patch.object(mpesa_service.db, 'execute') as mock_execute:
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_execute.return_value = mock_result
            
            with pytest.raises(ValidationError, match="Payment record not found"):
                await mpesa_service.query_payment_status("test_checkout_id")

    @pytest.mark.asyncio
    async def test_process_callback_success(self, mpesa_service):
        """Test successful callback processing."""
        callback_data = {
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
        
        mock_payment = MagicMock(spec=Payment)
        mock_payment.id = 1
        mock_payment.status = PaymentStatus.PENDING
        mock_payment.metadata = {}
        
        parsed_callback = {
            "success": True,
            "checkout_request_id": "test_checkout_id",
            "result_code": 0,
            "result_desc": "Success"
        }
        
        with patch.object(mpesa_service.mpesa_api, 'verify_callback_signature', return_value=True), \
             patch.object(mpesa_service.mpesa_api, 'parse_stk_callback', return_value=parsed_callback), \
             patch.object(mpesa_service.db, 'execute') as mock_execute:
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_payment
            mock_execute.return_value = mock_result
            
            result = await mpesa_service.process_callback(callback_data)
            
            assert result["success"] is True
            assert result["payment_id"] == 1
            assert result["status"] == PaymentStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_process_callback_invalid_signature(self, mpesa_service):
        """Test callback processing with invalid signature."""
        callback_data = {
            "signature": "invalid_signature",
            "Body": {}
        }
        
        with patch.object(mpesa_service.mpesa_api, 'verify_callback_signature', return_value=False):
            with pytest.raises(ValidationError, match="Invalid callback signature"):
                await mpesa_service.process_callback(callback_data)

    @pytest.mark.asyncio
    async def test_process_callback_parse_error(self, mpesa_service):
        """Test callback processing with parse error."""
        callback_data = {
            "signature": "test_signature",
            "Body": {}
        }
        
        parsed_callback = {
            "success": False,
            "error": "Parse error"
        }
        
        with patch.object(mpesa_service.mpesa_api, 'verify_callback_signature', return_value=True), \
             patch.object(mpesa_service.mpesa_api, 'parse_stk_callback', return_value=parsed_callback):
            
            with pytest.raises(ValidationError, match="Failed to parse callback"):
                await mpesa_service.process_callback(callback_data)

    @pytest.mark.asyncio
    async def test_get_transaction_status_success(self, mpesa_service):
        """Test successful transaction status query."""
        mock_response = {
            "success": True,
            "data": {
                "ResponseCode": "0",
                "ResponseDescription": "Success"
            }
        }
        
        with patch.object(mpesa_service.mpesa_api, 'get_transaction_status', return_value=mock_response):
            result = await mpesa_service.get_transaction_status("test_transaction_id")
            
            assert result["success"] is True
            assert result["transaction_id"] == "test_transaction_id"

    @pytest.mark.asyncio
    async def test_get_transaction_status_failure(self, mpesa_service):
        """Test transaction status query failure."""
        mock_response = {
            "success": False,
            "error": "API Error"
        }
        
        with patch.object(mpesa_service.mpesa_api, 'get_transaction_status', return_value=mock_response):
            with pytest.raises(ExternalServiceError, match="Transaction status query failed"):
                await mpesa_service.get_transaction_status("test_transaction_id")

    @pytest.mark.asyncio
    async def test_reverse_payment_success(self, mpesa_service):
        """Test successful payment reversal."""
        mock_payment = MagicMock(spec=Payment)
        mock_payment.id = 1
        mock_payment.status = PaymentStatus.COMPLETED
        mock_payment.amount = 1000
        mock_payment.external_reference = "test_transaction_id"
        mock_payment.user_id = 1
        mock_payment.metadata = {}
        
        mock_user = MagicMock(spec=User)
        mock_user.phone_number = "254712345678"
        
        mock_reversal_response = {
            "success": True,
            "data": {
                "ResponseCode": "0",
                "ResponseDescription": "Success"
            }
        }
        
        with patch.object(mpesa_service.mpesa_api, 'reverse_transaction', return_value=mock_reversal_response), \
             patch.object(mpesa_service.db, 'execute') as mock_execute:
            
            # Mock payment query
            mock_payment_result = MagicMock()
            mock_payment_result.scalar_one_or_none.return_value = mock_payment
            mock_execute.return_value = mock_payment_result
            
            # Mock user query
            mock_user_result = MagicMock()
            mock_user_result.scalar_one_or_none.return_value = mock_user
            mock_execute.return_value = mock_user_result
            
            result = await mpesa_service.reverse_payment(1, "Test reversal")
            
            assert result["success"] is True
            assert result["payment_id"] == 1

    @pytest.mark.asyncio
    async def test_reverse_payment_not_found(self, mpesa_service):
        """Test payment reversal when payment not found."""
        with patch.object(mpesa_service.db, 'execute') as mock_execute:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_execute.return_value = mock_result
            
            with pytest.raises(ValidationError, match="Payment not found"):
                await mpesa_service.reverse_payment(999, "Test reversal")

    @pytest.mark.asyncio
    async def test_reverse_payment_not_completed(self, mpesa_service):
        """Test payment reversal when payment not completed."""
        mock_payment = MagicMock(spec=Payment)
        mock_payment.status = PaymentStatus.PENDING
        
        with patch.object(mpesa_service.db, 'execute') as mock_execute:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_payment
            mock_execute.return_value = mock_result
            
            with pytest.raises(ValidationError, match="Only completed payments can be reversed"):
                await mpesa_service.reverse_payment(1, "Test reversal")

    @pytest.mark.asyncio
    async def test_reverse_payment_no_external_reference(self, mpesa_service):
        """Test payment reversal when payment has no external reference."""
        mock_payment = MagicMock(spec=Payment)
        mock_payment.status = PaymentStatus.COMPLETED
        mock_payment.external_reference = None
        
        with patch.object(mpesa_service.db, 'execute') as mock_execute:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_payment
            mock_execute.return_value = mock_result
            
            with pytest.raises(ValidationError, match="Payment has no external reference for reversal"):
                await mpesa_service.reverse_payment(1, "Test reversal")

    @pytest.mark.asyncio
    async def test_get_payment_statistics_success(self, mpesa_service):
        """Test successful payment statistics retrieval."""
        # Mock payment objects
        mock_payments = [
            MagicMock(spec=Payment, status=PaymentStatus.COMPLETED, amount=1000),
            MagicMock(spec=Payment, status=PaymentStatus.COMPLETED, amount=2000),
            MagicMock(spec=Payment, status=PaymentStatus.PENDING, amount=1500),
            MagicMock(spec=Payment, status=PaymentStatus.FAILED, amount=500),
        ]
        
        with patch.object(mpesa_service.db, 'execute') as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_payments
            mock_execute.return_value = mock_result
            
            result = await mpesa_service.get_payment_statistics()
            
            assert result["success"] is True
            assert result["statistics"]["total_payments"] == 4
            assert result["statistics"]["completed_payments"] == 2
            assert result["statistics"]["pending_payments"] == 1
            assert result["statistics"]["failed_payments"] == 1
            assert result["statistics"]["total_amount"] == 3000
            assert result["statistics"]["success_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_get_payment_statistics_empty(self, mpesa_service):
        """Test payment statistics with no payments."""
        with patch.object(mpesa_service.db, 'execute') as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result
            
            result = await mpesa_service.get_payment_statistics()
            
            assert result["success"] is True
            assert result["statistics"]["total_payments"] == 0
            assert result["statistics"]["success_rate"] == 0

    @pytest.mark.asyncio
    async def test_initiate_payment_database_error(self, mpesa_service, mock_user):
        """Test payment initiation with database error."""
        mock_stk_response = {
            "success": True,
            "data": {
                "CheckoutRequestID": "test_checkout_id",
                "MerchantRequestID": "test_merchant_id"
            },
            "phone_number": "254712345678",
            "amount": 1000
        }
        
        with patch.object(mpesa_service.mpesa_api, 'stk_push', return_value=mock_stk_response), \
             patch.object(mpesa_service.db, 'add') as mock_add, \
             patch.object(mpesa_service.db, 'commit', side_effect=Exception("Database error")):
            
            with pytest.raises(BillingError, match="Failed to initiate payment"):
                await mpesa_service.initiate_payment(
                    user=mock_user,
                    amount=1000,
                    account_reference="ISP123456"
                )

    @pytest.mark.asyncio
    async def test_process_callback_payment_not_found(self, mpesa_service):
        """Test callback processing when payment not found."""
        callback_data = {
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
        
        parsed_callback = {
            "success": True,
            "checkout_request_id": "test_checkout_id",
            "result_code": 0,
            "result_desc": "Success"
        }
        
        with patch.object(mpesa_service.mpesa_api, 'verify_callback_signature', return_value=True), \
             patch.object(mpesa_service.mpesa_api, 'parse_stk_callback', return_value=parsed_callback), \
             patch.object(mpesa_service.db, 'execute') as mock_execute:
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_execute.return_value = mock_result
            
            result = await mpesa_service.process_callback(callback_data)
            
            assert result["success"] is False
            assert "Payment not found" in result["error"]
