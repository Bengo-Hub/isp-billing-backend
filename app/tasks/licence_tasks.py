"""Licence management Celery tasks."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

from celery import current_task
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.licence import Licence, LicenceStatus, LicencePaymentStatus
from app.models.organization import Organization, OrganizationStatus
from app.models.router import Router
from app.models.user import User
from app.models.subscription import Subscription
from app.modules.licences import LicenceService

logger = get_logger(__name__)


@celery_app.task(bind=True)
def monitor_licence_expiry(self):
    """Monitor all licences for expiry and create alerts."""
    logger.info("Monitoring licence expiry")
    
    try:
        async def _monitor_expiry():
            async with AsyncSessionLocal() as db:
                service = LicenceService(db)
                result = await service.monitor_licence_expiry()
                return result
        
        result = asyncio.run(_monitor_expiry())
        
        logger.info(f"Licence expiry monitoring completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Licence expiry monitoring failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)  # Retry in 1 hour


@celery_app.task(bind=True)
def update_licence_usage_stats(self):
    """Update licence usage statistics for all active licences."""
    logger.info("Updating licence usage statistics")
    
    try:
        async def _update_usage_stats():
            async with AsyncSessionLocal() as db:
                service = LicenceService(db)
                
                # Get all active licences
                result = await db.execute(
                    select(Licence).where(Licence.status == LicenceStatus.ACTIVE)
                )
                active_licences = result.scalars().all()
                
                updated_count = 0
                for licence in active_licences:
                    try:
                        # Get current system usage
                        router_count = await db.execute(
                            select(func.count(Router.id)).where(Router.is_active == True)
                        )
                        routers = router_count.scalar() or 0
                        
                        user_count = await db.execute(
                            select(func.count(User.id)).where(User.is_active == True)
                        )
                        users = user_count.scalar() or 0
                        
                        subscription_count = await db.execute(
                            select(func.count(Subscription.id)).where(Subscription.status == "active")
                        )
                        active_subscriptions = subscription_count.scalar() or 0
                        
                        # Calculate daily revenue (simplified - would integrate with billing)
                        daily_revenue = 0  # This would be calculated from actual payments
                        
                        # Update usage
                        usage_data = {
                            "routers_count": routers,
                            "users_count": users,
                            "active_sessions": active_subscriptions,
                            "total_transactions": licence.total_transactions,
                            "daily_revenue": daily_revenue,
                            "monthly_revenue": daily_revenue * 30,  # Simplified calculation
                            "system_uptime_percentage": 99.9,  # Would be calculated from monitoring
                            "api_calls_count": 0  # Would be tracked from API usage
                        }
                        
                        await service.update_licence_usage(licence.id, usage_data, "daily")
                        updated_count += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to update usage for licence {licence.id}: {e}")
                
                return {"updated_licences": updated_count}
        
        result = asyncio.run(_update_usage_stats())
        
        logger.info(f"Licence usage stats update completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Licence usage stats update failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)


@celery_app.task(bind=True)
def send_licence_expiry_notifications(self):
    """Send expiry notifications for licences nearing expiry."""
    logger.info("Sending licence expiry notifications")
    
    try:
        async def _send_notifications():
            async with AsyncSessionLocal() as db:
                # Get licences expiring in 7, 3, and 1 days
                notification_days = [7, 3, 1]
                notifications_sent = 0
                
                for days in notification_days:
                    expiry_date = datetime.utcnow() + timedelta(days=days)
                    start_date = expiry_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = start_date + timedelta(days=1)
                    
                    result = await db.execute(
                        select(Licence).where(
                            and_(
                                Licence.expiry_date >= start_date,
                                Licence.expiry_date < end_date,
                                Licence.status == LicenceStatus.ACTIVE
                            )
                        )
                    )
                    expiring_licences = result.scalars().all()
                    
                    for licence in expiring_licences:
                        try:
                            # Send email notification
                            from app.tasks.notification_tasks import send_email_notification
                            
                            subject = f"Licence Expiry Warning - {days} days remaining"
                            message = f"""
                            Your CodeVertex licence ({licence.licence_key}) will expire in {days} days.
                            
                            Licence Details:
                            - Organisation: {licence.organization_name}
                            - Expiry Date: {licence.expiry_date.strftime('%Y-%m-%d')}
                            - Type: {licence.licence_type.value}
                            
                            Please renew your licence to avoid service interruption.
                            """
                            
                            send_email_notification.delay(
                                user_id=None,  # System notification
                                subject=subject,
                                body=message,
                                to_email=licence.contact_email
                            )
                            
                            # Send SMS if phone number available
                            if licence.contact_phone:
                                from app.tasks.notification_tasks import send_sms_notification
                                
                                sms_message = f"CodeVertex licence {licence.licence_key} expires in {days} days. Renew at your dashboard."
                                
                                send_sms_notification.delay(
                                    user_id=None,
                                    message=sms_message,
                                    to_phone=licence.contact_phone
                                )
                            
                            notifications_sent += 1
                            
                        except Exception as e:
                            logger.error(f"Failed to send notification for licence {licence.id}: {e}")
                
                return {"notifications_sent": notifications_sent}
        
        result = asyncio.run(_send_notifications())
        
        logger.info(f"Licence expiry notifications completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Licence expiry notifications failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)


@celery_app.task(bind=True)
def process_licence_auto_renewals(self):
    """Process automatic licence renewals."""
    logger.info("Processing licence auto-renewals")
    
    try:
        async def _process_renewals():
            async with AsyncSessionLocal() as db:
                service = LicenceService(db)
                
                # Get licences with auto-renewal enabled that expire in 3 days
                renewal_date = datetime.utcnow() + timedelta(days=3)
                start_date = renewal_date.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date + timedelta(days=1)
                
                result = await db.execute(
                    select(Licence).where(
                        and_(
                            Licence.expiry_date >= start_date,
                            Licence.expiry_date < end_date,
                            Licence.auto_renewal_enabled == True,
                            Licence.status == LicenceStatus.ACTIVE
                        )
                    )
                )
                renewal_licences = result.scalars().all()
                
                processed_count = 0
                for licence in renewal_licences:
                    try:
                        # Create renewal payment (in production, this would integrate with payment gateway)
                        renewal_data = await service.renew_licence(
                            licence_id=licence.id,
                            renewal_months=licence.billing_cycle_months,
                            payment_method="auto_renewal",
                            amount=licence.monthly_cost * licence.billing_cycle_months,
                            auto_renewal=True
                        )
                        
                        # In production, you would trigger payment processing here
                        # For now, we'll mark as pending and require manual processing
                        
                        processed_count += 1
                        logger.info(f"Created auto-renewal for licence {licence.licence_key}")
                        
                    except Exception as e:
                        logger.error(f"Failed to process auto-renewal for licence {licence.id}: {e}")
                
                return {"processed_renewals": processed_count}
        
        result = asyncio.run(_process_renewals())
        
        logger.info(f"Licence auto-renewal processing completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Licence auto-renewal processing failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)


@celery_app.task(bind=True)
def cleanup_old_licence_data(self):
    """Clean up old licence usage logs and alerts."""
    logger.info("Cleaning up old licence data")
    
    try:
        async def _cleanup_data():
            async with AsyncSessionLocal() as db:
                # Clean up usage logs older than 1 year
                cleanup_date = datetime.utcnow() - timedelta(days=365)
                
                # Delete old usage logs
                result = await db.execute(
                    select(LicenceUsageLog).where(LicenceUsageLog.log_date < cleanup_date)
                )
                old_logs = result.scalars().all()
                
                logs_deleted = 0
                for log in old_logs:
                    await db.delete(log)
                    logs_deleted += 1
                
                # Clean up old acknowledged alerts (older than 90 days)
                alert_cleanup_date = datetime.utcnow() - timedelta(days=90)
                
                result = await db.execute(
                    select(LicenceAlert).where(
                        and_(
                            LicenceAlert.is_acknowledged == True,
                            LicenceAlert.acknowledged_at < alert_cleanup_date
                        )
                    )
                )
                old_alerts = result.scalars().all()
                
                alerts_deleted = 0
                for alert in old_alerts:
                    await db.delete(alert)
                    alerts_deleted += 1
                
                await db.commit()
                
                return {
                    "usage_logs_deleted": logs_deleted,
                    "alerts_deleted": alerts_deleted
                }
        
        result = asyncio.run(_cleanup_data())
        
        logger.info(f"Licence data cleanup completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Licence data cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=86400, max_retries=3)  # Retry in 24 hours


@celery_app.task(bind=True)
def generate_licence_reports(self):
    """Generate monthly licence usage and revenue reports."""
    logger.info("Generating licence reports")
    
    try:
        async def _generate_reports():
            async with AsyncSessionLocal() as db:
                service = LicenceService(db)
                
                # Get all active licences
                result = await db.execute(
                    select(Licence).where(Licence.status == LicenceStatus.ACTIVE)
                )
                active_licences = result.scalars().all()
                
                reports_generated = 0
                for licence in active_licences:
                    try:
                        # Generate analytics report
                        analytics = await service.get_licence_analytics(licence.id)
                        
                        # Generate earnings report
                        earnings = await service.get_licence_earnings(licence.id, "monthly", 12)
                        
                        # In production, these reports would be saved to file storage
                        # and optionally emailed to licence holders
                        
                        reports_generated += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to generate report for licence {licence.id}: {e}")
                
                return {"reports_generated": reports_generated}
        
        result = asyncio.run(_generate_reports())
        
        logger.info(f"Licence report generation completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Licence report generation failed: {exc}")
        raise self.retry(exc=exc, countdown=86400, max_retries=3)


@celery_app.task(bind=True)
def check_licence_grace_periods(self):
    """
    Check organization trial/subscription expiry and manage grace periods.

    Run every hour:
    - Expired within grace_period_days → status=PENDING_PAYMENT, set grace_period_ends_at
    - Grace period ended → status=SUSPENDED
    """
    logger.info("Checking licence grace periods")

    try:
        async def _check_grace_periods():
            async with AsyncSessionLocal() as db:
                now = datetime.utcnow()
                transitioned = {"to_pending_payment": 0, "to_suspended": 0}

                # 1. Find TRIAL orgs whose trial has expired
                result = await db.execute(
                    select(Organization).where(
                        and_(
                            Organization.status == OrganizationStatus.TRIAL,
                            Organization.trial_ends_at != None,
                            Organization.trial_ends_at <= now,
                            Organization.licence_bypass == False,
                        )
                    )
                )
                expired_trial_orgs = result.scalars().all()

                for org in expired_trial_orgs:
                    grace_end = org.trial_ends_at + timedelta(days=org.grace_period_days)
                    if now < grace_end:
                        org.status = OrganizationStatus.PENDING_PAYMENT
                        org.grace_period_ends_at = grace_end
                        transitioned["to_pending_payment"] += 1
                        logger.info(f"Org {org.id} ({org.name}) trial expired → PENDING_PAYMENT (grace until {grace_end})")
                    else:
                        org.status = OrganizationStatus.SUSPENDED
                        org.suspended_at = now
                        transitioned["to_suspended"] += 1
                        logger.info(f"Org {org.id} ({org.name}) trial + grace expired → SUSPENDED")

                # 2. Find ACTIVE orgs whose subscription has expired
                result = await db.execute(
                    select(Organization).where(
                        and_(
                            Organization.status == OrganizationStatus.ACTIVE,
                            Organization.subscription_ends_at != None,
                            Organization.subscription_ends_at <= now,
                            Organization.licence_bypass == False,
                        )
                    )
                )
                expired_sub_orgs = result.scalars().all()

                for org in expired_sub_orgs:
                    grace_end = org.subscription_ends_at + timedelta(days=org.grace_period_days)
                    if now < grace_end:
                        org.status = OrganizationStatus.PENDING_PAYMENT
                        org.grace_period_ends_at = grace_end
                        transitioned["to_pending_payment"] += 1
                        logger.info(f"Org {org.id} ({org.name}) subscription expired → PENDING_PAYMENT (grace until {grace_end})")
                    else:
                        org.status = OrganizationStatus.SUSPENDED
                        org.suspended_at = now
                        transitioned["to_suspended"] += 1
                        logger.info(f"Org {org.id} ({org.name}) subscription + grace expired → SUSPENDED")

                # 3. Find PENDING_PAYMENT orgs whose grace period has ended
                result = await db.execute(
                    select(Organization).where(
                        and_(
                            Organization.status == OrganizationStatus.PENDING_PAYMENT,
                            Organization.grace_period_ends_at != None,
                            Organization.grace_period_ends_at <= now,
                            Organization.licence_bypass == False,
                        )
                    )
                )
                grace_expired_orgs = result.scalars().all()

                for org in grace_expired_orgs:
                    org.status = OrganizationStatus.SUSPENDED
                    org.suspended_at = now
                    transitioned["to_suspended"] += 1
                    logger.info(f"Org {org.id} ({org.name}) grace period ended → SUSPENDED")

                await db.commit()
                return transitioned

        result = asyncio.run(_check_grace_periods())
        logger.info(f"Grace period check completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Grace period check failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)
