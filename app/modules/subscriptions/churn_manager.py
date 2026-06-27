"""Tiered customer churn + hard-purge (Issue 3).

Captive hotspot customers who stop reconnecting / buying are churned in TIERS, so
operators get accurate retention reporting while still reclaiming router slots and
(eventually) purging stale PII:

  * Tier 1 — expiry (``expiry_manager``): at package expiry the user is
    disconnected + disabled on the router and the Subscription goes EXPIRED. The
    row is KEPT (a returning customer just renews it in place).
  * Tier 2 — churn-mark (:meth:`ChurnManager.process_churn_mark`): after the
    tenant's configurable ``OrganizationSettings.prune_inactive_users_days``
    (default 14) with no reconnect/renewal, the router user is REMOVED (frees the
    hotspot slot) and the Subscription is marked INACTIVE = "churned". The row is
    still KEPT so the retention report counts it as a non-returning customer.
  * Tier 3 — hard-purge (:meth:`ChurnManager.process_hard_purge`): after a longer
    window (default 90 days) the customer's operational footprint + PII
    (CustomerPurchase phone/email, CustomerSession, Subscription) are DELETED and
    the router account removed. The synthetic, PII-free customer ``User`` and the
    ``Payment`` (revenue) are retained so accounting / aggregate revenue stay intact.

A returning customer (buys again) flips their Subscription back to ACTIVE via the
hotspot dashboard bridge, so churn is fully reversible until hard-purge.

All router changes are NAT-safe (routed through the polling-agent command queue)
and best-effort — a failure for one customer never aborts the batch.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_portal import CustomerPurchase, CustomerSession
from app.models.organization import OrganizationSettings
from app.models.router import Router
from app.models.subscription import (
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
)

logger = logging.getLogger(__name__)

# Tier-3 hard-purge window. Kept as a module constant (NOT a per-tenant column) so
# Issue 3 ships with no DB migration; can be promoted to OrganizationSettings later.
DEFAULT_HARD_PURGE_DAYS = 90

# System default churn window when a tenant has no OrganizationSettings row.
DEFAULT_PRUNE_DAYS = 14


class ChurnManager:
    """Run the Tier-2 (churn-mark) and Tier-3 (hard-purge) churn passes."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._router_cache: Dict[int, Optional[Router]] = {}

    # ------------------------------------------------------------------ helpers
    async def _prune_days_by_org(self) -> Dict[int, int]:
        """Map organization_id -> prune_inactive_users_days (tenant-configurable)."""
        rows = (
            await self.db.execute(
                select(
                    OrganizationSettings.organization_id,
                    OrganizationSettings.prune_inactive_users_days,
                )
            )
        ).all()
        return {oid: (days or DEFAULT_PRUNE_DAYS) for oid, days in rows}

    async def _router_for_org(self, organization_id: int) -> Optional[Router]:
        if organization_id not in self._router_cache:
            self._router_cache[organization_id] = (
                await self.db.execute(
                    select(Router)
                    .where(
                        Router.organization_id == organization_id,
                        Router.is_active == True,  # noqa: E712
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        return self._router_cache[organization_id]

    async def _queue_remove_user(
        self, organization_id: int, username: str, *, source: str, source_id: str
    ) -> bool:
        """Queue a NAT-safe ``remove_user`` for the org's router (best-effort)."""
        router = await self._router_for_org(organization_id)
        if not router or not username:
            return False
        if not (getattr(router, "agent_installed", False) and getattr(router, "agent_token", None)):
            # No polling agent — the router is unreachable from the cloud (NATed).
            # Skip silently; the row-side churn still proceeds.
            return False
        try:
            from app.services.router_agent import RouterAgentService

            agent = RouterAgentService(self.db)
            await agent.queue_command(
                router_id=router.id,
                action="remove_user",
                params={"username": username, "type": "hotspot"},
                priority=3,
                source=source,
                source_id=source_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.error(
                "churn: failed to queue remove_user for %s on router %s: %s",
                username, router.id, exc,
            )
            return False

    # -------------------------------------------------------------- tier 2
    async def process_churn_mark(self) -> Dict[str, int]:
        """Tier 2: mark long-inactive hotspot customers CHURNED + free the router slot.

        Selects EXPIRED hotspot Subscriptions whose ``end_date`` is older than the
        tenant's ``prune_inactive_users_days`` and: queues a router ``remove_user``
        and flips the Subscription to INACTIVE (= churned). The row is KEPT for
        retention reporting; a repeat purchase reactivates it via the bridge.
        """
        now = datetime.utcnow()
        prune_by_org = await self._prune_days_by_org()
        result = {"scanned": 0, "churned": 0, "router_removed": 0, "errors": 0}

        subs = (
            await self.db.execute(
                select(Subscription).where(
                    Subscription.subscription_type == SubscriptionType.HOTSPOT,
                    Subscription.status == SubscriptionStatus.EXPIRED,
                )
            )
        ).scalars().all()

        for sub in subs:
            result["scanned"] += 1
            try:
                prune_days = prune_by_org.get(sub.organization_id, DEFAULT_PRUNE_DAYS)
                cutoff = now - timedelta(days=prune_days)
                if not sub.end_date or sub.end_date >= cutoff:
                    continue  # still within the grace window

                if await self._queue_remove_user(
                    sub.organization_id, sub.username,
                    source="churn_mark", source_id=str(sub.id),
                ):
                    result["router_removed"] += 1

                sub.status = SubscriptionStatus.INACTIVE
                sub.updated_at = now
                result["churned"] += 1
            except Exception as exc:  # noqa: BLE001 - never abort the batch
                result["errors"] += 1
                logger.error("churn-mark failed for subscription %s: %s", sub.id, exc)

        await self.db.commit()
        logger.info("churn-mark pass complete: %s", result)
        return result

    # -------------------------------------------------------------- tier 3
    async def process_hard_purge(
        self, hard_purge_days: int = DEFAULT_HARD_PURGE_DAYS
    ) -> Dict[str, int]:
        """Tier 3: hard-purge customers inactive beyond the long window.

        Deletes the operational footprint + PII (CustomerPurchase, CustomerSession,
        Subscription) for churned/expired hotspot customers older than
        ``hard_purge_days`` and removes the router account. The synthetic (PII-free)
        customer ``User`` and ``Payment`` rows are retained so revenue/accounting
        stay intact. FK-safe order: purchases -> sessions -> subscription.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(days=hard_purge_days)
        result = {"scanned": 0, "purged": 0, "router_removed": 0, "errors": 0}

        subs = (
            await self.db.execute(
                select(Subscription).where(
                    Subscription.subscription_type == SubscriptionType.HOTSPOT,
                    Subscription.status.in_(
                        [
                            SubscriptionStatus.INACTIVE,
                            SubscriptionStatus.EXPIRED,
                            SubscriptionStatus.CANCELLED,
                        ]
                    ),
                    Subscription.end_date < cutoff,
                )
            )
        ).scalars().all()

        for sub in subs:
            result["scanned"] += 1
            try:
                if await self._queue_remove_user(
                    sub.organization_id, sub.username,
                    source="hard_purge", source_id=str(sub.id),
                ):
                    result["router_removed"] += 1

                # Capture the CustomerSession ids referenced by this customer's
                # purchases BEFORE deleting the purchases (FK points purchase ->
                # session), so we can then delete the now-unreferenced sessions.
                session_ids = [
                    sid for (sid,) in (
                        await self.db.execute(
                            select(CustomerPurchase.session_id).where(
                                CustomerPurchase.subscription_id == sub.id,
                                CustomerPurchase.session_id.is_not(None),
                            )
                        )
                    ).all()
                ]

                await self.db.execute(
                    delete(CustomerPurchase).where(
                        CustomerPurchase.subscription_id == sub.id
                    )
                )
                if session_ids:
                    await self.db.execute(
                        delete(CustomerSession).where(
                            CustomerSession.id.in_(session_ids)
                        )
                    )
                await self.db.execute(
                    delete(Subscription).where(Subscription.id == sub.id)
                )
                await self.db.commit()
                result["purged"] += 1
            except Exception as exc:  # noqa: BLE001 - isolate per-customer failures
                result["errors"] += 1
                logger.error("hard-purge failed for subscription %s: %s", sub.id, exc)
                try:
                    await self.db.rollback()
                except Exception:
                    pass

        logger.info("hard-purge pass complete: %s", result)
        return result
