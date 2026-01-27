"""Twilio SMS provider implementation.

Twilio provides global SMS coverage with excellent deliverability.
This is the default SMS provider for ISP Billing.

Documentation: https://www.twilio.com/docs/sms

Environment variables required:
    TWILIO_ACCOUNT_SID: Twilio account SID
    TWILIO_AUTH_TOKEN: Twilio auth token
    TWILIO_FROM_NUMBER: Default sender phone number (E.164 format)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.logging import get_logger
from .base import (
    SMSProviderInterface,
    SMSProviderConfig,
    SMSResult,
    BulkSMSResult,
    SMSDeliveryStatus,
)

logger = get_logger(__name__)


class TwilioSMSProvider(SMSProviderInterface):
    """Twilio SMS provider implementation.
    
    Supports:
    - Single and bulk SMS sending
    - Delivery status tracking
    - Alphanumeric sender IDs (where supported)
    - Unicode messages
    - MMS (multimedia messages)
    
    Required credentials:
        account_sid: Twilio Account SID
        auth_token: Twilio Auth Token
        from_number: Default sender phone number (E.164)
        
    Optional settings:
        messaging_service_sid: Twilio Messaging Service SID (for advanced routing)
        status_callback_url: URL for delivery status webhooks
    """
    
    BASE_URL = "https://api.twilio.com/2010-04-01"
    
    # Map Twilio status to our status enum
    STATUS_MAP = {
        "queued": SMSDeliveryStatus.QUEUED,
        "accepted": SMSDeliveryStatus.QUEUED,
        "sending": SMSDeliveryStatus.SENT,
        "sent": SMSDeliveryStatus.SENT,
        "delivered": SMSDeliveryStatus.DELIVERED,
        "undelivered": SMSDeliveryStatus.UNDELIVERED,
        "failed": SMSDeliveryStatus.FAILED,
    }
    
    def _validate_config(self) -> None:
        """Validate Twilio configuration."""
        credentials = self.config.credentials
        
        if not credentials.get("account_sid"):
            raise ValueError("Twilio account_sid is required")
        if not credentials.get("auth_token"):
            raise ValueError("Twilio auth_token is required")
        if not credentials.get("from_number") and not credentials.get("messaging_service_sid"):
            raise ValueError("Twilio from_number or messaging_service_sid is required")
    
    @property
    def provider_name(self) -> str:
        return "Twilio"
    
    @property
    def supports_delivery_reports(self) -> bool:
        return True
    
    @property
    def supports_bulk_sms(self) -> bool:
        return True
    
    @property
    def _account_sid(self) -> str:
        """Get Twilio Account SID."""
        return self.config.credentials["account_sid"]
    
    @property
    def _auth_token(self) -> str:
        """Get Twilio Auth Token."""
        return self.config.credentials["auth_token"]
    
    @property
    def _from_number(self) -> Optional[str]:
        """Get default sender phone number."""
        return self.config.credentials.get("from_number")
    
    @property
    def _messaging_service_sid(self) -> Optional[str]:
        """Get Messaging Service SID."""
        return self.config.credentials.get("messaging_service_sid")
    
    @property
    def _status_callback_url(self) -> Optional[str]:
        """Get status callback URL."""
        return self.config.credentials.get("status_callback_url")
    
    @property
    def _auth(self) -> Tuple[str, str]:
        """Get HTTP basic auth credentials."""
        return (self._account_sid, self._auth_token)
    
    async def send_sms(
        self,
        to: str,
        message: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SMSResult:
        """Send SMS via Twilio.
        
        Args:
            to: Recipient phone number
            message: SMS message content
            sender_id: Optional sender ID override (phone number or alphanumeric)
            metadata: Optional metadata (not sent to Twilio, for internal use)
            
        Returns:
            SMSResult with send status
        """
        try:
            # Format phone number
            formatted_to = self.format_phone_number(to)
            
            # Build request payload
            payload: Dict[str, str] = {
                "To": formatted_to,
                "Body": message,
            }
            
            # Set sender - priority: sender_id param > messaging service > from_number
            if sender_id:
                payload["From"] = sender_id
            elif self._messaging_service_sid:
                payload["MessagingServiceSid"] = self._messaging_service_sid
            elif self._from_number:
                payload["From"] = self._from_number
            
            # Add status callback if configured
            if self._status_callback_url:
                payload["StatusCallback"] = self._status_callback_url
            
            # Send request
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    f"{self.BASE_URL}/Accounts/{self._account_sid}/Messages.json",
                    data=payload,
                    auth=self._auth,
                )
                
                data = response.json()
                
                if response.status_code in (200, 201):
                    # Success
                    status = self.STATUS_MAP.get(
                        data.get("status", ""),
                        SMSDeliveryStatus.UNKNOWN
                    )
                    
                    return SMSResult(
                        success=True,
                        message_id=data.get("sid"),
                        status=status,
                        recipient=formatted_to,
                        cost=float(data.get("price", 0)) if data.get("price") else None,
                        currency=data.get("price_unit"),
                        segments=data.get("num_segments", 1),
                        message="SMS sent successfully",
                        raw_response=data,
                        sent_at=datetime.utcnow(),
                    )
                else:
                    # Error
                    error_code = str(data.get("code", ""))
                    error_message = data.get("message", "Unknown error")
                    
                    logger.error(
                        f"Twilio SMS failed: {error_code} - {error_message}",
                        extra={"to": formatted_to, "error": data},
                    )
                    
                    return SMSResult(
                        success=False,
                        status=SMSDeliveryStatus.FAILED,
                        recipient=formatted_to,
                        message=error_message,
                        error_code=error_code,
                        raw_response=data,
                    )
        
        except httpx.TimeoutException:
            logger.error(f"Twilio SMS timeout for {to}")
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message="Request timeout",
                error_code="TIMEOUT",
            )
        except Exception as e:
            logger.error(f"Twilio SMS error: {e}")
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message=str(e),
                error_code="INTERNAL_ERROR",
            )
    
    async def send_bulk_sms(
        self,
        recipients: List[str],
        message: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BulkSMSResult:
        """Send bulk SMS via Twilio.
        
        For Twilio, we use concurrent requests with rate limiting.
        For high-volume sending, consider using Twilio Messaging Services
        with geographic routing and fallback numbers.
        
        Args:
            recipients: List of recipient phone numbers
            message: SMS message content
            sender_id: Optional sender ID override
            metadata: Optional metadata
            
        Returns:
            BulkSMSResult with aggregated results
        """
        import asyncio
        
        # Rate limit: process in batches
        batch_size = min(self.config.rate_limit_per_second, 10)
        results = []
        successful = 0
        failed = 0
        total_cost = 0.0
        currency = None
        
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i:i + batch_size]
            
            # Send batch concurrently
            tasks = [
                self.send_sms(to=recipient, message=message, sender_id=sender_id, metadata=metadata)
                for recipient in batch
            ]
            batch_results = await asyncio.gather(*tasks)
            
            for result in batch_results:
                results.append(result)
                if result.success:
                    successful += 1
                    if result.cost:
                        total_cost += result.cost
                    if result.currency and not currency:
                        currency = result.currency
                else:
                    failed += 1
            
            # Small delay between batches for rate limiting
            if i + batch_size < len(recipients):
                await asyncio.sleep(1)
        
        return BulkSMSResult(
            total=len(recipients),
            successful=successful,
            failed=failed,
            results=results,
            total_cost=total_cost if total_cost > 0 else None,
            currency=currency,
        )
    
    async def get_delivery_status(self, message_id: str) -> SMSResult:
        """Get delivery status for a Twilio message.
        
        Args:
            message_id: Twilio Message SID
            
        Returns:
            SMSResult with current delivery status
        """
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(
                    f"{self.BASE_URL}/Accounts/{self._account_sid}/Messages/{message_id}.json",
                    auth=self._auth,
                )
                
                data = response.json()
                
                if response.status_code == 200:
                    status = self.STATUS_MAP.get(
                        data.get("status", ""),
                        SMSDeliveryStatus.UNKNOWN
                    )
                    
                    return SMSResult(
                        success=status in (SMSDeliveryStatus.DELIVERED, SMSDeliveryStatus.SENT),
                        message_id=data.get("sid"),
                        status=status,
                        recipient=data.get("to"),
                        cost=float(data.get("price", 0)) if data.get("price") else None,
                        currency=data.get("price_unit"),
                        segments=data.get("num_segments", 1),
                        message=data.get("status"),
                        raw_response=data,
                    )
                else:
                    return SMSResult(
                        success=False,
                        message_id=message_id,
                        status=SMSDeliveryStatus.UNKNOWN,
                        message=data.get("message", "Status check failed"),
                        error_code=str(data.get("code", "")),
                        raw_response=data,
                    )
        
        except Exception as e:
            logger.error(f"Twilio status check error: {e}")
            return SMSResult(
                success=False,
                message_id=message_id,
                status=SMSDeliveryStatus.UNKNOWN,
                message=str(e),
                error_code="STATUS_CHECK_ERROR",
            )
    
    async def get_account_balance(self) -> Tuple[float, str]:
        """Get Twilio account balance.
        
        Returns:
            Tuple of (balance, currency)
        """
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(
                    f"{self.BASE_URL}/Accounts/{self._account_sid}/Balance.json",
                    auth=self._auth,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return float(data.get("balance", 0)), data.get("currency", "USD")
                else:
                    raise Exception(f"Balance check failed: {response.status_code}")
        
        except Exception as e:
            logger.error(f"Twilio balance check error: {e}")
            raise
    
    def parse_webhook(self, payload: Dict[str, Any]) -> SMSResult:
        """Parse Twilio webhook payload for delivery status.
        
        Args:
            payload: Twilio webhook POST data
            
        Returns:
            SMSResult with delivery status
        """
        message_id = payload.get("MessageSid", payload.get("SmsSid"))
        status_str = payload.get("MessageStatus", payload.get("SmsStatus", ""))
        
        status = self.STATUS_MAP.get(status_str.lower(), SMSDeliveryStatus.UNKNOWN)
        
        return SMSResult(
            success=status in (SMSDeliveryStatus.DELIVERED, SMSDeliveryStatus.SENT),
            message_id=message_id,
            status=status,
            recipient=payload.get("To"),
            message=status_str,
            error_code=payload.get("ErrorCode"),
            raw_response=payload,
        )
