"""Notification service."""

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
        """Send email notification."""
        try:
            if settings.email_provider == "smtp":
                return await self._send_smtp_email(to_email, subject, body, is_html)
            elif settings.email_provider == "sendgrid":
                return await self._send_sendgrid_email(to_email, subject, body, is_html)
            elif settings.email_provider == "ses":
                return await self._send_ses_email(to_email, subject, body, is_html)
            else:
                logger.warning(f"Unknown email provider: {settings.email_provider}")
                return {"status": "error", "message": "Email provider not configured"}
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return {"status": "error", "message": str(e)}

    async def send_sms_notification(
        self,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """Send SMS notification using platform gateway credentials."""
        try:
            from sqlalchemy import and_
            from app.models.sms_credit import SMSGatewayConfig, SMSProviderType, SMSGatewayStatus

            # Get primary active platform-level gateway
            result = await self.db.execute(
                select(SMSGatewayConfig).where(
                    and_(
                        SMSGatewayConfig.organization_id.is_(None),
                        SMSGatewayConfig.is_active == True,
                        SMSGatewayConfig.is_primary == True,
                        SMSGatewayConfig.status == SMSGatewayStatus.ACTIVE,
                    )
                )
            )
            gateway = result.scalar_one_or_none()

            if not gateway:
                logger.warning("No primary active SMS gateway configured at platform level")
                return {"status": "error", "message": "SMS gateway not configured"}

            if gateway.provider_type == SMSProviderType.AFRICASTALKING:
                return await self._send_africas_talking_sms(to_phone, message)
            elif gateway.provider_type == SMSProviderType.TWILIO:
                return await self._send_twilio_sms(to_phone, message)
            else:
                logger.warning(f"Unknown SMS provider type: {gateway.provider_type}")
                return {"status": "error", "message": "Unknown SMS provider"}
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            return {"status": "error", "message": str(e)}

    async def get_pending_notifications(self) -> List[Notification]:
        """Get all pending notifications."""
        result = await self.db.execute(
            select(Notification).where(Notification.status == NotificationStatus.PENDING)
        )
        return result.scalars().all()

    async def _send_smtp_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> Dict[str, Any]:
        """Send email via SMTP."""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart()
            msg['From'] = settings.smtp_username
            msg['To'] = to_email
            msg['Subject'] = subject

            if is_html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return {"status": "success", "message": "Email sent successfully"}
        except Exception as e:
            logger.error(f"SMTP email sending failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _send_sendgrid_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> Dict[str, Any]:
        """Send email via SendGrid."""
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail

            sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
            
            message = Mail(
                from_email=settings.smtp_username,
                to_emails=to_email,
                subject=subject,
                plain_text_content=body if not is_html else None,
                html_content=body if is_html else None
            )

            response = sg.send(message)
            
            if response.status_code == 202:
                logger.info(f"SendGrid email sent successfully to {to_email}")
                return {"status": "success", "message": "Email sent successfully"}
            else:
                logger.error(f"SendGrid email failed: {response.status_code}")
                return {"status": "error", "message": f"SendGrid error: {response.status_code}"}
        except Exception as e:
            logger.error(f"SendGrid email sending failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _send_ses_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> Dict[str, Any]:
        """Send email via AWS SES."""
        try:
            import boto3
            from botocore.exceptions import ClientError

            ses_client = boto3.client(
                'ses',
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key
            )

            response = ses_client.send_email(
                Source=settings.smtp_username,
                Destination={'ToAddresses': [to_email]},
                Message={
                    'Subject': {'Data': subject},
                    'Body': {
                        'Text': {'Data': body} if not is_html else None,
                        'Html': {'Data': body} if is_html else None
                    }
                }
            )

            logger.info(f"SES email sent successfully to {to_email}")
            return {"status": "success", "message": "Email sent successfully", "message_id": response['MessageId']}
        except ClientError as e:
            logger.error(f"SES email sending failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _send_africas_talking_sms(
        self,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """Send SMS via Africa's Talking using platform gateway credentials."""
        try:
            import json
            from sqlalchemy import and_
            from app.models.sms_credit import SMSGatewayConfig, SMSProviderType, SMSGatewayStatus
            from app.integrations.payment_gateways import PaymentGatewayFactory

            # Get platform-level AT gateway (organization_id IS NULL)
            result = await self.db.execute(
                select(SMSGatewayConfig).where(
                    and_(
                        SMSGatewayConfig.organization_id.is_(None),
                        SMSGatewayConfig.provider_type == SMSProviderType.AFRICASTALKING,
                        SMSGatewayConfig.is_active == True,
                        SMSGatewayConfig.status == SMSGatewayStatus.ACTIVE,
                    )
                )
            )
            gateway = result.scalar_one_or_none()

            if not gateway:
                logger.error("No active Africa's Talking gateway configured at platform level")
                return {"status": "error", "message": "SMS gateway not configured"}

            # Decrypt credentials JSON (same approach as sms_gateways.py)
            encryption_key = getattr(settings, 'encryption_key', None)
            if encryption_key:
                credentials = PaymentGatewayFactory._decrypt_credentials(
                    gateway.credentials, encryption_key
                )
            else:
                # Development mode - try plain JSON
                try:
                    credentials = json.loads(gateway.credentials) if gateway.credentials else {}
                except json.JSONDecodeError:
                    credentials = {}

            username = credentials.get("username") or credentials.get("api_username")
            api_key = credentials.get("api_key")

            if not api_key or not username:
                logger.error(f"Africa's Talking credentials not properly configured. Keys found: {list(credentials.keys())}")
                return {"status": "error", "message": "SMS gateway credentials missing"}

            # Ensure phone number has + prefix for Africa's Talking
            formatted_phone = to_phone if to_phone.startswith('+') else f'+{to_phone}'

            import africastalking
            africastalking.initialize(username=username, api_key=api_key)

            sms = africastalking.SMS
            response = sms.send(message, [formatted_phone])

            if response['SMSMessageData']['Recipients'][0]['statusCode'] == 101:
                logger.info(f"Africa's Talking SMS sent successfully to {to_phone}")
                return {"status": "success", "message": "SMS sent successfully"}
            else:
                logger.error(f"Africa's Talking SMS failed: {response}")
                return {"status": "error", "message": "SMS sending failed"}
        except Exception as e:
            logger.error(f"Africa's Talking SMS sending failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _send_twilio_sms(
        self,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """Send SMS via Twilio."""
        try:
            from twilio.rest import Client

            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

            message_obj = client.messages.create(
                body=message,
                from_=settings.twilio_phone_number,
                to=to_phone
            )

            logger.info(f"Twilio SMS sent successfully to {to_phone}")
            return {"status": "success", "message": "SMS sent successfully", "message_id": message_obj.sid}
        except Exception as e:
            logger.error(f"Twilio SMS sending failed: {e}")
            return {"status": "error", "message": str(e)}
