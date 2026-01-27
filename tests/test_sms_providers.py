"""Tests for SMS providers (Twilio and Africa's Talking)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.integrations.sms.base import (
    SMSProviderInterface, 
    SMSResult, 
    SMSDeliveryStatus,
    SMSProviderConfig,
)
from app.integrations.sms.twilio_provider import TwilioSMSProvider
from app.integrations.sms.africastalking_provider import AfricasTalkingSMSProvider
from app.integrations.sms.factory import SMSProviderFactory
from app.models.sms_credit import SMSProviderType


class TestSMSResult:
    """Tests for SMS Result dataclass."""

    def test_sms_result_success(self):
        """Test successful SMS result creation."""
        result = SMSResult(
            success=True,
            message_id="msg_123",
            status=SMSDeliveryStatus.SENT,
            raw_response={"id": "msg_123"},
        )
        
        assert result.success is True
        assert result.message_id == "msg_123"
        assert result.status == SMSDeliveryStatus.SENT
        assert result.error_code is None

    def test_sms_result_failure(self):
        """Test failed SMS result creation."""
        result = SMSResult(
            success=False,
            status=SMSDeliveryStatus.FAILED,
            error_code="INVALID_PHONE",
            message="Invalid phone number",
        )
        
        assert result.success is False
        assert result.message_id is None
        assert result.status == SMSDeliveryStatus.FAILED
        assert result.error_code == "INVALID_PHONE"

    def test_sms_delivery_status_enum(self):
        """Test SMS delivery status enum values."""
        assert SMSDeliveryStatus.QUEUED.value == "queued"
        assert SMSDeliveryStatus.SENT.value == "sent"
        assert SMSDeliveryStatus.DELIVERED.value == "delivered"
        assert SMSDeliveryStatus.FAILED.value == "failed"


class TestTwilioSMSProvider:
    """Tests for Twilio SMS provider."""

    @pytest.fixture
    def twilio_config(self):
        """Create Twilio config."""
        return SMSProviderConfig(
            provider_type="twilio",
            credentials={
                "account_sid": "test_sid",
                "auth_token": "test_token",
                "from_number": "+1234567890",
            },
            is_active=True,
            default_country_code="+254",
        )

    @pytest.fixture
    def twilio_provider(self, twilio_config):
        """Create Twilio provider with test credentials."""
        return TwilioSMSProvider(twilio_config)

    def test_provider_type(self, twilio_provider):
        """Test provider type."""
        assert twilio_provider.provider_name == "Twilio"

    @pytest.mark.asyncio
    async def test_format_phone_number_with_plus(self, twilio_provider):
        """Test phone number formatting with plus sign."""
        result = twilio_provider._format_phone_number("+254712345678")
        assert result == "+254712345678"

    @pytest.mark.asyncio
    async def test_format_phone_number_without_plus(self, twilio_provider):
        """Test phone number formatting without plus sign."""
        result = twilio_provider._format_phone_number("254712345678")
        assert result == "+254712345678"

    @pytest.mark.asyncio
    async def test_format_phone_number_with_leading_zero(self, twilio_provider):
        """Test phone number formatting with leading zero (Kenya)."""
        result = twilio_provider._format_phone_number("0712345678")
        assert result == "+254712345678"

    @pytest.mark.asyncio
    async def test_send_sms_success(self, twilio_provider):
        """Test successful SMS sending via Twilio."""
        mock_message = MagicMock()
        mock_message.sid = "SM123456"
        mock_message.status = "sent"
        mock_message.price = "-0.0075"
        mock_message.price_unit = "USD"
        mock_message.date_sent = datetime.utcnow()
        
        with patch.object(
            twilio_provider, "_send_via_twilio", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = mock_message
            
            result = await twilio_provider.send_sms(
                to="+254712345678",
                message="Test message",
            )
            
            assert result.success is True
            assert result.message_id == "SM123456"

    @pytest.mark.asyncio
    async def test_send_sms_failure(self, twilio_provider):
        """Test SMS sending failure via Twilio."""
        with patch.object(
            twilio_provider, "_send_via_twilio", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Invalid phone number")
            
            result = await twilio_provider.send_sms(
                to="+invalid",
                message="Test message",
            )
            
            assert result.success is False
            assert result.status == SMSDeliveryStatus.FAILED

    @pytest.mark.asyncio
    async def test_send_bulk_sms(self, twilio_provider):
        """Test bulk SMS sending via Twilio."""
        mock_message = MagicMock()
        mock_message.sid = "SM123456"
        mock_message.status = "sent"
        mock_message.price = None
        mock_message.price_unit = None
        mock_message.date_sent = None
        
        with patch.object(
            twilio_provider, "_send_via_twilio", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = mock_message
            
            results = await twilio_provider.send_bulk_sms(
                recipients=["+254712345678", "+254723456789"],
                message="Test bulk message",
            )
            
            assert len(results) == 2
            assert all(r.success for r in results)


class TestAfricasTalkingSMSProvider:
    """Tests for Africa's Talking SMS provider."""

    @pytest.fixture
    def at_config(self):
        """Create Africa's Talking config."""
        return SMSProviderConfig(
            provider_type="africastalking",
            credentials={
                "username": "sandbox",
                "api_key": "test_api_key",
                "sender_id": "TestSender",
            },
            is_active=True,
            default_country_code="+254",
        )

    @pytest.fixture
    def at_provider(self, at_config):
        """Create Africa's Talking provider with test credentials."""
        with patch("app.integrations.sms.africastalking_provider.africastalking") as mock_at:
            mock_at.initialize = MagicMock()
            mock_at.SMS = MagicMock()
            provider = AfricasTalkingSMSProvider(at_config)
            return provider

    def test_provider_type(self, at_provider):
        """Test provider type."""
        assert at_provider.provider_name == "Africa's Talking"

    @pytest.mark.asyncio
    async def test_format_phone_number(self, at_provider):
        """Test phone number formatting for AT."""
        result = at_provider._format_phone_number("0712345678")
        assert result == "+254712345678"

    @pytest.mark.asyncio
    async def test_send_sms_success(self, at_provider):
        """Test successful SMS sending via Africa's Talking."""
        mock_response = {
            "SMSMessageData": {
                "Recipients": [
                    {
                        "messageId": "AT_123456",
                        "status": "Success",
                        "statusCode": 101,
                        "cost": "KES 0.80",
                    }
                ]
            }
        }
        
        with patch.object(
            at_provider, "_send_via_at", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = mock_response
            
            result = await at_provider.send_sms(
                to="+254712345678",
                message="Test message",
            )
            
            assert result.success is True
            assert result.message_id == "AT_123456"

    @pytest.mark.asyncio
    async def test_send_sms_failure(self, at_provider):
        """Test SMS sending failure via Africa's Talking."""
        mock_response = {
            "SMSMessageData": {
                "Recipients": [
                    {
                        "messageId": None,
                        "status": "InvalidPhoneNumber",
                        "statusCode": 403,
                    }
                ]
            }
        }
        
        with patch.object(
            at_provider, "_send_via_at", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = mock_response
            
            result = await at_provider.send_sms(
                to="+invalid",
                message="Test message",
            )
            
            assert result.success is False
            assert result.status == SMSDeliveryStatus.FAILED


class TestSMSProviderFactory:
    """Tests for SMS provider factory."""

    @pytest.mark.asyncio
    async def test_create_twilio_provider(self):
        """Test creating Twilio provider via factory."""
        provider = await SMSProviderFactory.create(
            provider_type=SMSProviderType.TWILIO,
            credentials={
                "account_sid": "test_sid",
                "auth_token": "test_token",
                "from_number": "+1234567890",
            },
        )
        assert provider.provider_name == "Twilio"

    @pytest.mark.asyncio
    async def test_create_africastalking_provider(self):
        """Test creating Africa's Talking provider via factory."""
        with patch("app.integrations.sms.africastalking_provider.africastalking") as mock_at:
            mock_at.initialize = MagicMock()
            mock_at.SMS = MagicMock()
            
            provider = await SMSProviderFactory.create(
                provider_type=SMSProviderType.AFRICASTALKING,
                credentials={
                    "username": "sandbox",
                    "api_key": "test_key",
                },
            )
            assert provider.provider_name == "Africa's Talking"

    def test_get_available_providers(self):
        """Test getting available providers."""
        providers = SMSProviderFactory.get_available_providers()
        assert isinstance(providers, dict)
        # At minimum, twilio and africastalking should be available
        assert "twilio" in providers or SMSProviderType.TWILIO.value in str(providers)

