"""Standalone durable NATS consumer (Phase 5, ADDITIVE).

Run as a NEW, separate process (NOT inside the API web pod):

    python -m app.events.consumer

It binds DURABLE JetStream consumers (so it is multi-replica-safe: each event is
delivered once to the durable group, not once per pod) to:

    treasury.payment.succeeded  → find the CustomerPurchase by treasury intent id
                                  (fallback: reference_id) and run the EXISTING
                                  _process_successful_payment provisioning.
                                  IDEMPOTENT — already-completed purchases are
                                  skipped, so a redelivery never double-provisions.
    auth.user.*                 → best-effort upsert/sync of the local User
                                  (the ISP user) from the auth-api identity event.
    subscription.*              → no-op / log for now (placeholder for later).

This is the PRIMARY confirmation path when NATS is configured. The Phase-2
treasury payment/status POLLING in app/api/v1/portal/hotspot.py is intentionally
left intact as the FALLBACK — both run the same idempotent
_process_successful_payment, so whichever fires first wins and the other no-ops.

Import-safety: ``nats`` is imported lazily inside ``main`` so this module is
importable (e.g. for ``python -c "import app.events.consumer"``) even when
nats-py is absent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.events import (
    SUB_AUTH_USER,
    SUB_SUBSCRIPTION,
    SUB_TREASURY_PAYMENT_SUCCEEDED,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Envelope helpers
# ──────────────────────────────────────────────────────────────────────────
def _decode(data: bytes) -> Dict[str, Any]:
    """Parse a NATS message body into the shared envelope dict (tolerant)."""
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {}


def _payload(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the payload, accepting both shared-events (``payload``) and
    CloudEvents (``data``) shapes for robustness."""
    if isinstance(envelope.get("payload"), dict):
        return envelope["payload"]
    if isinstance(envelope.get("data"), dict):
        return envelope["data"]
    return {}


# ──────────────────────────────────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────────────────────────────────
async def handle_treasury_payment_succeeded(envelope: Dict[str, Any]) -> None:
    """Provision on a confirmed treasury payment (idempotent).

    Resolves the local CustomerPurchase by treasury intent id first, then by
    reference_id, then by the local payment_reference — covering treasury's
    several id fields. Runs the unchanged _process_successful_payment, which is
    safe to re-run (already-completed purchases short-circuit).
    """
    from app.api.v1.portal.hotspot import _process_successful_payment
    from app.models.customer_portal import CustomerPurchase
    from app.models.organization import Organization

    p = _payload(envelope)
    intent_id = p.get("intent_id") or p.get("id") or envelope.get("aggregate_id")
    reference = p.get("reference_id") or p.get("reference")

    async with AsyncSessionLocal() as db:
        purchase: Optional[CustomerPurchase] = None

        if intent_id:
            res = await db.execute(
                select(CustomerPurchase).where(
                    CustomerPurchase.treasury_payment_intent_id == str(intent_id)
                )
            )
            purchase = res.scalar_one_or_none()

        if purchase is None and reference:
            res = await db.execute(
                select(CustomerPurchase).where(
                    CustomerPurchase.payment_reference == str(reference)
                )
            )
            purchase = res.scalar_one_or_none()

        if purchase is None:
            logger.info(
                "treasury.payment.succeeded: no matching CustomerPurchase "
                "(intent_id=%s reference=%s) — ignoring (likely not an isp payment)",
                intent_id,
                reference,
            )
            return

        # Idempotency: already provisioned → no-op (consumer redelivery / poller race).
        if purchase.payment_status == "completed":
            logger.info(
                "treasury.payment.succeeded: purchase %s already completed — skipping",
                purchase.id,
            )
            return

        org_res = await db.execute(
            select(Organization).where(Organization.id == purchase.organization_id)
        )
        organization = org_res.scalar_one_or_none()
        if organization is None:
            logger.warning(
                "treasury.payment.succeeded: organization %s for purchase %s not found",
                purchase.organization_id,
                purchase.id,
            )
            return

        logger.info(
            "treasury.payment.succeeded: provisioning purchase %s (org %s)",
            purchase.id,
            organization.id,
        )
        await _process_successful_payment(db, purchase, organization)


async def handle_auth_user(envelope: Dict[str, Any]) -> None:
    """Best-effort sync of the local User (ISP user) from an auth.user.* event.

    Links/updates by ``auth_service_user_id`` (the central SSO subject), falling
    back to email. NEVER creates duplicates and never raises out of the handler.
    Mirrors the lightweight identity-sync other services do; purely additive.
    """
    from datetime import datetime

    from app.models.user import User

    p = _payload(envelope)
    auth_user_id = p.get("user_id") or p.get("id") or envelope.get("aggregate_id")
    email = (p.get("email") or "").strip().lower() or None
    if not auth_user_id and not email:
        return

    async with AsyncSessionLocal() as db:
        user: Optional[User] = None
        if auth_user_id:
            res = await db.execute(
                select(User).where(User.auth_service_user_id == str(auth_user_id))
            )
            user = res.scalar_one_or_none()
        if user is None and email:
            res = await db.execute(select(User).where(User.email == email))
            user = res.scalar_one_or_none()

        if user is None:
            # No local user to link. We do NOT auto-create accounts here (account
            # creation stays with the existing SSO JIT path on first API call) —
            # this consumer only keeps already-known users in sync. Log and skip.
            logger.info(
                "auth.user.*: no local user for auth_id=%s email=%s — skipping sync",
                auth_user_id,
                email,
            )
            return

        changed = False
        if auth_user_id and not user.auth_service_user_id:
            user.auth_service_user_id = str(auth_user_id)
            changed = True
        full_name = p.get("full_name") or p.get("name")
        if full_name and not (user.first_name and user.last_name):
            parts = str(full_name).split(" ", 1)
            user.first_name = user.first_name or parts[0]
            user.last_name = user.last_name or (parts[1] if len(parts) > 1 else parts[0])
            changed = True
        if changed:
            user.auth_synced_at = datetime.utcnow()
            await db.commit()
            logger.info("auth.user.*: synced local user %s (auth_id=%s)", user.id, auth_user_id)


async def handle_subscription(envelope: Dict[str, Any]) -> None:
    """subscription.* — no-op/log placeholder for now (Phase 5 scope)."""
    logger.info(
        "subscription event received (event_type=%s) — no-op for now",
        envelope.get("event_type"),
    )


# Map a consumed subject pattern → (durable suffix, async handler).
_ROUTES = [
    (SUB_TREASURY_PAYMENT_SUCCEEDED, "treasury-payment", handle_treasury_payment_succeeded),
    (SUB_AUTH_USER, "auth-user", handle_auth_user),
    (SUB_SUBSCRIPTION, "subscription", handle_subscription),
]


# ──────────────────────────────────────────────────────────────────────────
# Subscription wiring
# ──────────────────────────────────────────────────────────────────────────
async def _make_cb(handler):
    """Wrap a handler into a JetStream message callback that ack/naks safely."""

    async def _cb(msg):
        envelope = _decode(msg.data)
        try:
            await handler(envelope)
            await msg.ack()
        except Exception as exc:
            logger.error(
                "handler error on subject %s: %s — nak for redelivery",
                getattr(msg, "subject", "?"),
                exc,
            )
            try:
                await msg.nak()
            except Exception:
                pass

    return _cb


async def run() -> None:
    """Connect, bind durable consumers, and block until signalled."""
    from app.events.nats import connect, jetstream, nats_available, nats_enabled

    if not nats_enabled():
        logger.error("NATS_URL is not set — consumer has nothing to connect to. Exiting.")
        return
    if not nats_available():
        logger.error(
            "nats-py is not installed in this image — cannot run the consumer. "
            "Add 'nats-py' to requirements.txt and rebuild."
        )
        return

    # Layer-2 settle buffer to dodge the JetStream 'consumer already bound' race
    # when a replica is replaced during a rolling redeploy.
    settle = max(0, int(settings.nats_rebind_settle_seconds))
    if settle:
        logger.info("waiting %ss before binding durables (rebind settle)", settle)
        await asyncio.sleep(settle)

    nc = await connect()
    if nc is None:
        logger.error("could not connect to NATS — consumer exiting")
        return

    js = await jetstream(nc)

    for subject, suffix, handler in _ROUTES:
        durable = f"{settings.nats_durable_name}-{suffix}"
        cb = await _make_cb(handler)
        try:
            # Durable push subscription with an explicit queue group == durable
            # name: multi-replica-safe (one delivery per group), manual ack.
            await js.subscribe(
                subject,
                durable=durable,
                queue=durable,
                cb=cb,
                manual_ack=True,
            )
            logger.info("bound durable consumer %s → subject %s", durable, subject)
        except Exception as exc:
            logger.error("failed to bind durable %s on %s: %s", durable, subject, exc)

    logger.info("isp-billing NATS consumer running")

    # Block until terminated.
    stop = asyncio.Event()

    def _signal(*_a):
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal)
            except NotImplementedError:  # Windows
                pass
    except Exception:
        pass

    await stop.wait()
    logger.info("isp-billing NATS consumer shutting down")
    try:
        await nc.drain()
    except Exception:
        try:
            await nc.close()
        except Exception:
            pass


def main() -> None:
    """Entrypoint for ``python -m app.events.consumer``."""
    from app.core.logging import setup_logging

    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
