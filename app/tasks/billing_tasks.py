"""Billing-related Celery tasks."""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from celery import current_task
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.billing import Invoice, InvoiceStatus, BillingCycle
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import UserSession
from app.modules.billing import BillingService

logger = get_logger(__name__)


@celery_app.task(bind=True)
def run_billing_cycle(self):
    """Run the main billing cycle to generate invoices."""
    logger.info("Starting billing cycle task")
    
    try:
        # Use async context for database operations
        async def _run_billing_cycle():
            async with AsyncSessionLocal() as db:
                billing_service = BillingService(db)
                result = await billing_service.generate_billing_cycle_invoices()
                return result
        
        # Run the async function
        import asyncio
        result = asyncio.run(_run_billing_cycle())
        
        logger.info(f"Billing cycle completed successfully. Generated {result['invoices_created']} invoices")
        return {
            "status": "success", 
            "invoices_generated": result["invoices_created"],
            "total_subscriptions": result["total_subscriptions"],
            "errors": result["errors"]
        }
    except Exception as exc:
        logger.error(f"Billing cycle failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def generate_invoice_for_user(self, user_id: int, subscription_id: int):
    """Generate invoice for a specific user and subscription."""
    logger.info(f"Generating invoice for user {user_id}, subscription {subscription_id}")
    
    try:
        async def _generate_invoice():
            async with AsyncSessionLocal() as db:
                billing_service = BillingService(db)
                invoice = await billing_service.generate_subscription_invoice(subscription_id)
                return invoice
        
        import asyncio
        invoice = asyncio.run(_generate_invoice())
        
        if invoice:
            logger.info(f"Invoice {invoice.invoice_number} generated for user {user_id}")
            return {
                "status": "success", 
                "user_id": user_id, 
                "subscription_id": subscription_id,
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number
            }
        else:
            logger.warning(f"Failed to generate invoice for user {user_id}, subscription {subscription_id}")
            return {
                "status": "failed", 
                "user_id": user_id, 
                "subscription_id": subscription_id,
                "error": "Invoice generation failed"
            }
    except Exception as exc:
        logger.error(f"Invoice generation failed for user {user_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def process_payment(self, payment_id: int):
    """Process a payment and update related records."""
    logger.info(f"Processing payment {payment_id}")
    
    try:
        async def _process_payment():
            async with AsyncSessionLocal() as db:
                billing_service = BillingService(db)
                payment = await billing_service.get_payment_by_id(payment_id)
                
                if not payment:
                    return None
                
                # Update payment status to completed
                payment.status = "completed"
                payment.processed_date = datetime.utcnow()
                
                # Apply payment to invoice if linked
                if payment.invoice_id:
                    await billing_service._apply_payment_to_invoice(payment.invoice_id, payment.amount)
                
                await db.commit()
                return payment
        
        import asyncio
        payment = asyncio.run(_process_payment())
        
        if payment:
            logger.info(f"Payment {payment_id} processed successfully")
            return {
                "status": "success", 
                "payment_id": payment_id,
                "amount": float(payment.amount),
                "invoice_id": payment.invoice_id
            }
        else:
            logger.warning(f"Payment {payment_id} not found")
            return {
                "status": "failed", 
                "payment_id": payment_id,
                "error": "Payment not found"
            }
    except Exception as exc:
        logger.error(f"Payment processing failed for payment {payment_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_invoice_reminder(self, invoice_id: int):
    """Send invoice reminder to user."""
    logger.info(f"Sending invoice reminder for invoice {invoice_id}")
    
    try:
        async def _send_reminder():
            async with AsyncSessionLocal() as db:
                billing_service = BillingService(db)
                invoice = await billing_service.get_invoice_by_id(invoice_id)
                
                if not invoice:
                    return None
                
                # Create notification for invoice reminder
                from app.modules.notifications import NotificationService
                notification_service = NotificationService(db)
                
                await notification_service.create_notification(
                    user_id=invoice.user_id,
                    title="Invoice Payment Reminder",
                    message=f"Your invoice {invoice.invoice_number} is due for payment. Amount: ${invoice.total_amount}",
                    notification_type="billing",
                    priority="medium"
                )
                
                return invoice
        
        import asyncio
        invoice = asyncio.run(_send_reminder())
        
        if invoice:
            logger.info(f"Invoice reminder sent for invoice {invoice_id}")
            return {
                "status": "success", 
                "invoice_id": invoice_id,
                "invoice_number": invoice.invoice_number
            }
        else:
            logger.warning(f"Invoice {invoice_id} not found for reminder")
            return {
                "status": "failed", 
                "invoice_id": invoice_id,
                "error": "Invoice not found"
            }
    except Exception as exc:
        logger.error(f"Invoice reminder failed for invoice {invoice_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def suspend_expired_subscriptions(self):
    """Suspend subscriptions that have expired."""
    logger.info("Suspending expired subscriptions")
    
    try:
        async def _suspend_expired():
            async with AsyncSessionLocal() as db:
                from app.modules.subscriptions import SubscriptionService
                subscription_service = SubscriptionService(db)
                
                # Get expired subscriptions
                expired_subscriptions = await subscription_service.get_expired_subscriptions()
                suspended_count = 0
                
                for subscription in expired_subscriptions:
                    try:
                        await subscription_service.suspend_subscription(
                            subscription.id, 
                            None, 
                            "Subscription expired"
                        )
                        suspended_count += 1
                    except Exception as e:
                        logger.error(f"Failed to suspend subscription {subscription.id}: {e}")
                
                return suspended_count
        
        import asyncio
        suspended_count = asyncio.run(_suspend_expired())
        
        logger.info(f"Expired subscriptions suspended successfully. Count: {suspended_count}")
        return {
            "status": "success", 
            "suspended_count": suspended_count
        }
    except Exception as exc:
        logger.error(f"Subscription suspension failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def cleanup_expired_sessions(self):
    """Clean up expired user sessions."""
    logger.info("Cleaning up expired sessions")
    
    try:
        async def _cleanup_sessions():
            async with AsyncSessionLocal() as db:
                # Get expired sessions (older than 7 days)
                cutoff_date = datetime.utcnow() - timedelta(days=7)
                result = await db.execute(
                    select(UserSession).where(UserSession.expires_at < cutoff_date)
                )
                expired_sessions = result.scalars().all()
                
                cleaned_count = 0
                for session in expired_sessions:
                    await db.delete(session)
                    cleaned_count += 1
                
                await db.commit()
                return cleaned_count
        
        import asyncio
        cleaned_count = asyncio.run(_cleanup_sessions())
        
        logger.info(f"Expired sessions cleaned up successfully. Count: {cleaned_count}")
        return {
            "status": "success", 
            "cleaned_count": cleaned_count
        }
    except Exception as exc:
        logger.error(f"Session cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def generate_monthly_reports(self):
    """Generate monthly billing and usage reports."""
    logger.info("Generating monthly reports")
    
    try:
        async def _generate_reports():
            async with AsyncSessionLocal() as db:
                from app.modules.analytics import ReportsService
                reports_service = ReportsService(db)
                
                # Generate reports for last month
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=30)
                
                # Generate CSV reports
                subscription_csv = await reports_service.generate_subscription_report_csv(
                    start_date, end_date
                )
                billing_csv = await reports_service.generate_billing_report_csv(
                    start_date, end_date
                )
                
                # Store reports (in production, this would save to cloud storage)
                reports_generated = 2
                
                return reports_generated
        
        import asyncio
        reports_generated = asyncio.run(_generate_reports())
        
        logger.info(f"Monthly reports generated successfully. Count: {reports_generated}")
        return {
            "status": "success", 
            "reports_generated": reports_generated
        }
    except Exception as exc:
        logger.error(f"Report generation failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)