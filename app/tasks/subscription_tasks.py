"""
Subscription-related Celery tasks.

These tasks handle automatic subscription management including:
- Expiry detection and processing
- Router synchronization
- Bandwidth profile management
- Usage tracking
- Notifications for expiring subscriptions
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from celery import current_task
from sqlalchemy import select, and_

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.router import Router

logger = get_logger(__name__)


@celery_app.task(bind=True)
def process_expired_subscriptions(
    self,
    grace_period_minutes: int = 5,
    batch_size: int = 100,
    send_notifications: bool = True
):
    """
    Process all expired subscriptions.

    This is the main task that should run every minute to:
    1. Find subscriptions past their end_date
    2. Update their status to EXPIRED
    3. Disable users on MikroTik routers
    4. Disconnect any active sessions
    5. Send expiry notifications

    Args:
        grace_period_minutes: Minutes after expiry before disabling
        batch_size: Maximum subscriptions per run
        send_notifications: Whether to send SMS/email notifications
    """
    logger.info("Starting subscription expiry processing")

    try:
        async def _process_expiry():
            from app.modules.subscriptions.expiry_manager import SubscriptionExpiryManager

            async with AsyncSessionLocal() as db:
                expiry_manager = SubscriptionExpiryManager(db)

                results = await expiry_manager.process_expired_subscriptions(
                    grace_period_minutes=grace_period_minutes,
                    batch_size=batch_size,
                    send_notifications=send_notifications
                )

                return results

        results = asyncio.run(_process_expiry())

        logger.info(
            f"Expiry processing completed: "
            f"{results['expired']} expired, "
            f"{results['disabled_on_router']} disabled, "
            f"{results['failed']} failed"
        )

        return results

    except Exception as exc:
        logger.error(f"Subscription expiry processing failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def send_expiring_soon_notifications(
    self,
    hours_before: list = None,
    batch_size: int = 100
):
    """
    Send notifications for subscriptions expiring soon.

    Notifies users at configured intervals before their subscription expires.
    Default intervals: 24 hours, 6 hours, 1 hour.

    Args:
        hours_before: List of hours before expiry to notify
        batch_size: Maximum subscriptions to check
    """
    logger.info("Sending expiring soon notifications")

    if hours_before is None:
        hours_before = [24, 6, 1]

    try:
        async def _send_notifications():
            from app.modules.subscriptions.expiry_manager import SubscriptionExpiryManager

            async with AsyncSessionLocal() as db:
                expiry_manager = SubscriptionExpiryManager(db)

                results = await expiry_manager.process_expiring_soon_notifications(
                    hours_before=hours_before,
                    batch_size=batch_size
                )

                return results

        results = asyncio.run(_send_notifications())

        logger.info(
            f"Expiring soon notifications sent: {results['notifications_sent']} "
            f"of {results['checked']} checked"
        )

        return results

    except Exception as exc:
        logger.error(f"Expiring soon notifications failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@celery_app.task(bind=True)
def check_and_disconnect_expired_sessions(self, router_id: Optional[int] = None):
    """
    Check routers for active sessions with expired subscriptions.

    This is a fallback mechanism that scans routers for any users
    who should have been disconnected but weren't (due to network
    issues, task failures, etc.).

    Args:
        router_id: Specific router to check (None = all online routers)
    """
    logger.info(
        f"Checking for expired sessions on "
        f"{'router ' + str(router_id) if router_id else 'all routers'}"
    )

    try:
        async def _check_sessions():
            from app.modules.subscriptions.expiry_manager import SubscriptionExpiryManager

            async with AsyncSessionLocal() as db:
                expiry_manager = SubscriptionExpiryManager(db)

                results = await expiry_manager.check_and_disconnect_expired_sessions(
                    router_id=router_id
                )

                return results

        results = asyncio.run(_check_sessions())

        logger.info(
            f"Expired session check completed: "
            f"{results['disconnected']} disconnected "
            f"from {results['routers_checked']} routers"
        )

        return results

    except Exception as exc:
        logger.error(f"Expired session check failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@celery_app.task(bind=True)
def sync_subscription_to_router(self, subscription_id: int):
    """
    Sync a single subscription to its router.

    Call this after creating or updating a subscription to ensure
    the router has the correct user configuration.

    Args:
        subscription_id: ID of the subscription to sync
    """
    logger.info(f"Syncing subscription {subscription_id} to router")

    try:
        async def _sync_subscription():
            from app.modules.subscriptions.router_sync import SubscriptionRouterSyncService

            async with AsyncSessionLocal() as db:
                sync_service = SubscriptionRouterSyncService(db)

                # Get subscription
                result = await db.execute(
                    select(Subscription).where(Subscription.id == subscription_id)
                )
                subscription = result.scalar_one_or_none()

                if not subscription:
                    return {"success": False, "error": "Subscription not found"}

                sync_result = await sync_service.sync_subscription_to_router(subscription)

                return sync_result

        result = asyncio.run(_sync_subscription())

        if result["success"]:
            logger.info(f"Subscription {subscription_id} synced successfully")
        else:
            logger.warning(
                f"Subscription {subscription_id} sync failed: {result.get('error')}"
            )

        return result

    except Exception as exc:
        logger.error(f"Subscription sync failed for {subscription_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def sync_all_subscriptions_for_router(self, router_id: int):
    """
    Sync all subscriptions for a specific router.

    Useful after router reconnection or configuration reset.

    Args:
        router_id: ID of the router to sync subscriptions for
    """
    logger.info(f"Syncing all subscriptions for router {router_id}")

    try:
        async def _sync_router_subscriptions():
            from app.modules.subscriptions.router_sync import SubscriptionRouterSyncService

            async with AsyncSessionLocal() as db:
                sync_service = SubscriptionRouterSyncService(db)

                results = await sync_service.sync_all_subscriptions_to_router(router_id)

                return results

        results = asyncio.run(_sync_router_subscriptions())

        logger.info(
            f"Router {router_id} subscription sync completed: "
            f"{results['synced']} synced, {results['failed']} failed"
        )

        return results

    except Exception as exc:
        logger.error(f"Router subscription sync failed for {router_id}: {exc}")
        raise self.retry(exc=exc, countdown=120, max_retries=3)


@celery_app.task(bind=True)
def sync_bandwidth_profiles_to_router(self, router_id: int):
    """
    Sync all bandwidth profiles (from service plans) to a router.

    Creates/updates hotspot user profiles and PPP profiles with
    the rate limits defined in the service plans.

    Args:
        router_id: ID of the router to sync profiles to
    """
    logger.info(f"Syncing bandwidth profiles to router {router_id}")

    try:
        async def _sync_profiles():
            from app.modules.subscriptions.bandwidth_manager import BandwidthProfileManager

            async with AsyncSessionLocal() as db:
                bandwidth_manager = BandwidthProfileManager(db)

                # Get router
                router_result = await db.execute(
                    select(Router).where(Router.id == router_id)
                )
                router = router_result.scalar_one_or_none()

                if not router:
                    return {"success": False, "error": "Router not found"}

                results = await bandwidth_manager.sync_all_profiles_to_router(router)

                return results

        results = asyncio.run(_sync_profiles())

        if results["success"]:
            logger.info(
                f"Bandwidth profiles synced to router {router_id}: "
                f"{results['hotspot_profiles']['created']} hotspot created, "
                f"{results['ppp_profiles']['created']} PPP created"
            )
        else:
            logger.warning(
                f"Bandwidth profile sync failed for router {router_id}: "
                f"{results.get('error')}"
            )

        return results

    except Exception as exc:
        logger.error(f"Bandwidth profile sync failed for {router_id}: {exc}")
        raise self.retry(exc=exc, countdown=120, max_retries=3)


@celery_app.task(bind=True)
def sync_bandwidth_profiles_to_all_routers(self):
    """
    Sync bandwidth profiles to all online routers.

    Call this after modifying service plans to ensure all routers
    have the updated bandwidth configurations.
    """
    logger.info("Syncing bandwidth profiles to all routers")

    try:
        async def _sync_all():
            from app.modules.subscriptions.bandwidth_manager import BandwidthProfileManager

            async with AsyncSessionLocal() as db:
                bandwidth_manager = BandwidthProfileManager(db)

                results = await bandwidth_manager.sync_all_routers()

                return results

        results = asyncio.run(_sync_all())

        logger.info(
            f"Bandwidth profile sync completed: "
            f"{results['successful']} routers synced, "
            f"{results['failed']} failed"
        )

        return results

    except Exception as exc:
        logger.error(f"Bandwidth profile sync to all routers failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@celery_app.task(bind=True)
def renew_subscription(
    self,
    subscription_id: int,
    new_end_date: str,
    changed_by: Optional[int] = None
):
    """
    Renew a subscription and re-enable on router.

    Args:
        subscription_id: ID of subscription to renew
        new_end_date: New expiry date (ISO format string)
        changed_by: User ID who initiated the renewal
    """
    logger.info(f"Renewing subscription {subscription_id}")

    try:
        async def _renew():
            from app.modules.subscriptions.expiry_manager import SubscriptionExpiryManager

            async with AsyncSessionLocal() as db:
                expiry_manager = SubscriptionExpiryManager(db)

                # Parse the date
                end_date = datetime.fromisoformat(new_end_date.replace('Z', '+00:00'))

                result = await expiry_manager.renew_subscription(
                    subscription_id=subscription_id,
                    new_end_date=end_date,
                    changed_by=changed_by
                )

                return result

        result = asyncio.run(_renew())

        if result["success"]:
            logger.info(f"Subscription {subscription_id} renewed successfully")
        else:
            logger.warning(
                f"Subscription {subscription_id} renewal failed: {result.get('error')}"
            )

        return result

    except Exception as exc:
        logger.error(f"Subscription renewal failed for {subscription_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def generate_expiry_report(self, organization_id: Optional[int] = None, days: int = 30):
    """
    Generate expiry statistics report.

    Args:
        organization_id: Optional org to filter by
        days: Number of days for historical data
    """
    logger.info(f"Generating expiry report for {days} days")

    try:
        async def _generate():
            from app.modules.subscriptions.expiry_manager import SubscriptionExpiryManager

            async with AsyncSessionLocal() as db:
                expiry_manager = SubscriptionExpiryManager(db)

                stats = await expiry_manager.get_expiry_statistics(
                    organization_id=organization_id,
                    days=days
                )

                return stats

        results = asyncio.run(_generate())

        logger.info(f"Expiry report generated: {results.get('counts', {})}")

        return results

    except Exception as exc:
        logger.error(f"Expiry report generation failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@celery_app.task(bind=True)
def cleanup_orphaned_router_users(self, router_id: Optional[int] = None):
    """
    Clean up router users that don't have matching subscriptions.

    This removes users from routers whose subscriptions have been
    deleted from the database (rather than just expired).

    Args:
        router_id: Specific router to clean (None = all routers)
    """
    logger.info(
        f"Cleaning up orphaned router users on "
        f"{'router ' + str(router_id) if router_id else 'all routers'}"
    )

    try:
        async def _cleanup():
            from app.integrations.mikrotik import get_mikrotik_client

            async with AsyncSessionLocal() as db:
                # Get routers
                if router_id:
                    query = select(Router).where(Router.id == router_id)
                else:
                    query = select(Router).where(Router.status == "online")

                router_result = await db.execute(query)
                routers = router_result.scalars().all()

                results = {
                    "routers_checked": 0,
                    "users_removed": 0,
                    "errors": []
                }

                client = get_mikrotik_client()

                for router in routers:
                    results["routers_checked"] += 1

                    try:
                        connection = await client.connect(
                            ip_address=router.ip_address,
                            username=router.username,
                            password=router.password,
                            port=router.port
                        )

                        try:
                            # Get hotspot users
                            hotspot_users = await client.execute_command(
                                connection, "/ip/hotspot/user", method="get"
                            )

                            for user in (hotspot_users or []):
                                username = user.get('name')
                                if not username or username in ['default', 'admin']:
                                    continue

                                # Check if subscription exists
                                sub_result = await db.execute(
                                    select(Subscription).where(
                                        and_(
                                            Subscription.username == username,
                                            Subscription.router_id == router.id
                                        )
                                    )
                                )
                                subscription = sub_result.scalar_one_or_none()

                                if not subscription:
                                    # Remove orphaned user
                                    try:
                                        await client.execute_command(
                                            connection, "/ip/hotspot/user", method="remove",
                                            id=user['.id']
                                        )
                                        results["users_removed"] += 1
                                        logger.info(
                                            f"Removed orphaned user {username} from router {router.id}"
                                        )
                                    except Exception as e:
                                        logger.warning(f"Failed to remove user {username}: {e}")

                        finally:
                            await client.disconnect(router.ip_address, router.port)

                    except Exception as e:
                        results["errors"].append({
                            "router_id": router.id,
                            "error": str(e)
                        })

                return results

        results = asyncio.run(_cleanup())

        logger.info(
            f"Orphaned user cleanup completed: {results['users_removed']} removed"
        )

        return results

    except Exception as exc:
        logger.error(f"Orphaned user cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)
