"""Test billing endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus


class TestBillingEndpoints:
    """Test billing and payment endpoints."""

    async def test_get_invoices_authenticated(
        self, 
        client: AsyncClient, 
        auth_headers: dict
    ):
        """Test getting invoices with authentication."""
        response = await client.get("/api/v1/billing/invoices", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "invoices" in data
        assert "total" in data

    async def test_get_invoices_unauthorized(self, client: AsyncClient):
        """Test getting invoices without authentication."""
        response = await client.get("/api/v1/billing/invoices")
        
        assert response.status_code == 401

    async def test_generate_invoices_admin(
        self, 
        client: AsyncClient, 
        admin_auth_headers: dict
    ):
        """Test generating invoices as admin."""
        response = await client.post(
            "/api/v1/billing/invoices/generate",
            headers=admin_auth_headers
        )
        
        assert response.status_code == 200
        assert "Invoice generation not implemented yet" in response.json()["message"]

    async def test_generate_invoices_unauthorized(self, client: AsyncClient):
        """Test generating invoices without authentication."""
        response = await client.post("/api/v1/billing/invoices/generate")
        
        assert response.status_code == 401

    async def test_generate_invoices_customer_forbidden(
        self, 
        client: AsyncClient, 
        auth_headers: dict
    ):
        """Test generating invoices as customer (forbidden)."""
        response = await client.post(
            "/api/v1/billing/invoices/generate",
            headers=auth_headers
        )
        
        assert response.status_code == 403

    async def test_get_invoice_by_id(
        self, 
        client: AsyncClient, 
        auth_headers: dict
    ):
        """Test getting invoice by ID."""
        response = await client.get(
            "/api/v1/billing/invoices/1",
            headers=auth_headers
        )
        
        assert response.status_code == 404
        assert "Invoice not found" in response.json()["detail"]

    async def test_initiate_mpesa_stk(
        self, 
        client: AsyncClient, 
        auth_headers: dict
    ):
        """Test initiating MPESA STK Push."""
        response = await client.post(
            "/api/v1/billing/payments/mpesa/stk",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert "MPESA STK Push not implemented yet" in response.json()["message"]

    async def test_mpesa_callback(self, client: AsyncClient):
        """Test MPESA callback webhook."""
        callback_data = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test_merchant_id",
                    "CheckoutRequestID": "test_checkout_id",
                    "ResultCode": 0,
                    "ResultDesc": "Success"
                }
            }
        }
        
        response = await client.post(
            "/api/v1/billing/payments/mpesa/callback",
            json=callback_data
        )
        
        assert response.status_code == 200
        assert "MPESA callback not implemented yet" in response.json()["message"]

    async def test_get_payment_history(
        self, 
        client: AsyncClient, 
        auth_headers: dict
    ):
        """Test getting payment history."""
        response = await client.get(
            "/api/v1/billing/payments/history",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "payments" in data
        assert "total" in data

    async def test_get_payment_history_unauthorized(self, client: AsyncClient):
        """Test getting payment history without authentication."""
        response = await client.get("/api/v1/billing/payments/history")
        
        assert response.status_code == 401
