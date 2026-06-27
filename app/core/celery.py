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
        "app.tasks.event_tasks",
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
        "cleanup-expired-commands": {
            "task": "app.tasks.router_tasks.cleanup_expired_commands",
            "schedule": 60.0 * 15,  # Every 15 minutes
        },
        "cleanup-old-router-backups": {
            "task": "app.tasks.router_tasks.cleanup_old_router_backups",
            "schedule": 60.0 * 60 * 24,  # Daily — churn backups older than 2 days
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
        "process-expired-hotspot-users": {
            "task": "app.tasks.subscription_tasks.process_expired_hotspot_users",
            "schedule": 60.0 * 2,  # Every 2 min - disconnect expired hotspot/voucher users (NAT-safe)
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
        # Tiered churn (Issue 3): churn-mark removes the router slot + marks CHURNED
        # after the tenant's prune_inactive_users_days (kept for retention); hard-purge
        # deletes operational/PII rows after the long window. Daily is ample.
        "process-churn-mark": {
            "task": "app.tasks.subscription_tasks.process_churn_mark",
            "schedule": 60.0 * 60 * 24,  # Daily
        },
        "process-hard-purge": {
            "task": "app.tasks.subscription_tasks.process_hard_purge",
            "schedule": 60.0 * 60 * 24,  # Daily
        },
        # NOTE: platform-licence beat tasks removed — the local licence subsystem is
        # retired; ISP subscription/renewal lifecycle is owned by subscriptions-api
        # (with treasury auto-invoicing).
        # Phase 5: transactional-outbox publisher → NATS JetStream.
        # Inert when NATS_URL is unset (publishes 0 rows), so safe to always run.
        "publish-outbox-events": {
            "task": "app.tasks.event_tasks.publish_outbox_events",
            "schedule": 5.0,  # Every 5 seconds
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
