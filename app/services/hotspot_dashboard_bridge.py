"""Bridge hotspot purchases/voucher-redeems into the dashboard's data model.

Captive hotspot purchases + voucher redeems natively write ``CustomerSession`` +
``CustomerPurchase`` (see app/models/customer_portal.py). The admin dashboard's
Users-"All" tab, Expiry page and analytics/revenue reports however read
``Subscription`` + ``Payment`` + ``User`` (mirroring the PPPoE path which always
creates a Subscription, a customer User and a Payment).

This module is the single, IDEMPOTENT bridge that — after the existing
voucher/CustomerSession + router create_user provisioning — also creates / renews
the dashboard rows so hotspot customers are no longer invisible in
Customers/Users/Expiry/analytics:

  * a lightweight customer ``User`` (role=CUSTOMER) keyed by the hotspot username,
  * a ``Subscription`` (SubscriptionType.HOTSPOT) keyed by
    (organization, user, router, type) — a repeat purchase RENEWS it,
  * for DIRECT purchases only, a ``Payment`` (status COMPLETED) carrying the
    treasury reference — the revenue event.

Voucher REDEEM intentionally creates NO Payment: the money moved (and revenue was
recognized) when the voucher was SOLD, so recording a Payment again on redeem
would double-count. Redeem still creates/renews the User + Subscription so the
redeemed customer shows on Customers/Users/Expiry.

Idempotency: every write is an upsert keyed off stable identifiers (hotspot
username / treasury reference), so a webhook re-delivery, a poll+NATS race, or a
re-redeem never duplicates a User, Subscription or Payment.

Kept as a standalone service (not inlined into the already-large portal routers)
to keep those modules under the size budget and to share the exact same logic
between the post-payment path and the voucher-redeem path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Payment, PaymentMethod, PaymentStatus
from app.models.organization import Organization
from app.models.plan import ServicePlan
from app.models.router import Router
from app.models.subscription import (
    Subscription,
    SubscriptionStatus,
    SubscriptionType,
)
from app.models.user import User, UserRole, UserStatus

logger = logging.getLogger(__name__)


def _plan_window_hours(plan: ServicePlan) -> float:
    """Effective access window for a plan (single source of truth, defensive)."""
    try:
        return float(plan.access_window_hours() or 0.0)
    except Exception:
        return float((plan.validity_days or 0) * 24)


async def _resolve_router_id(db: AsyncSession, organization: Organization) -> Optional[int]:
    """The org's active router id (Subscription.router_id is NOT NULL)."""
    res = await db.execute(
        select(Router.id).where(
            Router.organization_id == organization.id,
            Router.is_active == True,  # noqa: E712
        ).limit(1)
    )
    return res.scalar_one_or_none()


async def _upsert_customer_user(
    db: AsyncSession,
    organization: Organization,
    *,
    hotspot_username: str,
    hotspot_password_hash: str,
    phone: Optional[str],
    email: Optional[str],
) -> Optional[User]:
    """Create / fetch a lightweight customer User for a hotspot customer.

    Keyed by (organization, username=hotspot_username) so a repeat purchase by the
    same hotspot identity reuses the row. ``User.email`` and ``User.phone`` are
    globally UNIQUE, so we MUST NOT blindly write a customer's real phone/email
    (two captive customers, or a customer who is also an ISP user, would collide
    and 500 the provisioning). We therefore synthesize guaranteed-unique
    placeholder email/phone derived from the (already unique) hotspot username and
    keep the real phone on the CustomerPurchase/Payment. The dashboard Customers
    page lists username; richer contact remains on the purchase record.
    """
    res = await db.execute(
        select(User).where(
            User.organization_id == organization.id,
            User.username == hotspot_username,
        )
    )
    user = res.scalar_one_or_none()
    if user is not None:
        return user

    synthetic_email = f"{hotspot_username.lower()}@hotspot.{organization.slug}.local"
    user = User(
        organization_id=organization.id,
        username=hotspot_username,
        # Unique placeholders (real contact lives on the purchase/payment). Never
        # write the customer's real phone/email here — those columns are unique.
        email=synthetic_email,
        phone=None,
        first_name="Hotspot",
        last_name=hotspot_username,
        hashed_password=hotspot_password_hash,
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    try:
        await db.flush()
    except Exception as exc:  # extremely unlikely (race) — fetch the winner
        logger.warning("hotspot bridge: user upsert race for %s: %s", hotspot_username, exc)
        await db.rollback()
        res = await db.execute(
            select(User).where(
                User.organization_id == organization.id,
                User.username == hotspot_username,
            )
        )
        user = res.scalar_one_or_none()
    return user


async def _upsert_subscription(
    db: AsyncSession,
    organization: Organization,
    *,
    user: User,
    plan: ServicePlan,
    router_id: int,
    username: str,
    password_hash: str,
    expires_at: datetime,
) -> Subscription:
    """Create or RENEW the hotspot Subscription for this customer.

    Keyed by the model's natural key (user_id, router_id, subscription_type) — the
    same UniqueConstraint PPPoE relies on — so a repeat purchase RENEWS in place
    (refreshes plan/end_date/status) instead of duplicating.
    """
    res = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.router_id == router_id,
            Subscription.subscription_type == SubscriptionType.HOTSPOT,
        ).limit(1)
    )
    sub = res.scalar_one_or_none()
    now = datetime.utcnow()

    if sub is not None:
        # Renew: extend from the later of now / current end_date is not needed for
        # hotspot (per-purchase window); set the fresh window the customer just
        # bought and re-activate.
        sub.plan_id = plan.id
        sub.organization_id = organization.id
        sub.status = SubscriptionStatus.ACTIVE
        sub.start_date = now
        sub.end_date = expires_at
        sub.username = username
        sub.password = password_hash
        sub.last_activity = now
        sub.updated_at = now
        return sub

    sub = Subscription(
        organization_id=organization.id,
        user_id=user.id,
        plan_id=plan.id,
        router_id=router_id,
        subscription_type=SubscriptionType.HOTSPOT,
        status=SubscriptionStatus.ACTIVE,
        username=username,
        password=password_hash,
        start_date=now,
        end_date=expires_at,
    )
    db.add(sub)
    await db.flush()
    return sub


async def _maybe_create_payment(
    db: AsyncSession,
    organization: Organization,
    *,
    user: User,
    amount,
    currency: str,
    reference: Optional[str],
    method: str,
) -> Optional[Payment]:
    """Create a COMPLETED Payment for a DIRECT purchase (idempotent by reference).

    Mirrors the PPPoE/treasury payment record. NOT called for voucher redeems
    (revenue was recognized at voucher SALE — see module docstring). Idempotent on
    ``reference_number`` so webhook re-delivery / poll+NATS race never double-counts.
    """
    if reference:
        res = await db.execute(
            select(Payment).where(
                Payment.reference_number == reference,
                Payment.organization_id == organization.id,
            ).limit(1)
        )
        if res.scalar_one_or_none() is not None:
            return None  # already recorded

    payment_number = reference or f"HSP-{organization.id}-{int(datetime.utcnow().timestamp())}"
    pm = PaymentMethod.MPESA if (method or "").lower() == "mpesa" else PaymentMethod.OTHER

    payment = Payment(
        organization_id=organization.id,
        user_id=user.id,
        payment_number=payment_number,
        amount=amount,
        currency=currency or "KES",
        payment_method=pm,
        status=PaymentStatus.COMPLETED,
        reference_number=reference,
        payment_date=datetime.utcnow(),
        notes="Hotspot package purchase",
    )
    db.add(payment)
    await db.flush()
    return payment


async def bridge_hotspot_purchase_to_dashboard(
    db: AsyncSession,
    organization: Organization,
    plan: ServicePlan,
    *,
    hotspot_username: str,
    hotspot_password_hash: str,
    expires_at: datetime,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    amount=None,
    currency: str = "KES",
    payment_reference: Optional[str] = None,
    payment_method: str = "treasury",
    is_voucher_redeem: bool = False,
) -> None:
    """Idempotently mirror a hotspot purchase/redeem into User+Subscription(+Payment).

    Called AFTER the existing CustomerSession/CustomerPurchase + router create_user
    logic, from BOTH the post-payment provisioning (NATS consumer + poll fallback)
    and the voucher-redeem path. Fully guarded — a failure here must NEVER break
    the customer's connectivity (the captive flow already succeeded), so all errors
    are swallowed and logged.

    :param is_voucher_redeem: when True, no Payment is created (the voucher SALE was
        the revenue event; recording another Payment would double-count).
    """
    try:
        router_id = await _resolve_router_id(db, organization)
        if router_id is None:
            # Subscription.router_id is NOT NULL — without a router we cannot
            # create the dashboard subscription. Skip gracefully (the customer is
            # still provisioned via the session/voucher path).
            logger.warning(
                "hotspot bridge: no active router for org %s — skipping dashboard "
                "Subscription for %s", organization.id, hotspot_username,
            )
            return

        user = await _upsert_customer_user(
            db,
            organization,
            hotspot_username=hotspot_username,
            hotspot_password_hash=hotspot_password_hash,
            phone=phone,
            email=email,
        )
        if user is None:
            logger.warning(
                "hotspot bridge: could not resolve customer User for %s — skipping",
                hotspot_username,
            )
            return

        await _upsert_subscription(
            db,
            organization,
            user=user,
            plan=plan,
            router_id=router_id,
            username=hotspot_username,
            password_hash=hotspot_password_hash,
            expires_at=expires_at,
        )

        if not is_voucher_redeem and amount is not None:
            await _maybe_create_payment(
                db,
                organization,
                user=user,
                amount=amount,
                currency=currency,
                reference=payment_reference,
                method=payment_method,
            )

        # This bridge is invoked AFTER the caller has already committed the
        # critical voucher/session/purchase rows, so it owns + commits ONLY its own
        # dashboard rows. Committing here (rather than relying on the caller) means
        # a constraint failure rolls back ONLY the bridge's work, never the
        # already-persisted customer provisioning.
        await db.commit()
        logger.info(
            "hotspot bridge: mirrored %s (org %s) into User/Subscription%s",
            hotspot_username,
            organization.id,
            "" if is_voucher_redeem else "/Payment",
        )
    except Exception as exc:  # MUST never break provisioning
        logger.error(
            "hotspot bridge: failed to mirror %s into dashboard (non-fatal): %s",
            hotspot_username,
            exc,
        )
        try:
            await db.rollback()
        except Exception:
            pass
