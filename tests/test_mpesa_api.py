"""Tests for MPESA API endpoints.

This module contains comprehensive tests for the MPESA REST API endpoints
that handle payment processing and status queries.

Reference: https://developer.safaricom.co.ke/Documentation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import status

from app.main import app
from app.models.user import User, UserRole, UserStatus
from app.models.billing import Payment, PaymentStatus, PaymentMethod


class TestMpesaAPIEndpoints:
    """Test cases for MPESA API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_user(self):
        """Mock authenticated user."""
        user = MagicMock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.email = "test@example.com"
        user.phone_number = "254712345678"
        user.role = UserRole.CUSTOMER
        user.status = UserStatus.ACTIVE
        return user

    @pytest.fixture
    def mock_admin_user(self):
        """Mock admin user."""
        user = MagicMock(spec=User)
        user.id = 1
        user.username = "admin"
        user.email = "admin@example.com"
        user.phone_number = "254712345678"
        user.role = UserRole.ADMIN
        user.status = UserStatus.ACTIVE
        return user

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()

    def test_initiate_payment_success(self, client, mock_user, mock_db):
        """Test successful payment initiation endpoint."""
        payment_data = {
            "amount": 1000,
            "account_reference": "ISP123456",
            "description": "Test Payment"
        }
        
        mock_response = {
            "success": True,
            "payment_id": 1,
            "checkout_request_id": "test_checkout_id",
            "amount": 1000,
            "phone_number": "254712345678",
            "message": "Payment request sent to your phone"
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.initiate_payment.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/initiate-payment", json=payment_data)
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["amount"] == 1000
            assert data["phone_number"] == "254712345678"

    def test_initiate_payment_validation_error(self, client, mock_user, mock_db):
        """Test payment initiation with validation error."""
        payment_data = {
            "amount": 0,  # Invalid amount
            "account_reference": "ISP123456"
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.initiate_payment.side_effect = Exception("Validation error")
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/initiate-payment", json=payment_data)
            
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_initiate_payment_unauthorized(self, client):
        """Test payment initiation without authentication."""
        payment_data = {
            "amount": 1000,
            "account_reference": "ISP123456"
        }
        
        response = client.post("/api/v1/mpesa/initiate-payment", json=payment_data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_payment_status_success(self, client, mock_user, mock_db):
        """Test successful payment status query endpoint."""
        checkout_request_id = "test_checkout_id"
        
        mock_response = {
            "success": True,
            "payment_id": 1,
            "status": "completed",
            "amount": 1000,
            "mpesa_response": {
                "ResultCode": 0,
                "ResultDesc": "Success"
            }
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.query_payment_status.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.get(f"/api/v1/mpesa/payment-status/{checkout_request_id}")
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["status"] == "completed"

    def test_get_payment_status_not_found(self, client, mock_user, mock_db):
        """Test payment status query when payment not found."""
        checkout_request_id = "nonexistent_id"
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.query_payment_status.side_effect = Exception("Payment not found")
            mock_service_class.return_value = mock_service
            
            response = client.get(f"/api/v1/mpesa/payment-status/{checkout_request_id}")
            
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_process_callback_success(self, client, mock_db):
        """Test successful callback processing endpoint."""
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
        
        mock_response = {
            "success": True,
            "payment_id": 1,
            "status": "completed",
            "result_code": 0
        }
        
        with patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.process_callback.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/callback", json=callback_data)
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["status"] == "completed"

    def test_process_callback_invalid_signature(self, client, mock_db):
        """Test callback processing with invalid signature."""
        callback_data = {
            "signature": "invalid_signature",
            "Body": {}
        }
        
        with patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.process_callback.side_effect = Exception("Invalid signature")
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/callback", json=callback_data)
            
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_get_transaction_status_success(self, client, mock_user, mock_db):
        """Test successful transaction status query endpoint."""
        transaction_id = "test_transaction_id"
        
        mock_response = {
            "success": True,
            "transaction_id": transaction_id,
            "status_data": {
                "ResponseCode": "0",
                "ResponseDescription": "Success"
            }
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.get_transaction_status.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.get(f"/api/v1/mpesa/transaction-status/{transaction_id}")
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["transaction_id"] == transaction_id

    def test_reverse_payment_success(self, client, mock_user, mock_db):
        """Test successful payment reversal endpoint."""
        reversal_data = {
            "payment_id": 1,
            "reason": "Customer requested refund"
        }
        
        mock_response = {
            "success": True,
            "payment_id": 1,
            "reversal_data": {
                "ResponseCode": "0",
                "ResponseDescription": "Success"
            }
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.reverse_payment.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/reverse-payment", json=reversal_data)
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["payment_id"] == 1

    def test_reverse_payment_not_found(self, client, mock_user, mock_db):
        """Test payment reversal when payment not found."""
        reversal_data = {
            "payment_id": 999,
            "reason": "Test reversal"
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.reverse_payment.side_effect = Exception("Payment not found")
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/reverse-payment", json=reversal_data)
            
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_get_payment_statistics_success(self, client, mock_user, mock_db):
        """Test successful payment statistics endpoint."""
        mock_response = {
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
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.get_payment_statistics.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.get("/api/v1/mpesa/statistics")
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["statistics"]["total_payments"] == 100
            assert data["statistics"]["success_rate"] == 95.0

    def test_get_payment_statistics_error(self, client, mock_user, mock_db):
        """Test payment statistics with error."""
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.get_payment_statistics.side_effect = Exception("Database error")
            mock_service_class.return_value = mock_service
            
            response = client.get("/api/v1/mpesa/statistics")
            
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_initiate_payment_missing_phone(self, client, mock_db):
        """Test payment initiation with user having no phone number."""
        mock_user = MagicMock(spec=User)
        mock_user.phone_number = None
        
        payment_data = {
            "amount": 1000,
            "account_reference": "ISP123456"
        }
        
        with patch('app.api.v1.mpesa.get_current_user', return_value=mock_user), \
             patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.initiate_payment.side_effect = Exception("User phone number is required")
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/initiate-payment", json=payment_data)
            
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_callback_processing_payment_not_found(self, client, mock_db):
        """Test callback processing when payment not found."""
        callback_data = {
            "signature": "test_signature",
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "nonexistent_id",
                    "ResultCode": 0,
                    "ResultDesc": "Success"
                }
            }
        }
        
        mock_response = {
            "success": False,
            "error": "Payment not found"
        }
        
        with patch('app.api.v1.mpesa.get_db', return_value=mock_db), \
             patch('app.api.v1.mpesa.MpesaService') as mock_service_class:
            
            mock_service = AsyncMock()
            mock_service.process_callback.return_value = mock_response
            mock_service_class.return_value = mock_service
            
            response = client.post("/api/v1/mpesa/callback", json=callback_data)
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is False
            assert "Payment not found" in data["error"]

    def test_api_documentation_available(self, client):
        """Test that API documentation is accessible."""
        response = client.get("/docs")
        assert response.status_code == status.HTTP_200_OK

    def test_openapi_schema_available(self, client):
        """Test that OpenAPI schema is accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK

    def test_mpesa_endpoints_in_openapi(self, client):
        """Test that MPESA endpoints are included in OpenAPI schema."""
        response = client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        
        schema = response.json()
        paths = schema.get("paths", {})
        
        # Check that MPESA endpoints are present
        assert "/api/v1/mpesa/initiate-payment" in paths
        assert "/api/v1/mpesa/payment-status/{checkout_request_id}" in paths
        assert "/api/v1/mpesa/callback" in paths
        assert "/api/v1/mpesa/transaction-status/{transaction_id}" in paths
        assert "/api/v1/mpesa/reverse-payment" in paths
        assert "/api/v1/mpesa/statistics" in paths

    def test_mpesa_schemas_in_openapi(self, client):
        """Test that MPESA schemas are included in OpenAPI schema."""
        response = client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        
        schema = response.json()
        components = schema.get("components", {})
        schemas = components.get("schemas", {})
        
        # Check that MPESA schemas are present
        assert "MpesaPaymentRequest" in schemas
        assert "MpesaPaymentResponse" in schemas
        assert "MpesaStatusResponse" in schemas
        assert "MpesaCallbackResponse" in schemas
        assert "MpesaReversalRequest" in schemas
        assert "MpesaReversalResponse" in schemas
        assert "MpesaStatisticsResponse" in schemas
