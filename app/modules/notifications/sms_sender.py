"""SMS sending service — credit accounting + central delivery.

DELIVERY is centralized on the notifications-api (Africa's Talking etc. live
there now). isp-billing no longer ships local SMS providers. This service keeps
the LOCAL SMS-credit accounting (balance checks, cost calc, transaction
recording) and performs the actual wire send via the central notifications-api
(app.services.notifications_client). Per notification policy, SMS is never
plan-blocked.

Usage:
    service = SMSSendingService(db)
    result = await service.send_sms(
        to="+254712345678",
        message="Your subscription expires tomorrow",
        account_id=1,  # SMS credit account
        user_id=1,     # For audit
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.notification import Notification, NotificationStatus
from app.models.sms_credit import (
    SMSCreditAccount,
    SMSTransaction,
    SMSProviderType,
    SMSTransactionStatus,
    SMSTransactionType,
)

logger = get_logger(__name__)


class SMSDeliveryStatus(str, Enum):
    """SMS delivery status enumeration."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNDELIVERED = "undelivered"
    UNKNOWN = "unknown"


@dataclass
class SMSResult:
    """Result of an SMS send operation (delivery via notifications-api)."""

    success: bool
    message_id: Optional[str] = None
    status: SMSDeliveryStatus = SMSDeliveryStatus.UNKNOWN
    recipient: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    segments: int = 1
    message: Optional[str] = None
    error_code: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    sent_at: Optional[datetime] = None


def calculate_segments(message: str) -> int:
    """Estimate the number of SMS segments for a message (GSM-7 approximation).

    Single-segment: 160 chars; concatenated parts: 153 chars each. This mirrors
    the previous provider behaviour closely enough for credit estimation.
    """
    if not message:
        return 1
    length = len(message)
    if length <= 160:
        return 1
    return -(-length // 153)  # ceil division


class SMSSendingService:
    """Send SMS through the central notifications-api with local credit accounting."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def _get_default_account(self) -> SMSCreditAccount:
        """Get the default SMS credit account (or any active one)."""
        result = await self.db.execute(
            select(SMSCreditAccount).where(
                and_(
                    SMSCreditAccount.is_default == True,
                    SMSCreditAccount.is_active == True,
                )
            )
        )
        account = result.scalar_one_or_none()

        if not account:
            result = await self.db.execute(
                select(SMSCreditAccount).where(SMSCreditAccount.is_active == True)
            )
            account = result.scalar_one_or_none()

        if not account:
            raise ValueError("No active SMS credit account configured")

        return account

    async def _get_account(self, account_id: int) -> SMSCreditAccount:
        result = await self.db.execute(
            select(SMSCreditAccount).where(
                and_(
                    SMSCreditAccount.id == account_id,
                    SMSCreditAccount.is_active == True,
                )
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"SMS credit account {account_id} not found or inactive")
        return account

    async def _deliver(
        self,
        to: str,
        message: str,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SMSResult:
        """Perform the wire send via the central notifications-api.

        SMS-credit billing (balance checks, cost calc, transaction recording)
        stays in the caller; this just performs delivery. SMS is never
        plan-blocked.
        """
        from app.services.notifications_client import get_notifications_client

        segments = calculate_segments(message)
        client = get_notifications_client()
        if not client.is_configured:
            self.logger.error("notifications-api not configured; SMS to %s not delivered", to)
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                segments=segments,
                message="notifications-api not configured",
                error_code="NOTIFICATIONS_NOT_CONFIGURED",
            )

        try:
            resp = await client.send(
                channel="sms",
                template="ispbilling/raw_message",
                to=[to],
                data={"body": message},
                metadata=({"sender_id": sender_id} if sender_id else None),
            )
            self.logger.info(
                "SMS delivered via central notifications-api to %s (%s)",
                to,
                (resp or {}).get("requestId") or (resp or {}).get("status"),
            )
            return SMSResult(
                success=True,
                status=SMSDeliveryStatus.SENT,
                recipient=to,
                segments=segments,
                message="accepted by notifications-api",
                raw_response=resp or {},
            )
        except Exception as exc:
            self.logger.error("central notifications SMS delivery failed: %s", exc)
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                segments=segments,
                message=str(exc),
                error_code="SEND_ERROR",
            )

    async def send_sms(
        self,
        to: str,
        message: str,
        account_id: Optional[int] = None,
        user_id: Optional[int] = None,
        notification_id: Optional[int] = None,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SMSResult:
        """Send a single SMS, with local credit accounting + central delivery."""
        account = await self._get_account(account_id) if account_id else await self._get_default_account()

        # Check balance
        if account.current_balance <= 0:
            self.logger.error(f"SMS account {account.account_code} has no credit")
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message="Insufficient SMS credit",
                error_code="INSUFFICIENT_CREDIT",
            )

        # Cost estimate
        segments = calculate_segments(message)
        estimated_cost = Decimal(str(segments)) * account.average_cost_per_sms

        if estimated_cost > 0 and account.current_balance < estimated_cost:
            self.logger.warning(
                f"SMS account {account.account_code} may have insufficient credit. "
                f"Balance: {account.current_balance}, Estimated: {estimated_cost}"
            )

        balance_before = account.current_balance

        from app.modules.notifications.sms import SMSCreditService
        credit_service = SMSCreditService(self.db)
        transaction_id = credit_service._generate_transaction_id(SMSTransactionType.USAGE)

        try:
            result = await self._deliver(
                to=to,
                message=message,
                sender_id=sender_id,
                metadata=metadata,
            )

            actual_cost = Decimal(str(result.cost)) if result.cost else estimated_cost

            transaction = SMSTransaction(
                transaction_id=transaction_id,
                account_id=account.id,
                transaction_type=SMSTransactionType.USAGE,
                status=SMSTransactionStatus.COMPLETED if result.success else SMSTransactionStatus.FAILED,
                amount=actual_cost,
                currency=result.currency or account.currency,
                recipient_phone=to,
                message_content=message[:500] if message else None,
                message_length=len(message) if message else 0,
                sms_count=result.segments or segments,
                provider_transaction_id=result.message_id,
                provider_response=result.raw_response,
                delivery_status=result.status.value,
                user_id=user_id,
                notification_id=notification_id,
                balance_before=balance_before,
                balance_after=balance_before - actual_cost if result.success else balance_before,
                processed_at=datetime.utcnow(),
                error_message=result.message if not result.success else None,
            )

            self.db.add(transaction)

            if result.success:
                account.update_balance(actual_cost, SMSTransactionType.USAGE)
                account.total_messages_sent += 1
                account.total_amount_spent += actual_cost
                account.last_successful_send = datetime.utcnow()
                account.consecutive_failures = 0

                if account.total_messages_sent > 0:
                    account.average_cost_per_sms = (
                        account.total_amount_spent / account.total_messages_sent
                    )
            else:
                account.consecutive_failures += 1

            if notification_id:
                await self._update_notification_status(
                    notification_id,
                    result.success,
                    result.message_id,
                    result.message,
                )

            await self.db.commit()
            return result

        except Exception as e:
            self.logger.error(f"SMS send error: {e}")
            await self.db.rollback()
            return SMSResult(
                success=False,
                status=SMSDeliveryStatus.FAILED,
                recipient=to,
                message=str(e),
                error_code="SEND_ERROR",
            )

    async def send_bulk_sms(
        self,
        recipients: List[str],
        message: str,
        account_id: Optional[int] = None,
        user_id: Optional[int] = None,
        sender_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send SMS to multiple recipients (each delivered via notifications-api)."""
        account = await self._get_account(account_id) if account_id else await self._get_default_account()

        segments = calculate_segments(message)
        estimated_total = Decimal(str(len(recipients) * segments)) * account.average_cost_per_sms

        if account.current_balance < estimated_total:
            self.logger.warning(
                f"SMS account {account.account_code} may have insufficient credit for bulk. "
                f"Balance: {account.current_balance}, Estimated: {estimated_total}"
            )

        successful = 0
        failed = 0
        total_cost = Decimal("0")

        for recipient in recipients:
            result = await self._deliver(
                to=recipient,
                message=message,
                sender_id=sender_id,
                metadata=metadata,
            )
            actual_cost = Decimal(str(result.cost)) if result.cost else account.average_cost_per_sms

            transaction = SMSTransaction(
                transaction_id=f"BULK-{result.message_id}" if result.message_id else f"BULK-{datetime.utcnow().timestamp()}",
                account_id=account.id,
                transaction_type=SMSTransactionType.USAGE,
                status=SMSTransactionStatus.COMPLETED if result.success else SMSTransactionStatus.FAILED,
                amount=actual_cost,
                currency=result.currency or account.currency,
                recipient_phone=result.recipient,
                message_content=message[:500] if message else None,
                message_length=len(message) if message else 0,
                sms_count=result.segments,
                provider_transaction_id=result.message_id,
                delivery_status=result.status.value,
                user_id=user_id,
                balance_before=account.current_balance,
                balance_after=account.current_balance - actual_cost if result.success else account.current_balance,
                processed_at=datetime.utcnow(),
                error_message=result.message if not result.success else None,
            )
            self.db.add(transaction)

            if result.success:
                account.update_balance(actual_cost, SMSTransactionType.USAGE)
                account.total_messages_sent += 1
                total_cost += actual_cost
                successful += 1
            else:
                failed += 1

        if total_cost:
            account.total_amount_spent += total_cost
        if account.total_messages_sent > 0:
            account.average_cost_per_sms = account.total_amount_spent / account.total_messages_sent
        account.last_successful_send = datetime.utcnow()

        await self.db.commit()

        return {
            "total": len(recipients),
            "successful": successful,
            "failed": failed,
            "total_cost": float(total_cost) if total_cost else None,
            "currency": account.currency,
        }

    async def _update_notification_status(
        self,
        notification_id: int,
        success: bool,
        external_id: Optional[str],
        error_message: Optional[str],
    ) -> None:
        """Update notification status after SMS send."""
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()

        if notification:
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
                notification.external_id = external_id
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = error_message
                notification.retry_count += 1
