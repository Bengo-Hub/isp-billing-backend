"""Transactional-outbox write + publish helpers (Phase 5, ADDITIVE).

Two halves:

1. WRITE side — ``record_event(db, ...)`` adds an ``OutboxEvent`` row to the
   caller's SQLAlchemy session. The caller commits it in the SAME transaction
   as the domain change, so the event is durably tied to the business fact.
   This NEVER calls NATS, so it is safe even when nats-py is absent.

2. PUBLISH side — ``publish_pending(...)`` reads unpublished rows, publishes
   each to JetStream with the shared event envelope/subject, and stamps
   ``published_at``. Driven by a Celery beat task (~every 5s). When NATS is not
   configured/installed it no-ops, so rows simply accumulate harmlessly until
   eventing is enabled.

Envelope (matches shared-events Event):
    {id, event_type, aggregate_type, aggregate_id, tenant_id, payload,
     timestamp, version}
Subject = "{aggregate_type}.{event_type}"  e.g. "isp.payment.received".
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import AGGREGATE_TYPE
from app.models.outbox import OutboxEvent

logger = logging.getLogger(__name__)

# Stop retrying a row after this many failed publish attempts (poison guard).
MAX_PUBLISH_ATTEMPTS = 10
# Batch size for the poller.
PUBLISH_BATCH = 100


def record_event(
    db: AsyncSession,
    *,
    event_type: str,
    payload: Dict[str, Any],
    tenant_id: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    aggregate_type: str = AGGREGATE_TYPE,
) -> OutboxEvent:
    """Add an outbox row to ``db`` (the caller commits in its own transaction).

    Returns the (unflushed) ``OutboxEvent`` so callers can reference it. Does
    NOT commit — that is the caller's job so the event shares the domain
    transaction. Tolerant of being called when NATS is off (the row just waits).
    """
    evt = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id) if aggregate_id is not None else None,
        event_type=event_type,
        payload=payload,
        tenant_id=str(tenant_id) if tenant_id is not None else None,
        created_at=datetime.utcnow(),
        attempts=0,
    )
    db.add(evt)
    return evt


def _envelope(evt: OutboxEvent) -> bytes:
    """Serialise an outbox row into the shared-events JSON envelope."""
    body = {
        "id": str(uuid.uuid4()),
        "event_type": evt.event_type,
        "aggregate_type": evt.aggregate_type,
        "aggregate_id": evt.aggregate_id,
        "tenant_id": evt.tenant_id,
        "payload": evt.payload or {},
        "timestamp": (evt.created_at or datetime.utcnow()).isoformat() + "Z",
        "version": "1.0",
    }
    return json.dumps(body).encode("utf-8")


async def publish_pending(db: AsyncSession, limit: int = PUBLISH_BATCH) -> int:
    """Publish unpublished outbox rows to JetStream; return count published.

    No-ops (returns 0) when NATS is not configured or nats-py is unavailable —
    so the existing flows are unaffected and rows wait for eventing to come up.
    Opens one NATS connection for the batch and drains it at the end.
    """
    from app.events.nats import connect, ensure_stream, jetstream, nats_enabled

    if not nats_enabled():
        return 0

    # Fetch a bounded batch of pending rows, oldest first, under the attempt cap.
    result = await db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .where(OutboxEvent.attempts < MAX_PUBLISH_ATTEMPTS)
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0

    nc = await connect()
    if nc is None:
        return 0

    published = 0
    try:
        js = await jetstream(nc)
        await ensure_stream(js)
        for evt in rows:
            subject = f"{evt.aggregate_type}.{evt.event_type}"
            try:
                await js.publish(subject, _envelope(evt))
                evt.published_at = datetime.utcnow()
                published += 1
                logger.info("published outbox event id=%s subject=%s", evt.id, subject)
            except Exception as exc:
                evt.attempts = (evt.attempts or 0) + 1
                logger.warning(
                    "failed to publish outbox event id=%s subject=%s (attempt %s): %s",
                    evt.id,
                    subject,
                    evt.attempts,
                    exc,
                )
        await db.commit()
    finally:
        try:
            await nc.drain()
        except Exception:
            try:
                await nc.close()
            except Exception:
                pass

    return published
