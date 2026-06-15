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
    auth.tenant.*               → upsert the local Organization (ISP provider)
                                  keyed by auth_tenant_id; keeps Organization.uuid
                                  == auth tenant UUID for treasury/subscriptions
                                  tenant-scoping. auth-api is the SoT.
    auth.user.*                 → upsert the local User (the ISP user) from the
                                  auth-api identity event, reusing the SSO JIT
                                  mapping (provision_sso_user). Idempotent.
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
    SUB_AUTH_TENANT,
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


async def handle_auth_tenant(envelope: Dict[str, Any]) -> None:
    """Mirror an ISP-provider tenant from an auth.tenant.created/updated event.

    auth-api is the SoT for tenants. We upsert a local ``Organization`` keyed by
    ``auth_tenant_id`` (the auth tenant UUID). To keep treasury/subscriptions
    tenant-scoping aligned, the local ``Organization.uuid`` is set to the SAME
    auth tenant UUID — so the local uuid IS the auth tenant UUID.

    Only ISP-use-case tenants are mirrored: auth-api is multi-product, so a
    non-isp ``use_case`` is ignored here (other services consume those).
    Idempotent: a redelivery just refreshes name/slug. Never raises out (the
    callback naks on exception for redelivery).
    """
    import uuid as uuidlib
    from datetime import datetime, timedelta

    from app.models.organization import (
        Organization,
        OrganizationStatus,
        OrganizationType,
    )

    p = _payload(envelope)
    auth_tenant_id = (
        p.get("tenant_id") or p.get("id") or envelope.get("tenant_id") or envelope.get("aggregate_id")
    )
    if not auth_tenant_id:
        logger.info("auth.tenant.*: no tenant_id in payload — skipping")
        return
    auth_tenant_id = str(auth_tenant_id)

    name = p.get("name") or p.get("tenant_name") or "ISP Provider"
    slug = (p.get("slug") or p.get("tenant_slug") or "").strip().lower() or None
    use_case = (p.get("use_case") or "").strip().lower()

    # auth-api is multi-product; only mirror ISP tenants. Empty use_case is
    # treated as ISP-eligible (older events may omit it) — adjust if auth-api
    # always stamps a use_case.
    if use_case and use_case not in ("isp", "isp_billing", "ispbilling", "internet", "hotspot", "hotspot_business", "pppoe"):
        logger.info(
            "auth.tenant.*: ignoring non-isp tenant %s (use_case=%s)",
            auth_tenant_id,
            use_case,
        )
        return

    # Coerce the auth tenant UUID into a real UUID for the Organization.uuid
    # column (kept in sync so treasury/subscriptions tenant-scoping lines up).
    try:
        tenant_uuid = uuidlib.UUID(auth_tenant_id)
    except (ValueError, TypeError):
        logger.warning("auth.tenant.*: tenant_id %s is not a valid UUID — skipping", auth_tenant_id)
        return

    async with AsyncSessionLocal() as db:
        # 1) Match by auth_tenant_id, then by uuid (covers an org created before
        #    this column existed whose uuid already equals the auth tenant id).
        res = await db.execute(
            select(Organization).where(Organization.auth_tenant_id == auth_tenant_id)
        )
        org: Optional[Organization] = res.scalar_one_or_none()
        if org is None:
            res = await db.execute(
                select(Organization).where(Organization.uuid == tenant_uuid)
            )
            org = res.scalar_one_or_none()
        # 3) Fall back to slug (links a pre-existing local org to its auth tenant).
        if org is None and slug:
            res = await db.execute(
                select(Organization).where(Organization.slug == slug)
            )
            org = res.scalar_one_or_none()

        if org is not None:
            changed = False
            if org.auth_tenant_id != auth_tenant_id:
                org.auth_tenant_id = auth_tenant_id
                changed = True
            # Keep the local uuid == auth tenant uuid for tenant scoping.
            if str(org.uuid) != str(tenant_uuid):
                org.uuid = tenant_uuid
                changed = True
            if name and org.name != name:
                org.name = name
                changed = True
            if slug and org.slug != slug:
                # Only adopt the auth slug if it is not already taken by another org.
                existing = await db.execute(
                    select(Organization).where(
                        Organization.slug == slug, Organization.id != org.id
                    )
                )
                if existing.scalar_one_or_none() is None:
                    org.slug = slug
                    changed = True
            if changed:
                await db.commit()
                logger.info(
                    "auth.tenant.*: synced Organization %s (auth_tenant_id=%s)",
                    org.id,
                    auth_tenant_id,
                )
            else:
                logger.info(
                    "auth.tenant.*: Organization %s already in sync (auth_tenant_id=%s)",
                    org.id,
                    auth_tenant_id,
                )
            return

        # 4) Create a fresh local Organization (the ISP HQ). De-dupe slug/email.
        base_slug = slug or f"isp-{auth_tenant_id[:8]}"
        final_slug = base_slug
        suffix = 1
        while True:
            exists = await db.execute(
                select(Organization).where(Organization.slug == final_slug)
            )
            if exists.scalar_one_or_none() is None:
                break
            final_slug = f"{base_slug}-{suffix}"[:100]
            suffix += 1

        org = Organization(
            uuid=tenant_uuid,  # local uuid == auth tenant uuid (tenant scoping)
            auth_tenant_id=auth_tenant_id,
            name=name,
            slug=final_slug,
            organization_type=OrganizationType.HOTSPOT,
            status=OrganizationStatus.TRIAL,
            email=p.get("contact_email") or f"{final_slug}@sso.local",
            phone=p.get("contact_phone"),
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
        )
        db.add(org)
        await db.commit()
        logger.info(
            "auth.tenant.*: created local Organization %s (auth_tenant_id=%s slug=%s)",
            org.id,
            auth_tenant_id,
            final_slug,
        )
        # NOTE: isp-billing has no separate Outlet/Branch model — the
        # Organization itself is the ISP HQ, and network nodes are Routers
        # (provisioned later). So there is no default-HQ-outlet row to create.

        # Auto-assign the default ISP plan (KES 500 ISP_HOTSPOT_STARTER) with its
        # 14-day free trial via subscriptions-api. Best-effort — onboarding must
        # never fail because subscriptions-api is briefly unavailable; the tenant
        # can be (re)subscribed later. The plan's free_trial_days=14 drives the
        # trial; generate_invoice is left off so no charge is raised during trial.
        try:
            from app.services.subscriptions_client import get_subscriptions_client

            sub_client = get_subscriptions_client()
            if sub_client.is_configured:
                await sub_client.subscribe(
                    auth_tenant_id, "ISP_HOTSPOT_STARTER", start_trial=True
                )
                logger.info(
                    "auth.tenant.*: auto-subscribed %s to ISP_HOTSPOT_STARTER (14-day trial)",
                    auth_tenant_id,
                )
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning(
                "auth.tenant.*: auto-subscribe failed for %s: %s", auth_tenant_id, exc
            )


async def handle_auth_user(envelope: Dict[str, Any]) -> None:
    """Upsert the local ISP User from an auth.user.created/updated event.

    auth-api is the SoT for users. We reuse the SSO JIT mapping
    (``provision_sso_user``) by translating the event payload into the same
    claims shape, so create + link + role-mapping logic is shared with the
    on-first-API-call SSO path. Idempotent: re-running links/refreshes by
    ``auth_service_user_id`` (then email) and never duplicates. Never raises out
    of the handler (the callback naks on exception for redelivery).
    """
    from app.core.sso import provision_sso_user

    p = _payload(envelope)
    auth_user_id = p.get("user_id") or p.get("id") or envelope.get("aggregate_id")
    email = (p.get("email") or "").strip().lower() or None
    if not auth_user_id and not email:
        logger.info("auth.user.*: no user_id/email in payload — skipping")
        return

    # Translate the auth.user.* payload into the SSO-claims shape that
    # provision_sso_user expects. tenant_slug/tenant_id let it resolve + link the
    # local Organization (which handle_auth_tenant keeps in sync, uuid == auth
    # tenant id), so the user is attached to the right org.
    claims: Dict[str, Any] = {
        "sub": str(auth_user_id) if auth_user_id else None,
        "email": email,
        "full_name": p.get("full_name") or p.get("name"),
        "roles": p.get("roles") or [],
        "tenant_id": p.get("tenant_id") or envelope.get("tenant_id"),
        "tenant_slug": p.get("tenant_slug"),
        "is_platform_owner": bool(p.get("is_platform_owner")),
    }

    async with AsyncSessionLocal() as db:
        user = await provision_sso_user(db, claims)
        logger.info(
            "auth.user.*: upserted local user %s (auth_id=%s org=%s)",
            user.id,
            auth_user_id,
            user.organization_id,
        )


async def handle_subscription(envelope: Dict[str, Any]) -> None:
    """subscription.* — no-op/log placeholder for now (Phase 5 scope)."""
    logger.info(
        "subscription event received (event_type=%s) — no-op for now",
        envelope.get("event_type"),
    )


# Map a consumed subject pattern → (durable suffix, async handler).
_ROUTES = [
    (SUB_TREASURY_PAYMENT_SUCCEEDED, "treasury-payment", handle_treasury_payment_succeeded),
    (SUB_AUTH_TENANT, "auth-tenant", handle_auth_tenant),
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
