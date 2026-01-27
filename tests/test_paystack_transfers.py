"""Tests for Paystack payment gateway transfers and subscriptions."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.integrations.payment_gateways.paystack import PaystackGateway


class TestPaystackTransfers:
    """Tests for Paystack transfer functionality."""

    @pytest.fixture
    def paystack_config(self):
        """Create Paystack config."""
        return {
            "credentials": {
                "secret_key": "sk_test_xxxxx",
                "public_key": "pk_test_xxxxx",
            },
            "callback_url": "https://example.com/callback",
        }

    @pytest.fixture
    def paystack(self, paystack_config):
        """Create Paystack gateway with test credentials."""
        return PaystackGateway(paystack_config)

    @pytest.fixture
    def mock_http_client(self):
        """Create mock HTTP client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_create_transfer_recipient_bank(self, paystack, mock_http_client):
        """Test creating a bank transfer recipient."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Transfer Recipient Created",
            "data": {
                "active": True,
                "createdAt": "2024-01-01T00:00:00.000Z",
                "currency": "NGN",
                "domain": "test",
                "id": 12345,
                "integration": 100032,
                "name": "John Doe",
                "recipient_code": "RCP_xxxxx",
                "type": "nuban",
                "details": {
                    "account_number": "0123456789",
                    "account_name": "John Doe",
                    "bank_code": "058",
                    "bank_name": "GTBank"
                }
            }
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.create_transfer_recipient(
                recipient_type="nuban",
                name="John Doe",
                account_number="0123456789",
                bank_code="058",
                currency="NGN",
            )

            assert result["status"] is True
            assert result["data"]["recipient_code"] == "RCP_xxxxx"
            assert result["data"]["type"] == "nuban"

    @pytest.mark.asyncio
    async def test_create_transfer_recipient_mobile_money(self, paystack, mock_http_client):
        """Test creating a mobile money transfer recipient."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Transfer Recipient Created",
            "data": {
                "recipient_code": "RCP_mobile_xxxxx",
                "type": "mobile_money",
                "details": {
                    "account_number": "+254712345678",
                    "account_name": "Jane Doe",
                }
            }
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.create_transfer_recipient(
                recipient_type="mobile_money",
                name="Jane Doe",
                account_number="+254712345678",
                bank_code="MTN",  # Mobile provider code
                currency="GHS",
            )

            assert result["status"] is True
            assert result["data"]["type"] == "mobile_money"

    @pytest.mark.asyncio
    async def test_initiate_transfer_success(self, paystack, mock_http_client):
        """Test initiating a transfer."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Transfer requires OTP to continue",
            "data": {
                "reference": "TRF_test123",
                "integration": 100032,
                "domain": "test",
                "amount": 50000,
                "currency": "NGN",
                "source": "balance",
                "reason": "Payout to user",
                "recipient": 12345,
                "status": "otp",
                "transfer_code": "TRF_xxxxx",
                "id": 67890,
                "createdAt": "2024-01-01T12:00:00.000Z",
                "updatedAt": "2024-01-01T12:00:00.000Z"
            }
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.initiate_transfer(
                amount=50000,
                recipient_code="RCP_xxxxx",
                reason="Payout to user",
                reference="TRF_test123",
            )

            assert result["status"] is True
            assert result["data"]["transfer_code"] == "TRF_xxxxx"
            assert result["data"]["amount"] == 50000

    @pytest.mark.asyncio
    async def test_verify_transfer(self, paystack, mock_http_client):
        """Test verifying a transfer."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Transfer fetched",
            "data": {
                "id": 67890,
                "amount": 50000,
                "currency": "NGN",
                "reference": "TRF_test123",
                "status": "success",
                "transfer_code": "TRF_xxxxx",
                "recipient": {
                    "recipient_code": "RCP_xxxxx",
                    "name": "John Doe"
                }
            }
        }
        mock_http_client.get.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.verify_transfer("TRF_test123")

            assert result["status"] is True
            assert result["data"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_initiate_bulk_transfer(self, paystack, mock_http_client):
        """Test initiating bulk transfers."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Bulk transfers queued",
            "data": [
                {
                    "reference": "TRF_1",
                    "recipient": "RCP_1",
                    "amount": 10000,
                    "status": "pending",
                },
                {
                    "reference": "TRF_2",
                    "recipient": "RCP_2",
                    "amount": 20000,
                    "status": "pending",
                }
            ]
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            transfers = [
                {"amount": 10000, "recipient": "RCP_1", "reference": "TRF_1"},
                {"amount": 20000, "recipient": "RCP_2", "reference": "TRF_2"},
            ]
            result = await paystack.initiate_bulk_transfer(transfers)

            assert result["status"] is True
            assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_list_banks(self, paystack, mock_http_client):
        """Test listing supported banks."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Banks retrieved",
            "data": [
                {"id": 1, "name": "Access Bank", "slug": "access-bank", "code": "044"},
                {"id": 2, "name": "GTBank", "slug": "gtbank", "code": "058"},
                {"id": 3, "name": "First Bank", "slug": "first-bank", "code": "011"},
            ]
        }
        mock_http_client.get.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.list_banks(country="nigeria")

            assert result["status"] is True
            assert len(result["data"]) == 3
            assert result["data"][0]["code"] == "044"

    @pytest.mark.asyncio
    async def test_list_mobile_money_providers(self, paystack, mock_http_client):
        """Test listing mobile money providers."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Mobile Money providers retrieved",
            "data": [
                {"name": "MTN", "slug": "mtn", "code": "MTN"},
                {"name": "Vodafone", "slug": "vodafone", "code": "VOD"},
            ]
        }
        mock_http_client.get.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.list_mobile_money_providers(country="ghana")

            assert result["status"] is True
            assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_resolve_account_number(self, paystack, mock_http_client):
        """Test resolving bank account number."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Account number resolved",
            "data": {
                "account_number": "0123456789",
                "account_name": "JOHN DOE",
                "bank_id": 1
            }
        }
        mock_http_client.get.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.resolve_account_number(
                account_number="0123456789",
                bank_code="058",
            )

            assert result["status"] is True
            assert result["data"]["account_name"] == "JOHN DOE"


class TestPaystackSubscriptions:
    """Tests for Paystack subscription functionality."""

    @pytest.fixture
    def paystack_config(self):
        """Create Paystack config."""
        return {
            "credentials": {
                "secret_key": "sk_test_xxxxx",
                "public_key": "pk_test_xxxxx",
            },
            "callback_url": "https://example.com/callback",
        }

    @pytest.fixture
    def paystack(self, paystack_config):
        """Create Paystack gateway with test credentials."""
        return PaystackGateway(paystack_config)

    @pytest.fixture
    def mock_http_client(self):
        """Create mock HTTP client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_create_plan(self, paystack, mock_http_client):
        """Test creating a subscription plan."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Plan created",
            "data": {
                "id": 12345,
                "name": "Premium Plan",
                "plan_code": "PLN_xxxxx",
                "amount": 500000,
                "interval": "monthly",
                "currency": "NGN",
                "send_invoices": True,
                "send_sms": True,
            }
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.create_plan(
                name="Premium Plan",
                amount=500000,
                interval="monthly",
                description="Premium subscription plan",
            )

            assert result["status"] is True
            assert result["data"]["plan_code"] == "PLN_xxxxx"
            assert result["data"]["interval"] == "monthly"

    @pytest.mark.asyncio
    async def test_list_plans(self, paystack, mock_http_client):
        """Test listing subscription plans."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Plans retrieved",
            "data": [
                {
                    "id": 1,
                    "name": "Basic Plan",
                    "plan_code": "PLN_basic",
                    "amount": 100000,
                    "interval": "monthly",
                },
                {
                    "id": 2,
                    "name": "Premium Plan",
                    "plan_code": "PLN_premium",
                    "amount": 500000,
                    "interval": "monthly",
                }
            ],
            "meta": {"total": 2, "page": 1, "perPage": 50}
        }
        mock_http_client.get.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.list_plans()

            assert result["status"] is True
            assert len(result["data"]) == 2
            assert result["data"][0]["plan_code"] == "PLN_basic"

    @pytest.mark.asyncio
    async def test_get_subscription(self, paystack, mock_http_client):
        """Test getting subscription details."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Subscription retrieved",
            "data": {
                "id": 67890,
                "subscription_code": "SUB_xxxxx",
                "email_token": "abc123",
                "amount": 500000,
                "status": "active",
                "next_payment_date": "2024-02-01T00:00:00.000Z",
                "plan": {
                    "id": 12345,
                    "name": "Premium Plan",
                    "plan_code": "PLN_premium",
                },
                "customer": {
                    "id": 11111,
                    "email": "customer@example.com",
                }
            }
        }
        mock_http_client.get.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.get_subscription("SUB_xxxxx")

            assert result["status"] is True
            assert result["data"]["subscription_code"] == "SUB_xxxxx"
            assert result["data"]["status"] == "active"


class TestPaystackWebhooks:
    """Tests for Paystack webhook handling."""

    @pytest.fixture
    def paystack_config(self):
        """Create Paystack config."""
        return {
            "credentials": {
                "secret_key": "sk_test_xxxxx",
                "public_key": "pk_test_xxxxx",
            },
            "callback_url": "https://example.com/callback",
        }

    @pytest.fixture
    def paystack(self, paystack_config):
        """Create Paystack gateway with test credentials."""
        return PaystackGateway(paystack_config)

    def test_verify_webhook_signature_valid(self, paystack):
        """Test valid webhook signature verification."""
        import hashlib
        import hmac

        payload = '{"event":"charge.success","data":{"id":123}}'
        secret = "sk_test_xxxxx"
        expected_signature = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha512
        ).hexdigest()

        # Assuming PaystackGateway has verify_webhook method
        is_valid = paystack.verify_webhook_signature(payload, expected_signature)
        assert is_valid is True

    def test_verify_webhook_signature_invalid(self, paystack):
        """Test invalid webhook signature verification."""
        payload = '{"event":"charge.success","data":{"id":123}}'
        invalid_signature = "invalid_signature_hash"

        is_valid = paystack.verify_webhook_signature(payload, invalid_signature)
        assert is_valid is False


class TestPaystackErrors:
    """Tests for Paystack error handling."""

    @pytest.fixture
    def paystack_config(self):
        """Create Paystack config."""
        return {
            "credentials": {
                "secret_key": "sk_test_xxxxx",
                "public_key": "pk_test_xxxxx",
            },
            "callback_url": "https://example.com/callback",
        }

    @pytest.fixture
    def paystack(self, paystack_config):
        """Create Paystack gateway with test credentials."""
        return PaystackGateway(paystack_config)

    @pytest.fixture
    def mock_http_client(self):
        """Create mock HTTP client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_transfer_insufficient_balance(self, paystack, mock_http_client):
        """Test transfer with insufficient balance."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": False,
            "message": "Insufficient funds in balance",
            "data": None
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.initiate_transfer(
                amount=99999999999,
                recipient_code="RCP_xxxxx",
                reason="Large payout",
            )

            assert result["status"] is False
            assert "Insufficient" in result["message"]

    @pytest.mark.asyncio
    async def test_invalid_recipient_code(self, paystack, mock_http_client):
        """Test transfer with invalid recipient code."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": False,
            "message": "Recipient code is invalid",
            "data": None
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(paystack, "_client", mock_http_client):
            result = await paystack.initiate_transfer(
                amount=10000,
                recipient_code="RCP_invalid",
                reason="Test payout",
            )

            assert result["status"] is False
            assert "invalid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_network_error_handling(self, paystack, mock_http_client):
        """Test handling of network errors."""
        mock_http_client.post.side_effect = Exception("Network timeout")

        with patch.object(paystack, "_client", mock_http_client):
            with pytest.raises(Exception, match="Network timeout"):
                await paystack.initiate_transfer(
                    amount=10000,
                    recipient_code="RCP_xxxxx",
                    reason="Test payout",
                )
