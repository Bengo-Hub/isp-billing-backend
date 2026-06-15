"""
Subscription Expiry Management Service.

This module handles automatic detection and processing of expired subscriptions.
It is designed to be called by Celery scheduled tasks to ensure users are
disconnected when their packages expire.

Key Features:
- Detect expired subscriptions
- Disable users on MikroTik routers
- Disconnect active sessions
- Send expiry notifications
- Handle grace periods
- Track expiry history
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.router import Router
from app.models.subscription import (
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
    SubscriptionHistory
)
from app.models.plan import ServicePlan
from app.models.customer_portal import (
    VoucherCode,
    VoucherStatus,
    CustomerSession,
    SessionStatus,
    CustomerPurchase,
)
from app.integrations.mikrotik import get_mikrotik_client
from app.models.organization import OrganizationSettings
from .router_sync import SubscriptionRouterSyncService

logger = get_logger(__name__)

# Default churn window (days) applied to a hotspot/PPPoE account that has NO
# specific duration on its plan. The ISP can override per-tenant via
# OrganizationSettings.auto_suspend_days; this is the system fallback so that a
# duration-less ("unlimited") package never grants access forever.
DEFAULT_CHURN_DAYS = 14


class SubscriptionExpiryManager:
    """
    Manages subscription expiry detection and processing.

    This service should be called periodically (e.g., every minute) to:
    1. Find expired subscriptions
    2. Disable users on routers
    3. Disconnect active sessions
    4. Update subscription status
    5. Send notifications (optional)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.router_sync = SubscriptionRouterSyncService(db)

    async def process_expired_subscriptions(
        self,
        grace_period_minutes: int = 5,
        batch_size: int = 100,
        send_notifications: bool = True
    ) -> Dict[str, Any]:
        """
        Process all expired subscriptions.

        Args:
            grace_period_minutes: Minutes after expiry to wait before disabling
            batch_size: Maximum subscriptions to process per run
            send_notifications: Whether to send expiry notifications

        Returns:
            Dict with processing results
        """
        results = {
            "processed": 0,
            "expired": 0,
            "disabled_on_router": 0,
            "failed": 0,
            "notifications_sent": 0,
            "errors": [],
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # Find expired subscriptions
            grace_cutoff = datetime.utcnow() - timedelta(minutes=grace_period_minutes)

            # CHURN duration-less subscriptions: a PPPoE/hotspot Subscription created
            # with NO end_date (no specific duration) would otherwise never expire.
            # Backfill an effective end_date = start + the org's auto_suspend_days
            # (default 14) so it enters the normal expiry path once the churn window
            # passes. Idempotent (recomputes the same date from start each run).
            churn_cache: Dict[int, int] = {}
            perpetual = (
                await self.db.execute(
                    select(Subscription)
                    .where(
                        Subscription.status == SubscriptionStatus.ACTIVE,
                        Subscription.end_date.is_(None),
                    )
                    .limit(batch_size)
                )
            ).scalars().all()
            for _sub in perpetual:
                _start = _sub.start_date or _sub.created_at
                if not _start:
                    continue
                _churn_days = await self._churn_days_for_org(
                    _sub.organization_id, churn_cache
                )
                _sub.end_date = _start + timedelta(days=_churn_days)
            if perpetual:
                await self.db.flush()

            expired_query = select(Subscription).where(
                and_(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.end_date <= grace_cutoff
                )
            ).limit(batch_size)

            result = await self.db.execute(expired_query)
            expired_subscriptions = result.scalars().all()

            results["expired"] = len(expired_subscriptions)

            for subscription in expired_subscriptions:
                results["processed"] += 1

                try:
                    # Update subscription status
                    subscription.status = SubscriptionStatus.EXPIRED
                    subscription.updated_at = datetime.utcnow()

                    # Log the expiry
                    history = SubscriptionHistory(
                        subscription_id=subscription.id,
                        action="expired",
                        old_status=SubscriptionStatus.ACTIVE.value,
                        new_status=SubscriptionStatus.EXPIRED.value,
                        details=f"Subscription expired at {subscription.end_date}",
                        ip_address="system"
                    )
                    self.db.add(history)

                    # Sync to router (this will disable the user)
                    sync_result = await self.router_sync.sync_subscription_to_router(
                        subscription
                    )

                    if sync_result["success"]:
                        results["disabled_on_router"] += 1
                    else:
                        results["errors"].append({
                            "subscription_id": subscription.id,
                            "error": sync_result.get("error"),
                            "stage": "router_sync"
                        })

                    # Send notification if enabled
                    if send_notifications:
                        notification_sent = await self._send_expiry_notification(
                            subscription
                        )
                        if notification_sent:
                            results["notifications_sent"] += 1

                    await self.db.commit()

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({
                        "subscription_id": subscription.id,
                        "error": str(e),
                        "stage": "processing"
                    })
                    logger.error(f"Failed to process expired subscription {subscription.id}: {e}")
                    await self.db.rollback()

            logger.info(
                f"Expiry processing complete: "
                f"{results['expired']} expired, "
                f"{results['disabled_on_router']} disabled on router, "
                f"{results['failed']} failed"
            )

            return results

        except Exception as e:
            logger.error(f"Expiry processing failed: {e}")
            results["errors"].append({"error": str(e), "stage": "query"})
            return results

    async def _churn_days_for_org(self, org_id: Optional[int], cache: Dict[int, int]) -> int:
        """Configured churn window (days) for an org's duration-less accounts.

        Reads OrganizationSettings.auto_suspend_days, falling back to
        DEFAULT_CHURN_DAYS (14) when unset/zero or settings are missing. Cached
        per call so a batch loop does one query per org, not per row.
        """
        if org_id is None:
            return DEFAULT_CHURN_DAYS
        if org_id in cache:
            return cache[org_id]
        days = DEFAULT_CHURN_DAYS
        try:
            settings = (
                await self.db.execute(
                    select(OrganizationSettings).where(
                        OrganizationSettings.organization_id == org_id
                    )
                )
            ).scalar_one_or_none()
            if settings and settings.auto_suspend_days and settings.auto_suspend_days > 0:
                days = settings.auto_suspend_days
        except Exception:  # pragma: no cover - defensive; fall back to default
            days = DEFAULT_CHURN_DAYS
        cache[org_id] = days
        return days

    async def process_expired_hotspot_users(
        self,
        grace_period_minutes: int = 2,
        batch_size: int = 300,
    ) -> Dict[str, Any]:
        """
        Disable + disconnect HOTSPOT users whose package has expired.

        This is the hotspot counterpart to ``process_expired_subscriptions`` (which
        only covers the PPPoE ``Subscription`` model). Hotspot access is sold via
        ``VoucherCode``s — redeemed (status USED) or bought online — each carrying a
        ``hotspot_username`` created on the router. Without this, an expired
        voucher's router user stays enabled and the device silently re-authenticates
        via its mac-cookie => FREE INTERNET AFTER EXPIRY.

        NAT-safe: the disable/disconnect are queued through the polling AGENT (the
        cloud cannot reach a NATed router directly); a direct MikroTik API call is
        used only as a fallback for reachable (LAN/VPN) routers. Disabling the user
        is what defeats mac-cookie auto-re-login — a disabled user cannot
        authenticate by cookie or otherwise.
        """
        results = {
            "checked": 0,
            "expired": 0,
            "disabled_on_router": 0,
            "sessions_expired": 0,
            "failed": 0,
            "errors": [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        now = datetime.utcnow()

        try:
            candidates: List[tuple] = []  # (voucher, activated_at)

            # 1) Redeemed / activated vouchers (status USED) — the main path.
            used_result = await self.db.execute(
                select(VoucherCode)
                .where(
                    VoucherCode.hotspot_username.isnot(None),
                    VoucherCode.status == VoucherStatus.USED,
                    VoucherCode.used_at.isnot(None),
                )
                .order_by(VoucherCode.used_at.asc())
                .limit(batch_size)
            )
            candidates.extend((v, v.used_at) for v in used_result.scalars().all())

            # 2) Online purchases left ACTIVE (user already provisioned at payment).
            #    Joined to a completed purchase so admin-generated unredeemed
            #    vouchers (which must stay redeemable) are never touched.
            purchased_result = await self.db.execute(
                select(VoucherCode, CustomerPurchase.completed_at)
                .join(CustomerPurchase, CustomerPurchase.voucher_code_id == VoucherCode.id)
                .where(
                    VoucherCode.hotspot_username.isnot(None),
                    VoucherCode.status == VoucherStatus.ACTIVE,
                    CustomerPurchase.payment_status == "completed",
                )
                .limit(batch_size)
            )
            candidates.extend(
                (row[0], row[1] or row[0].created_at) for row in purchased_result.all()
            )

            results["checked"] = len(candidates)
            churn_cache: Dict[int, int] = {}

            for voucher, activated_at in candidates:
                try:
                    if not activated_at:
                        continue

                    plan = (
                        await self.db.execute(
                            select(ServicePlan).where(ServicePlan.id == voucher.plan_id)
                        )
                    ).scalar_one_or_none()
                    if not plan:
                        continue

                    # Effective window honours BOTH validity_days and time_limit
                    # (a "1 hour" package has validity_days=1 but time_limit=1h).
                    # A duration-less plan churns after the org's auto_suspend_days
                    # (default 14) so "unlimited" packages don't last forever.
                    churn_days = await self._churn_days_for_org(
                        voucher.organization_id, churn_cache
                    )
                    expiry = plan.access_expiry_from(activated_at, fallback_churn_days=churn_days)
                    if expiry is None:
                        # No plan window AND no churn fallback -> rely on router-side
                        # time/data limits; nothing to expire here.
                        continue
                    if now <= expiry + timedelta(minutes=grace_period_minutes):
                        continue  # still inside the paid window (+ grace)

                    results["expired"] += 1
                    if await self._expire_hotspot_user_on_router(
                        voucher.organization_id, voucher.hotspot_username
                    ):
                        results["disabled_on_router"] += 1

                    voucher.status = VoucherStatus.EXPIRED
                    voucher.updated_at = now

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({"voucher_id": voucher.id, "error": str(e)})
                    logger.error(f"Failed to expire hotspot voucher {voucher.id}: {e}")

            # Mark stale hotspot SESSIONS expired too (status only — the router
            # disconnect is driven off the voucher above). Keeps the dashboard
            # session list accurate.
            session_res = await self.db.execute(
                update(CustomerSession)
                .where(
                    CustomerSession.status == SessionStatus.ACTIVE,
                    CustomerSession.expires_at <= now,
                )
                .values(
                    status=SessionStatus.EXPIRED,
                    ended_at=now,
                    terminate_cause="Session-Timeout",
                    updated_at=now,
                )
            )
            results["sessions_expired"] = session_res.rowcount or 0

            await self.db.commit()

            logger.info(
                f"Hotspot expiry: checked={results['checked']} expired={results['expired']} "
                f"disabled_on_router={results['disabled_on_router']} "
                f"sessions_expired={results['sessions_expired']} failed={results['failed']}"
            )
            return results

        except Exception as e:
            logger.error(f"Hotspot expiry processing failed: {e}")
            results["errors"].append({"error": str(e), "stage": "query"})
            await self.db.rollback()
            return results

    async def _expire_hotspot_user_on_router(
        self, organization_id: int, username: str
    ) -> bool:
        """
        Disable + disconnect a hotspot user on the organization's router.

        NAT-safe: prefers the polling-agent command queue (production routers are
        NATed and unreachable from the cloud); falls back to a direct MikroTik API
        call only for reachable routers. Best-effort — never raises.
        """
        router = (
            await self.db.execute(
                select(Router)
                .where(
                    Router.organization_id == organization_id,
                    Router.is_active == True,  # noqa: E712
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if not router:
            return False

        # Preferred NAT-safe path: queue for the agent's next poll.
        if getattr(router, "agent_installed", False) and getattr(router, "agent_token", None):
            try:
                from app.services.router_agent import RouterAgentService

                agent = RouterAgentService(self.db)
                await agent.queue_command(
                    router_id=router.id,
                    action="disable_user",
                    params={"username": username, "type": "hotspot"},
                    priority=2,
                    source="hotspot_expiry",
                    source_id=username,
                )
                await agent.queue_command(
                    router_id=router.id,
                    action="disconnect",
                    params={"username": username},
                    priority=2,
                    source="hotspot_expiry",
                    source_id=username,
                )
                return True
            except Exception as e:
                logger.error(
                    f"Failed to queue hotspot expiry for {username} on router {router.id}: {e}"
                )
                return False

        # Direct API fallback (reachable routers only).
        try:
            client = get_mikrotik_client()
            connection = await client.connect(
                ip_address=router.ip_address,
                username=router.username,
                password=router.password,
                port=router.port,
            )
            try:
                users = await client.execute_command(
                    connection, "/ip/hotspot/user", method="get"
                )
                for u in (users or []):
                    if u.get("name") == username and u.get(".id"):
                        await client.execute_command(
                            connection, "/ip/hotspot/user", method="set",
                            id=u[".id"], disabled="yes",
                        )
                actives = await client.execute_command(
                    connection, "/ip/hotspot/active", method="get"
                )
                for a in (actives or []):
                    if a.get("user") == username and a.get(".id"):
                        await client.execute_command(
                            connection, "/ip/hotspot/active", method="remove", id=a[".id"],
                        )
            finally:
                await client.disconnect(router.ip_address, router.port)
            return True
        except Exception as e:
            logger.error(
                f"Direct hotspot expiry failed for {username} on router {router.id}: {e}"
            )
            return False

    async def process_expiring_soon_notifications(
        self,
        hours_before: List[int] = None,
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """
        Send notifications for subscriptions expiring soon.

        Args:
            hours_before: List of hours before expiry to notify (e.g., [24, 6, 1])
            batch_size: Maximum subscriptions to process

        Returns:
            Dict with notification results
        """
        if hours_before is None:
            hours_before = [24, 6, 1]  # Default: 24h, 6h, 1h before

        results = {
            "checked": 0,
            "notifications_sent": 0,
            "errors": [],
            "by_hours": {}
        }

        for hours in hours_before:
            try:
                window_start = datetime.utcnow() + timedelta(hours=hours - 0.5)
                window_end = datetime.utcnow() + timedelta(hours=hours + 0.5)

                expiring_query = select(Subscription).where(
                    and_(
                        Subscription.status == SubscriptionStatus.ACTIVE,
                        Subscription.end_date >= window_start,
                        Subscription.end_date <= window_end
                    )
                ).limit(batch_size)

                result = await self.db.execute(expiring_query)
                expiring = result.scalars().all()

                results["by_hours"][hours] = len(expiring)
                results["checked"] += len(expiring)

                for subscription in expiring:
                    try:
                        sent = await self._send_expiring_soon_notification(
                            subscription, hours
                        )
                        if sent:
                            results["notifications_sent"] += 1
                    except Exception as e:
                        results["errors"].append({
                            "subscription_id": subscription.id,
                            "hours": hours,
                            "error": str(e)
                        })

            except Exception as e:
                results["errors"].append({
                    "hours": hours,
                    "error": str(e)
                })

        return results

    async def check_and_disconnect_expired_sessions(
        self,
        router_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Check router for active sessions with expired subscriptions
        and disconnect them.

        This is a fallback mechanism in case the normal expiry processing
        didn't disconnect the user (e.g., due to network issues).

        Args:
            router_id: Optional specific router to check. If None, checks all.

        Returns:
            Dict with disconnection results
        """
        results = {
            "routers_checked": 0,
            "sessions_checked": 0,
            "disconnected": 0,
            "errors": []
        }

        try:
            # Get routers to check
            if router_id:
                query = select(Router).where(Router.id == router_id)
            else:
                query = select(Router).where(Router.status == "online")

            router_result = await self.db.execute(query)
            routers = router_result.scalars().all()

            for router in routers:
                results["routers_checked"] += 1

                try:
                    client = get_mikrotik_client()
                    connection = await client.connect(
                        ip_address=router.ip_address,
                        username=router.username,
                        password=router.password,
                        port=router.port
                    )

                    try:
                        # Get active connections
                        connections = await client.get_active_connections(connection)
                        results["sessions_checked"] += len(connections)

                        for conn in connections:
                            username = conn.get("user") or conn.get("name")
                            if not username:
                                continue

                            # Check if subscription is expired
                            sub_result = await self.db.execute(
                                select(Subscription).where(
                                    and_(
                                        Subscription.username == username,
                                        Subscription.router_id == router.id,
                                        or_(
                                            Subscription.status == SubscriptionStatus.EXPIRED,
                                            Subscription.status == SubscriptionStatus.SUSPENDED,
                                            Subscription.status == SubscriptionStatus.CANCELLED,
                                            Subscription.end_date < datetime.utcnow()
                                        )
                                    )
                                )
                            )
                            expired_sub = sub_result.scalar_one_or_none()

                            if expired_sub:
                                # Disconnect this session
                                user_type = conn.get("type", "hotspot")
                                disconnected = await self._disconnect_session(
                                    client, connection, conn, user_type
                                )
                                if disconnected:
                                    results["disconnected"] += 1
                                    logger.info(
                                        f"Disconnected expired session: "
                                        f"{username} on router {router.id}"
                                    )

                    finally:
                        await client.disconnect(router.ip_address, router.port)

                except Exception as e:
                    results["errors"].append({
                        "router_id": router.id,
                        "error": str(e)
                    })

            return results

        except Exception as e:
            logger.error(f"Session check failed: {e}")
            results["errors"].append({"error": str(e)})
            return results

    async def _disconnect_session(
        self,
        client,
        connection,
        session: Dict[str, Any],
        user_type: str
    ) -> bool:
        """Disconnect a specific session."""
        try:
            session_id = session.get(".id")
            if not session_id:
                return False

            resource_path = "/ip/hotspot/active" if user_type == "hotspot" else "/ppp/active"
            await client.execute_command(
                connection, resource_path, method="remove", id=session_id
            )

            return True

        except Exception as e:
            logger.warning(f"Failed to disconnect session: {e}")
            return False

    async def _send_expiry_notification(
        self,
        subscription: Subscription
    ) -> bool:
        """Send expiry notification to user."""
        try:
            # Import notification service
            # This would integrate with your SMS/email notification system
            from app.modules.notifications.service import NotificationService

            # Get user info
            user_query = select(User).where(User.id == subscription.user_id)
            from app.models.user import User
            user_result = await self.db.execute(user_query)
            user = user_result.scalar_one_or_none()

            if not user:
                return False

            # Get plan name
            plan_query = select(ServicePlan).where(ServicePlan.id == subscription.plan_id)
            plan_result = await self.db.execute(plan_query)
            plan = plan_result.scalar_one_or_none()
            plan_name = plan.name if plan else "Unknown"

            # Send notification (SMS or email based on user preference)
            message = (
                f"Your {plan_name} internet package has expired. "
                f"Please renew to continue enjoying our services. "
                f"Visit our portal to purchase a new package."
            )

            # Note: Actual SMS sending would be implemented here
            # For now, just log it
            logger.info(
                f"Expiry notification for subscription {subscription.id}: "
                f"User {user.phone or user.email}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to send expiry notification: {e}")
            return False

    async def _send_expiring_soon_notification(
        self,
        subscription: Subscription,
        hours_remaining: int
    ) -> bool:
        """Send expiring soon notification."""
        try:
            from app.models.user import User

            user_query = select(User).where(User.id == subscription.user_id)
            user_result = await self.db.execute(user_query)
            user = user_result.scalar_one_or_none()

            if not user:
                return False

            plan_query = select(ServicePlan).where(ServicePlan.id == subscription.plan_id)
            plan_result = await self.db.execute(plan_query)
            plan = plan_result.scalar_one_or_none()
            plan_name = plan.name if plan else "Unknown"

            if hours_remaining >= 24:
                time_str = f"{hours_remaining // 24} day(s)"
            else:
                time_str = f"{hours_remaining} hour(s)"

            message = (
                f"Your {plan_name} internet package will expire in {time_str}. "
                f"Renew now to avoid disconnection."
            )

            logger.info(
                f"Expiring soon notification for subscription {subscription.id}: "
                f"{hours_remaining}h remaining"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to send expiring soon notification: {e}")
            return False

    async def get_expiry_statistics(
        self,
        organization_id: Optional[int] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get expiry statistics for reporting.

        Returns counts of expired, expiring soon, and active subscriptions.
        """
        try:
            now = datetime.utcnow()
            period_start = now - timedelta(days=days)

            base_filter = []
            if organization_id:
                base_filter.append(Subscription.organization_id == organization_id)

            # Count by status
            stats = {
                "period_days": days,
                "organization_id": organization_id,
                "timestamp": now.isoformat(),
                "counts": {},
                "expiring_soon": {}
            }

            for status in SubscriptionStatus:
                count_query = select(Subscription).where(
                    and_(
                        Subscription.status == status,
                        *base_filter
                    )
                )
                result = await self.db.execute(count_query)
                stats["counts"][status.value] = len(result.scalars().all())

            # Expiring in next 24h, 7d, 30d
            for hours, label in [(24, "24h"), (168, "7d"), (720, "30d")]:
                expiring_query = select(Subscription).where(
                    and_(
                        Subscription.status == SubscriptionStatus.ACTIVE,
                        Subscription.end_date <= now + timedelta(hours=hours),
                        Subscription.end_date > now,
                        *base_filter
                    )
                )
                result = await self.db.execute(expiring_query)
                stats["expiring_soon"][label] = len(result.scalars().all())

            # Recently expired (last 24h)
            recent_query = select(Subscription).where(
                and_(
                    Subscription.status == SubscriptionStatus.EXPIRED,
                    Subscription.end_date >= now - timedelta(hours=24),
                    *base_filter
                )
            )
            result = await self.db.execute(recent_query)
            stats["recently_expired_24h"] = len(result.scalars().all())

            return stats

        except Exception as e:
            logger.error(f"Failed to get expiry statistics: {e}")
            return {"error": str(e)}

    async def renew_subscription(
        self,
        subscription_id: int,
        new_end_date: datetime,
        changed_by: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Renew an expired or active subscription.

        Args:
            subscription_id: ID of subscription to renew
            new_end_date: New expiry date
            changed_by: User ID who initiated the renewal

        Returns:
            Dict with renewal result
        """
        result = {
            "success": False,
            "subscription_id": subscription_id,
            "error": None
        }

        try:
            # Get subscription
            sub_result = await self.db.execute(
                select(Subscription).where(Subscription.id == subscription_id)
            )
            subscription = sub_result.scalar_one_or_none()

            if not subscription:
                result["error"] = "Subscription not found"
                return result

            old_status = subscription.status

            # Update subscription
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.end_date = new_end_date
            subscription.updated_at = datetime.utcnow()
            subscription.is_router_synced = False  # Mark for re-sync

            # Log the renewal
            history = SubscriptionHistory(
                subscription_id=subscription.id,
                action="renewed",
                old_status=old_status.value,
                new_status=SubscriptionStatus.ACTIVE.value,
                details=f"Renewed until {new_end_date}",
                changed_by=changed_by
            )
            self.db.add(history)

            await self.db.commit()

            # Sync to router (re-enable user)
            sync_result = await self.router_sync.sync_subscription_to_router(
                subscription
            )

            result["success"] = sync_result["success"]
            result["new_end_date"] = new_end_date.isoformat()
            result["router_synced"] = sync_result["success"]

            if not sync_result["success"]:
                result["router_error"] = sync_result.get("error")

            return result

        except Exception as e:
            logger.error(f"Subscription renewal failed: {e}")
            result["error"] = str(e)
            await self.db.rollback()
            return result
