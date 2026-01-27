"""Notification-related Celery tasks."""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from celery import current_task
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.notification import Notification, NotificationType, NotificationStatus
from app.models.billing import Invoice, InvoiceStatus
from app.models.user import User
from app.modules.notifications import NotificationService

logger = get_logger(__name__)


@celery_app.task(bind=True)
def send_notification(
    self, 
    user_id: int, 
    notification_type: str, 
    title: str, 
    message: str,
    recipient: str
):
    """Send a notification to a user."""
    logger.info(f"Sending {notification_type} notification to user {user_id}")
    
    try:
        async def _send_notification():
            async with AsyncSessionLocal() as db:
                notification_service = NotificationService(db)
                
                # Create notification record
                notification = await notification_service.create_notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    priority="medium"
                )
                
                # Send via appropriate channel based on recipient type
                if "@" in recipient:  # Email
                    await notification_service.send_email_notification(
                        to_email=recipient,
                        subject=title,
                        body=message
                    )
                elif recipient.isdigit() or recipient.startswith("+"):  # SMS
                    await notification_service.send_sms_notification(
                        to_phone=recipient,
                        message=message
                    )
                
                return notification
        
        import asyncio
        notification = asyncio.run(_send_notification())
        
        logger.info(f"Notification sent to user {user_id}")
        return {
            "status": "success", 
            "user_id": user_id, 
            "notification_type": notification_type,
            "notification_id": notification.id
        }
    except Exception as exc:
        logger.error(f"Notification sending failed for user {user_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_email_notification(self, user_id: int, subject: str, body: str, to_email: str):
    """Send email notification to user."""
    logger.info(f"Sending email notification to user {user_id}")
    
    try:
        async def _send_email():
            async with AsyncSessionLocal() as db:
                notification_service = NotificationService(db)
                
                # Send email
                result = await notification_service.send_email_notification(
                    to_email=to_email,
                    subject=subject,
                    body=body
                )
                
                # Create notification record
                await notification_service.create_notification(
                    user_id=user_id,
                    title=subject,
                    message=body,
                    notification_type="email",
                    priority="medium"
                )
                
                return result
        
        import asyncio
        result = asyncio.run(_send_email())
        
        logger.info(f"Email notification sent to user {user_id}")
        return {
            "status": "success", 
            "user_id": user_id, 
            "email": to_email,
            "result": result
        }
    except Exception as exc:
        logger.error(f"Email notification failed for user {user_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_sms_notification(self, user_id: int, message: str, to_phone: str):
    """Send SMS notification to user."""
    logger.info(f"Sending SMS notification to user {user_id}")
    
    try:
        async def _send_sms():
            async with AsyncSessionLocal() as db:
                notification_service = NotificationService(db)
                
                # Send SMS
                result = await notification_service.send_sms_notification(
                    to_phone=to_phone,
                    message=message
                )
                
                # Create notification record
                await notification_service.create_notification(
                    user_id=user_id,
                    title="SMS Notification",
                    message=message,
                    notification_type="sms",
                    priority="high"
                )
                
                return result
        
        import asyncio
        result = asyncio.run(_send_sms())
        
        logger.info(f"SMS notification sent to user {user_id}")
        return {
            "status": "success", 
            "user_id": user_id, 
            "phone": to_phone,
            "result": result
        }
    except Exception as exc:
        logger.error(f"SMS notification failed for user {user_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_payment_reminders(self):
    """Send payment reminders for overdue invoices."""
    logger.info("Sending payment reminders")
    
    try:
        async def _send_reminders():
            async with AsyncSessionLocal() as db:
                from app.modules.billing import BillingService
                billing_service = BillingService(db)
                notification_service = NotificationService(db)
                
                # Get overdue invoices
                overdue_invoices = await billing_service.get_overdue_invoices()
                reminders_sent = 0
                
                for invoice in overdue_invoices:
                    try:
                        # Send reminder notification
                        await notification_service.create_notification(
                            user_id=invoice.user_id,
                            title="Payment Overdue",
                            message=f"Your invoice {invoice.invoice_number} is overdue. Amount: ${invoice.total_amount}",
                            notification_type="billing",
                            priority="high"
                        )
                        
                        # Send email reminder
                        user = await db.get(User, invoice.user_id)
                        if user and user.email:
                            await notification_service.send_email_notification(
                                to_email=user.email,
                                subject=f"Payment Overdue - Invoice {invoice.invoice_number}",
                                body=f"Your invoice {invoice.invoice_number} is overdue. Amount: ${invoice.total_amount}. Please make payment as soon as possible."
                            )
                        
                        reminders_sent += 1
                    except Exception as e:
                        logger.error(f"Failed to send reminder for invoice {invoice.id}: {e}")
                
                return reminders_sent
        
        import asyncio
        reminders_sent = asyncio.run(_send_reminders())
        
        logger.info(f"Payment reminders sent successfully. Count: {reminders_sent}")
        return {
            "status": "success", 
            "reminders_sent": reminders_sent
        }
    except Exception as exc:
        logger.error(f"Payment reminder sending failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_subscription_expiry_warnings(self):
    """Send warnings for subscriptions about to expire."""
    logger.info("Sending subscription expiry warnings")
    
    try:
        async def _send_warnings():
            async with AsyncSessionLocal() as db:
                from app.modules.subscriptions import SubscriptionService
                subscription_service = SubscriptionService(db)
                notification_service = NotificationService(db)
                
                # Get subscriptions expiring in 3 days
                expiring_subscriptions = await subscription_service.get_expiring_subscriptions(days=3)
                warnings_sent = 0
                
                for subscription in expiring_subscriptions:
                    try:
                        # Send warning notification
                        await notification_service.create_notification(
                            user_id=subscription.user_id,
                            title="Subscription Expiring Soon",
                            message=f"Your subscription will expire in 3 days. Please renew to avoid service interruption.",
                            notification_type="subscription",
                            priority="medium"
                        )
                        
                        # Send email warning
                        user = await db.get(User, subscription.user_id)
                        if user and user.email:
                            await notification_service.send_email_notification(
                                to_email=user.email,
                                subject="Subscription Expiring Soon",
                                body=f"Your subscription will expire in 3 days. Please renew to avoid service interruption."
                            )
                        
                        warnings_sent += 1
                    except Exception as e:
                        logger.error(f"Failed to send warning for subscription {subscription.id}: {e}")
                
                return warnings_sent
        
        import asyncio
        warnings_sent = asyncio.run(_send_warnings())
        
        logger.info(f"Subscription expiry warnings sent successfully. Count: {warnings_sent}")
        return {
            "status": "success", 
            "warnings_sent": warnings_sent
        }
    except Exception as exc:
        logger.error(f"Subscription expiry warning sending failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_welcome_notifications(self, user_id: int):
    """Send welcome notifications to new users."""
    logger.info(f"Sending welcome notifications to user {user_id}")
    
    try:
        async def _send_welcome():
            async with AsyncSessionLocal() as db:
                notification_service = NotificationService(db)
                user = await db.get(User, user_id)
                
                if not user:
                    return None
                
                # Send welcome notification
                await notification_service.create_notification(
                    user_id=user_id,
                    title="Welcome to ISP Billing System",
                    message=f"Welcome {user.first_name}! Your account has been created successfully.",
                    notification_type="welcome",
                    priority="low"
                )
                
                # Send welcome email
                if user.email:
                    await notification_service.send_email_notification(
                        to_email=user.email,
                        subject="Welcome to ISP Billing System",
                        body=f"Welcome {user.first_name}! Your account has been created successfully. You can now manage your subscriptions and billing."
                    )
                
                return user
        
        import asyncio
        user = asyncio.run(_send_welcome())
        
        if user:
            logger.info(f"Welcome notifications sent to user {user_id}")
            return {
                "status": "success", 
                "user_id": user_id,
                "user_name": user.first_name
            }
        else:
            logger.warning(f"User {user_id} not found for welcome notifications")
            return {
                "status": "failed", 
                "user_id": user_id,
                "error": "User not found"
            }
    except Exception as exc:
        logger.error(f"Welcome notification sending failed for user {user_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def process_notification_queue(self):
    """Process pending notifications from the queue."""
    logger.info("Processing notification queue")
    
    try:
        async def _process_queue():
            async with AsyncSessionLocal() as db:
                notification_service = NotificationService(db)
                
                # Get pending notifications
                result = await db.execute(
                    select(Notification).where(Notification.status == NotificationStatus.PENDING)
                )
                pending_notifications = result.scalars().all()
                
                processed_count = 0
                for notification in pending_notifications:
                    try:
                        # Process notification based on type
                        if notification.notification_type == "email":
                            # Send email using notification service
                            from app.modules.notifications import NotificationService
                            notification_service = NotificationService(db)
                            await notification_service.send_email_notification(
                                to_email=notification.recipient,
                                subject=notification.title,
                                body=notification.message
                            )
                        elif notification.notification_type == "sms":
                            # Send SMS using notification service
                            from app.modules.notifications import NotificationService
                            notification_service = NotificationService(db)
                            await notification_service.send_sms_notification(
                                to_phone=notification.recipient,
                                message=notification.message
                            )
                        
                        # Update status
                        notification.status = NotificationStatus.SENT
                        notification.sent_at = datetime.utcnow()
                        processed_count += 1
                    except Exception as e:
                        logger.error(f"Failed to process notification {notification.id}: {e}")
                        notification.status = NotificationStatus.FAILED
                
                await db.commit()
                return processed_count
        
        import asyncio
        processed_count = asyncio.run(_process_queue())
        
        logger.info(f"Notification queue processed successfully. Count: {processed_count}")
        return {
            "status": "success", 
            "processed_count": processed_count
        }
    except Exception as exc:
        logger.error(f"Notification queue processing failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def cleanup_old_notifications(self, days_old: int = 30):
    """Clean up old notifications."""
    logger.info(f"Cleaning up notifications older than {days_old} days")
    
    try:
        async def _cleanup():
            async with AsyncSessionLocal() as db:
                # Get old notifications
                cutoff_date = datetime.utcnow() - timedelta(days=days_old)
                result = await db.execute(
                    select(Notification).where(Notification.created_at < cutoff_date)
                )
                old_notifications = result.scalars().all()
                
                cleaned_count = 0
                for notification in old_notifications:
                    await db.delete(notification)
                    cleaned_count += 1
                
                await db.commit()
                return cleaned_count
        
        import asyncio
        cleaned_count = asyncio.run(_cleanup())
        
        logger.info(f"Old notifications cleaned up successfully. Count: {cleaned_count}")
        return {
            "status": "success", 
            "cleaned_count": cleaned_count
        }
    except Exception as exc:
        logger.error(f"Notification cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)