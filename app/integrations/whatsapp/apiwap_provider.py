"""APIWAP WhatsApp provider implementation.

APIWAP provides WhatsApp Business API integration with affordable rates
for African markets.

Documentation: https://api.apiwap.com/docs

Platform-managed credentials:
    api_key: APIWAP API key (managed at platform level)

How it works:
    1. Platform owner configures APIWAP API key in platform settings
    2. ISP providers subscribe to WhatsApp package (500 KES/month)
    3. When subscribed, WhatsApp is auto-enabled for their organization
    4. ISP providers can send WhatsApp messages using notification templates
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.core.logging import get_logger
from .base import (
    WhatsAppProviderInterface,
    WhatsAppProviderConfig,
    WhatsAppResult,
    BulkWhatsAppResult,
    WhatsAppDeliveryStatus,
)

logger = get_logger(__name__)


class APIWAPWhatsAppProvider(WhatsAppProviderInterface):
    """APIWAP WhatsApp provider implementation.

    Supports:
    - Single and bulk WhatsApp message sending
    - Text messages
    - Delivery status tracking (via webhooks)

    Platform-managed credentials:
        api_key: APIWAP API key

    Optional settings:
        webhook_url: URL for delivery status callbacks
    """

    BASE_URL = "https://api.apiwap.com/api/v1/whatsapp"

    # Map APIWAP status to our status enum
    STATUS_MAP = {
        "sent": WhatsAppDeliveryStatus.SENT,
        "delivered": WhatsAppDeliveryStatus.DELIVERED,
        "read": WhatsAppDeliveryStatus.READ,
        "failed": WhatsAppDeliveryStatus.FAILED,
        "pending": WhatsAppDeliveryStatus.QUEUED,
    }

    def _validate_config(self) -> None:
        """Validate APIWAP configuration."""
        credentials = self.config.credentials

        if not credentials.get("api_key"):
            raise ValueError("APIWAP api_key is required")

    @property
    def provider_name(self) -> str:
        return "APIWAP"

    @property
    def supports_delivery_reports(self) -> bool:
        return True

    @property
    def supports_bulk_messages(self) -> bool:
        return True  # Will implement via individual sends

    @property
    def _api_key(self) -> str:
        """Get APIWAP API key."""
        return self.config.credentials["api_key"]

    @property
    def _headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def send_message(
        self,
        to: str,
        message: str,
        message_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WhatsAppResult:
        """Send WhatsApp message via APIWAP.

        Args:
            to: Recipient phone number
            message: Message content
            message_type: Type of message (currently only 'text' supported)
            metadata: Optional metadata

        Returns:
            WhatsAppResult with send status
        """
        try:
            # Format phone number
            formatted_to = self.format_phone_number(to)

            # Build request payload
            payload = {
                "phoneNumber": formatted_to,
                "message": message,
                "type": message_type,
            }

            # Send request
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    f"{self.BASE_URL}/send-message",
                    json=payload,
                    headers=self._headers,
                )

                data = response.json()

                if response.status_code == 200 or response.status_code == 201:
                    # Successful send
                    message_id = data.get("messageId") or data.get("id")
                    status_str = data.get("status", "sent").lower()

                    return WhatsAppResult(
                        success=True,
                        message_id=message_id,
                        status=self.STATUS_MAP.get(status_str, WhatsAppDeliveryStatus.SENT),
                        recipient=formatted_to,
                        message=data.get("message", "Message sent successfully"),
                        raw_response=data,
                        sent_at=datetime.utcnow(),
                    )
                else:
                    # Error response
                    error_message = data.get("message") or data.get("error") or "Unknown error"

                    logger.error(
                        f"APIWAP WhatsApp send failed: {error_message}",
                        extra={"to": formatted_to, "error": data},
                    )

                    return WhatsAppResult(
                        success=False,
                        status=WhatsAppDeliveryStatus.FAILED,
                        recipient=formatted_to,
                        message=error_message,
                        error_code=str(response.status_code),
                        raw_response=data,
                    )

        except httpx.TimeoutException:
            logger.error(f"APIWAP WhatsApp timeout for {to}")
            return WhatsAppResult(
                success=False,
                status=WhatsAppDeliveryStatus.FAILED,
                recipient=to,
                message="Request timeout",
                error_code="TIMEOUT",
            )
        except Exception as e:
            logger.error(f"APIWAP WhatsApp error: {e}")
            return WhatsAppResult(
                success=False,
                status=WhatsAppDeliveryStatus.FAILED,
                recipient=to,
                message=str(e),
                error_code="INTERNAL_ERROR",
            )

    async def send_bulk_messages(
        self,
        recipients: List[str],
        message: str,
        message_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BulkWhatsAppResult:
        """Send bulk WhatsApp messages via APIWAP.

        Uses sequential sending for reliability.

        Args:
            recipients: List of recipient phone numbers
            message: Message content
            message_type: Type of message
            metadata: Optional metadata

        Returns:
            BulkWhatsAppResult with aggregated results
        """
        try:
            results = []
            successful = 0
            failed = 0
            total_cost = 0.0

            for recipient in recipients:
                result = await self.send_message(
                    to=recipient,
                    message=message,
                    message_type=message_type,
                    metadata=metadata,
                )
                results.append(result)

                if result.success:
                    successful += 1
                    if result.cost:
                        total_cost += result.cost
                else:
                    failed += 1

            return BulkWhatsAppResult(
                total=len(recipients),
                successful=successful,
                failed=failed,
                results=results,
                total_cost=total_cost if total_cost > 0 else None,
                currency="KES",  # APIWAP uses KES for Kenya
            )

        except Exception as e:
            logger.error(f"APIWAP bulk WhatsApp error: {e}")
            # Fall back to parent implementation
            return await super().send_bulk_messages(recipients, message, message_type, metadata)

    async def get_delivery_status(self, message_id: str) -> WhatsAppResult:
        """Get delivery status for an APIWAP message.

        Note: APIWAP uses callbacks for delivery reports.
        This method checks if the message exists and its last known status.

        Args:
            message_id: APIWAP message ID

        Returns:
            WhatsAppResult with current delivery status
        """
        # APIWAP primarily uses webhook callbacks for delivery status
        # For now, return unknown status - implement callback handling separately
        logger.warning(
            f"APIWAP delivery status check not fully implemented. "
            f"Use webhook callbacks instead. Message ID: {message_id}"
        )

        return WhatsAppResult(
            success=False,
            message_id=message_id,
            status=WhatsAppDeliveryStatus.UNKNOWN,
            message="Use delivery callbacks for status updates",
        )

    def parse_delivery_callback(self, payload: Dict[str, Any]) -> WhatsAppResult:
        """Parse APIWAP delivery callback.

        Args:
            payload: APIWAP callback data

        Returns:
            WhatsAppResult with delivery status
        """
        message_id = payload.get("messageId") or payload.get("id")
        status_str = payload.get("status", "").lower()

        status = self.STATUS_MAP.get(status_str, WhatsAppDeliveryStatus.UNKNOWN)

        return WhatsAppResult(
            success=status in [WhatsAppDeliveryStatus.DELIVERED, WhatsAppDeliveryStatus.READ],
            message_id=message_id,
            status=status,
            recipient=payload.get("phoneNumber"),
            message=payload.get("message", status_str),
            raw_response=payload,
        )
