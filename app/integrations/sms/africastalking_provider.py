"""Africa's Talking SMS provider implementation.

Africa's Talking provides SMS coverage across African markets with local numbers
and competitive rates.

Documentation: https://developers.africastalking.com/docs/sms/overview

Environment variables required:
    AT_USERNAME: Africa's Talking username
    AT_API_KEY: Africa's Talking API key
    AT_SENDER_ID: Optional alphanumeric sender ID
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


class AfricasTalkingSMSProvider(SMSProviderInterface):
    """Africa's Talking SMS provider implementation.
    
    Supports:
    - Single and bulk SMS sending (native bulk support)
    - Delivery status tracking
    - Alphanumeric sender IDs
    - Premium SMS
    - Shortcodes
    
    Required credentials:
        username: Africa's Talking username
        api_key: Africa's Talking API key
        
    Optional settings:
        sender_id: Alphanumeric sender ID (requires approval)
        shortcode: Premium SMS shortcode
        keyword: Premium SMS keyword
        is_sandbox: Use sandbox environment (default: False)
    """
    
    BASE_URL = "https://api.africastalking.com/version1"
    SANDBOX_URL = "https://api.sandbox.africastalking.com/version1"
    
    # Map Africa's Talking status to our status enum
    STATUS_MAP = {
        "success": SMSDeliveryStatus.SENT,
        "sent": SMSDeliveryStatus.SENT,
        "submitted": SMSDeliveryStatus.QUEUED,
        "buffered": SMSDeliveryStatus.QUEUED,
        "delivered": SMSDeliveryStatus.DELIVERED,
        "failed": SMSDeliveryStatus.FAILED,
        "rejected": SMSDeliveryStatus.FAILED,
    }
    
    def _validate_config(self) -> None:
        """Validate Africa's Talking configuration."""
        credentials = self.config.credentials
        
        if not credentials.get("username"):
            raise ValueError("Africa's Talking username is required")
        if not credentials.get("api_key"):
            raise ValueError("Africa's Talking api_key is required")
    
    @property
    def provider_name(self) -> str:
        return "Africa's Talking"
    
    @property
    def supports_delivery_reports(self) -> bool:
        return True
    
    @property
    def supports_bulk_sms(self) -> bool:
        return True  # Native bulk SMS support
    
    @property
    def _username(self) -> str:
        """Get Africa's Talking username."""
        return self.config.credentials["username"]
    
    @property
    def _api_key(self) -> str:
        """Get Africa's Talking API key."""
        return self.config.credentials["api_key"]
    
    @property
    def _sender_id(self) -> Optional[str]:
        """Get sender ID."""
        return self.config.credentials.get("sender_id")
    
    @property
    def _is_sandbox(self) -> bool:
        """Check if using sandbox environment."""
        return self.config.credentials.get("is_sandbox", False)
    
    @property
    def _base_url(self) -> str:
        """Get base URL based on environment."""
        return self.SANDBOX_URL if self._is_sandbox else self.BASE_URL
    
    @property
    def _headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "apiKey": self._api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
    
    async def send_sms(
        self,
        to: str,
        message: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SMSResult:
        """Send SMS via Africa's Talking.
        
        Args:
            to: Recipient phone number
            message: SMS message content
            sender_id: Optional sender ID override
            metadata: Optional metadata
            
        Returns:
            SMSResult with send status
        """
        try:
            # Format phone number
            formatted_to = self.format_phone_number(to)
            
            # Build request payload
            payload = {
                "username": self._username,
                "to": formatted_to,
                "message": message,
            }
            
            # Set sender ID
            final_sender = sender_id or self._sender_id
            if final_sender:
                payload["from"] = final_sender
            
            # Send request
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/messaging",
                    data=payload,
                    headers=self._headers,
                )
                
                data = response.json()
                
                if response.status_code == 201 and data.get("SMSMessageData"):
                    sms_data = data["SMSMessageData"]
                    recipients = sms_data.get("Recipients", [])
                    
                    if recipients:
                        recipient = recipients[0]
                        status_code = recipient.get("statusCode", 0)
                        
                        # Status codes: 100 = Sent, 101 = Sent to network
                        success = status_code in (100, 101, 102)
                        
                        return SMSResult(
                            success=success,
                            message_id=recipient.get("messageId"),
                            status=SMSDeliveryStatus.SENT if success else SMSDeliveryStatus.FAILED,
                            recipient=recipient.get("number"),
                            cost=float(recipient.get("cost", "0").replace("KES ", "").replace("USD ", "")),
                            currency="KES" if "KES" in recipient.get("cost", "") else "USD",
                            segments=int(recipient.get("number", 1)) if recipient.get("number") else 1,
                            message=recipient.get("status"),
                            raw_response=data,
                            sent_at=datetime.utcnow(),
                        )
                    
                    # No recipients in response
                    message_text = sms_data.get("Message", "Unknown error")
                    return SMSResult(
                        success=False,
                        status=SMSDeliveryStatus.FAILED,
                        recipient=formatted_to,
                        message=message_text,
                        raw_response=data,
                    )
                else:
                    # Error response
                    error_message = data.get("message", data.get("SMSMessageData", {}).get("Message", "Unknown error"))
                    
                    logger.error(
                        f"Africa's Talking SMS failed: {error_message}",
                        extra={"to": formatted_to, "error": data},
                    )
                    
                    return SMSResult(
                        success=False,
                        status=SMSDeliveryStatus.FAILED,
                        recipient=formatted_to,
                        message=error_message,
                        raw_response=data,
                    )
        
        except httpx.TimeoutException:
            logger.error(f"Africa's Talking SMS timeout for {to}")
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message="Request timeout",
                error_code="TIMEOUT",
            )
        except Exception as e:
            logger.error(f"Africa's Talking SMS error: {e}")
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
        """Send bulk SMS via Africa's Talking.
        
        Uses native bulk SMS support for efficiency.
        
        Args:
            recipients: List of recipient phone numbers
            message: SMS message content
            sender_id: Optional sender ID override
            metadata: Optional metadata
            
        Returns:
            BulkSMSResult with aggregated results
        """
        try:
            # Format phone numbers
            formatted_recipients = [self.format_phone_number(r) for r in recipients]
            
            # Build request payload - AT supports comma-separated recipients
            payload = {
                "username": self._username,
                "to": ",".join(formatted_recipients),
                "message": message,
            }
            
            final_sender = sender_id or self._sender_id
            if final_sender:
                payload["from"] = final_sender
            
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/messaging",
                    data=payload,
                    headers=self._headers,
                )
                
                data = response.json()
                
                results = []
                successful = 0
                failed = 0
                total_cost = 0.0
                currency = None
                
                if response.status_code == 201 and data.get("SMSMessageData"):
                    sms_data = data["SMSMessageData"]
                    recipients_data = sms_data.get("Recipients", [])
                    
                    for recipient in recipients_data:
                        status_code = recipient.get("statusCode", 0)
                        success = status_code in (100, 101, 102)
                        
                        cost_str = recipient.get("cost", "0")
                        cost = float(cost_str.replace("KES ", "").replace("USD ", "").strip() or 0)
                        
                        if "KES" in cost_str:
                            currency = "KES"
                        elif "USD" in cost_str:
                            currency = "USD"
                        
                        result = SMSResult(
                            success=success,
                            message_id=recipient.get("messageId"),
                            status=SMSDeliveryStatus.SENT if success else SMSDeliveryStatus.FAILED,
                            recipient=recipient.get("number"),
                            cost=cost,
                            currency=currency,
                            message=recipient.get("status"),
                            raw_response=recipient,
                            sent_at=datetime.utcnow(),
                        )
                        
                        results.append(result)
                        
                        if success:
                            successful += 1
                            total_cost += cost
                        else:
                            failed += 1
                
                return BulkSMSResult(
                    total=len(recipients),
                    successful=successful,
                    failed=failed,
                    results=results,
                    total_cost=total_cost if total_cost > 0 else None,
                    currency=currency,
                )
        
        except Exception as e:
            logger.error(f"Africa's Talking bulk SMS error: {e}")
            # Fall back to individual sending
            return await super().send_bulk_sms(recipients, message, sender_id, metadata)
    
    async def get_delivery_status(self, message_id: str) -> SMSResult:
        """Get delivery status for an Africa's Talking message.
        
        Note: Africa's Talking uses callbacks for delivery reports.
        This method checks if the message exists and its last known status.
        
        Args:
            message_id: Africa's Talking message ID
            
        Returns:
            SMSResult with current delivery status
        """
        # Africa's Talking primarily uses webhook callbacks for delivery status
        # For now, return unknown status - implement callback handling separately
        logger.warning(
            f"Africa's Talking delivery status check not fully implemented. "
            f"Use webhook callbacks instead. Message ID: {message_id}"
        )
        
        return SMSResult(
            success=False,
            message_id=message_id,
            status=SMSDeliveryStatus.UNKNOWN,
            message="Use delivery callbacks for status updates",
        )
    
    async def get_account_balance(self) -> Tuple[float, str]:
        """Get Africa's Talking account balance.
        
        Returns:
            Tuple of (balance, currency)
        """
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(
                    f"{self._base_url}/user?username={self._username}",
                    headers=self._headers,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    user_data = data.get("UserData", {})
                    balance_str = user_data.get("balance", "0")
                    
                    # Parse balance string like "KES 1500.00" or "USD 100.00"
                    parts = balance_str.split()
                    if len(parts) == 2:
                        currency = parts[0]
                        balance = float(parts[1])
                    else:
                        currency = "KES"
                        balance = float(balance_str.replace("KES", "").replace("USD", "").strip() or 0)
                    
                    return balance, currency
                else:
                    raise Exception(f"Balance check failed: {response.status_code}")
        
        except Exception as e:
            logger.error(f"Africa's Talking balance check error: {e}")
            raise
    
    def parse_delivery_callback(self, payload: Dict[str, Any]) -> SMSResult:
        """Parse Africa's Talking delivery callback.
        
        Args:
            payload: Africa's Talking callback data
            
        Returns:
            SMSResult with delivery status
        """
        message_id = payload.get("id")
        status_str = payload.get("status", "").lower()
        
        status = self.STATUS_MAP.get(status_str, SMSDeliveryStatus.UNKNOWN)
        
        return SMSResult(
            success=status == SMSDeliveryStatus.DELIVERED,
            message_id=message_id,
            status=status,
            recipient=payload.get("phoneNumber"),
            message=payload.get("failureReason", status_str),
            raw_response=payload,
        )
