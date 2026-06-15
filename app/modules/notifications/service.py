"""Notification service.

DELIVERY of SMS / WhatsApp / email is centralized on the notifications-api
(see app.services.notifications_client). isp-billing no longer ships local
SMS/WhatsApp/email providers — this service only persists Notification rows and
routes the actual send to the central notifications-api. SMS-credit and
WhatsApp-subscription BILLING stay local (see SMSSendingService / models).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.notification import Notification, NotificationType, NotificationStatus, NotificationPriority
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class NotificationService:
    """Notification service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def send_verification_email(self, user: User, token: str) -> None:
        """Send email verification email."""
        # Create notification record for email service to process
        notification = Notification(
            user_id=user.id,
            notification_type=NotificationType.EMAIL,
            title="Verify Your Email",
            message=f"Please click the link to verify your email: /verify?token={token}",
            recipient=user.email,
            status=NotificationStatus.PENDING,
        )

        self.db.add(notification)
        await self.db.commit()

    async def send_password_reset_email(self, user: User, token: str) -> None:
        """Send password reset email."""
        notification = Notification(
            user_id=user.id,
            notification_type=NotificationType.EMAIL,
            title="Password Reset Request",
            message=f"Click the link to reset your password: /reset-password?token={token}",
            recipient=user.email,
            status=NotificationStatus.PENDING,
        )

        self.db.add(notification)
        await self.db.commit()

    async def send_sms(self, user: User, message: str) -> None:
        """Send SMS notification."""
        if not user.phone:
            return

        notification = Notification(
            user_id=user.id,
            notification_type=NotificationType.SMS,
            title="SMS Notification",
            message=message,
            recipient=user.phone,
            status=NotificationStatus.PENDING,
        )

        self.db.add(notification)
        await self.db.commit()

    async def send_in_app_notification(
        self, user: User, title: str, message: str
    ) -> None:
        """Send in-app notification."""
        notification = Notification(
            user_id=user.id,
            notification_type=NotificationType.IN_APP,
            title=title,
            message=message,
            recipient=user.username,
            status=NotificationStatus.PENDING,
        )

        self.db.add(notification)
        await self.db.commit()

    async def get_user_notifications(
        self, user_id: int, limit: int = 50
    ) -> List[Notification]:
        """Get user notifications."""
        result = await self.db.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def mark_notification_as_read(self, notification_id: int, user_id: int) -> bool:
        """Mark notification as read."""
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id
            )
        )
        notification = result.scalar_one_or_none()

        if not notification:
            return False

        notification.status = NotificationStatus.READ
        notification.read_at = datetime.utcnow()
        await self.db.commit()
        return True

    async def create_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: str = "info",
        priority: str = "medium",
        data: Optional[Dict[str, Any]] = None
    ) -> Notification:
        """Create a notification."""
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            data=data,
            status=NotificationStatus.PENDING,
        )

        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)

        return notification

    async def send_email_notification(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> Dict[str, Any]:
        """Send an email via the central notifications-api.

        Email delivery is owned by notifications-api; there is no local SMTP /
        SendGrid / SES path anymore. Returns an error dict (no raise) when the
        central client is unconfigured or the call fails, so callers behave the
        same as before (best-effort delivery).
        """
        try:
            from app.services.notifications_client import get_notifications_client

            client = get_notifications_client()
            if not client.is_configured:
                logger.warning(
                    "notifications-api not configured; email to %s not delivered",
                    to_email,
                )
                return {"status": "error", "message": "notifications-api not configured"}

            resp = await client.send(
                channel="email",
                template="ispbilling/raw_message",
                to=[to_email],
                data={"subject": subject, "body": body, "is_html": is_html},
                metadata={"subject": subject},
            )
            logger.info("Email delivered via central notifications-api to %s", to_email)
            return {
                "status": "success",
                "message": "Email sent via notifications-api",
                "provider": "notifications-api",
                "raw": resp,
            }
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return {"status": "error", "message": str(e)}

    async def send_sms_notification(
        self,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """Send an SMS via the central notifications-api.

        DELIVERY is owned by notifications-api (Africa's Talking etc.); there is
        no local SMS provider anymore. This path carries no SMS-credit accounting
        (that lives in SMSSendingService). SMS is never plan-blocked. Returns an
        error dict (no raise) when central is unconfigured / fails.
        """
        try:
            from app.services.notifications_client import get_notifications_client

            client = get_notifications_client()
            if not client.is_configured:
                logger.warning(
                    "notifications-api not configured; SMS to %s not delivered",
                    to_phone,
                )
                return {"status": "error", "message": "notifications-api not configured"}

            resp = await client.send(
                channel="sms",
                template="ispbilling/raw_message",
                to=[to_phone],
                data={"body": message},
            )
            logger.info("SMS delivered via central notifications-api to %s", to_phone)
            return {
                "status": "success",
                "message": "SMS sent via notifications-api",
                "provider": "notifications-api",
                "raw": resp,
            }
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            return {"status": "error", "message": str(e)}

    async def get_pending_notifications(self) -> List[Notification]:
        """Get all pending notifications."""
        result = await self.db.execute(
            select(Notification).where(Notification.status == NotificationStatus.PENDING)
        )
        return result.scalars().all()
