"""Celery configuration and setup."""

from celery import Celery
from app.core.config import settings

# Create Celery instance
celery_app = Celery(
    "ispbilling",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.billing_tasks",
        "app.tasks.notification_tasks",
        "app.tasks.router_tasks",
        "app.tasks.provisioning_tasks",
        "app.tasks.subscription_tasks",
        "app.tasks.licence_tasks",
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    result_expires=3600,  # 1 hour
    beat_schedule={
        "billing-cycle": {
            "task": "app.tasks.billing_tasks.run_billing_cycle",
            "schedule": 60.0 * 60 * 24,  # Daily
        },
        "cleanup-expired-sessions": {
            "task": "app.tasks.billing_tasks.cleanup_expired_sessions",
            "schedule": 60.0 * 60,  # Hourly
        },
        "sync-router-status": {
            "task": "app.tasks.router_tasks.sync_router_status",
            "schedule": 60.0 * 5,  # Every 5 minutes
        },
        "send-payment-reminders": {
            "task": "app.tasks.notification_tasks.send_payment_reminders",
            "schedule": 60.0 * 60 * 12,  # Twice daily
        },
        "monitor-provisioning-sessions": {
            "task": "app.tasks.provisioning_tasks.monitor_provisioning_sessions",
            "schedule": 60.0 * 5,  # Every 5 minutes
        },
        "process-scheduled-provisioning": {
            "task": "app.tasks.provisioning_tasks.process_scheduled_provisioning",
            "schedule": 60.0,  # Every minute
        },
        "cleanup-old-provisioning-sessions": {
            "task": "app.tasks.provisioning_tasks.cleanup_old_provisioning_sessions",
            "schedule": 60.0 * 60 * 24,  # Daily
        },
        "update-provisioning-templates-stats": {
            "task": "app.tasks.provisioning_tasks.update_provisioning_templates_stats",
            "schedule": 60.0 * 60 * 6,  # Every 6 hours
        },
        # Subscription management tasks
        "process-expired-subscriptions": {
            "task": "app.tasks.subscription_tasks.process_expired_subscriptions",
            "schedule": 60.0,  # Every minute - critical for timely disconnection
        },
        "send-expiring-soon-notifications": {
            "task": "app.tasks.subscription_tasks.send_expiring_soon_notifications",
            "schedule": 60.0 * 30,  # Every 30 minutes
        },
        "check-expired-sessions-fallback": {
            "task": "app.tasks.subscription_tasks.check_and_disconnect_expired_sessions",
            "schedule": 60.0 * 15,  # Every 15 minutes - fallback check
        },
        "sync-bandwidth-profiles": {
            "task": "app.tasks.subscription_tasks.sync_bandwidth_profiles_to_all_routers",
            "schedule": 60.0 * 60 * 6,  # Every 6 hours
        },
        "cleanup-orphaned-router-users": {
            "task": "app.tasks.subscription_tasks.cleanup_orphaned_router_users",
            "schedule": 60.0 * 60 * 24,  # Daily
        },
        "generate-expiry-report": {
            "task": "app.tasks.subscription_tasks.generate_expiry_report",
            "schedule": 60.0 * 60 * 24,  # Daily
        },
        # Platform license management tasks
        "generate-renewal-invoices": {
            "task": "app.tasks.licence_tasks.generate_renewal_invoices_for_expiring_subscriptions",
            "schedule": 60.0 * 60 * 24,  # Daily at 00:00 UTC
        },
        "check-licence-grace-periods": {
            "task": "app.tasks.licence_tasks.check_licence_grace_periods",
            "schedule": 60.0 * 60,  # Hourly
        },
        "monitor-licence-expiry": {
            "task": "app.tasks.licence_tasks.monitor_licence_expiry",
            "schedule": 60.0 * 60 * 6,  # Every 6 hours
        },
        "send-licence-expiry-notifications": {
            "task": "app.tasks.licence_tasks.send_licence_expiry_notifications",
            "schedule": 60.0 * 60 * 12,  # Twice daily
        },
        "update-licence-usage-stats": {
            "task": "app.tasks.licence_tasks.update_licence_usage_stats",
            "schedule": 60.0 * 60,  # Hourly
        },
    },
)

# Optional configuration for production
if settings.is_production:
    celery_app.conf.update(
        worker_hijack_root_logger=False,
        worker_log_color=False,
        worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
        worker_task_log_format="[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s",
    )
