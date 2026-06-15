"""Transactional outbox model (Phase 5, ADDITIVE).

Mirrors the estate's shared-events outbox pattern (Go ``outbox_events``): a domain
operation writes an ``OutboxEvent`` row inside the SAME DB transaction as the
business change, and a background poller (a Celery beat task) publishes the
unpublished rows to NATS JetStream and stamps ``published_at``.

The envelope written to NATS matches the shared Event shape:
``{id, event_type, aggregate_type, aggregate_id, tenant_id, payload, timestamp,
version}`` and the subject is ``{aggregate_type}.{event_type}`` — so an isp
``payment.received`` event is published on subject ``isp.payment.received``.

This table is entirely independent of the existing schema; nothing reads or
writes it unless the Phase-5 publisher/consumer is wired in, so it is safe to
add ahead of enabling NATS.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class OutboxEvent(Base):
    """A single pending/published domain event in the transactional outbox."""

    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, index=True)

    # aggregate_type + event_type → NATS subject ("{aggregate_type}.{event_type}").
    # For isp-billing this is always aggregate_type="isp" (subjects like
    # isp.payment.received, isp.subscriber.created, isp.invoice.created).
    aggregate_type = Column(String(64), nullable=False, default="isp")
    aggregate_id = Column(String(128), nullable=True)  # e.g. purchase id / voucher id
    event_type = Column(String(128), nullable=False)  # e.g. "payment.received"

    # JSON event payload (domain fields). JSONB for efficient storage/indexing.
    payload = Column(JSONB, nullable=False)

    # Tenant scoping: the ISP Organization.uuid as a string (matches the shared
    # envelope tenant_id, which is a UUID). Nullable so platform-level events
    # (no tenant) can still be emitted.
    tenant_id = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    # NULL until the poller successfully publishes the row to NATS.
    published_at = Column(DateTime, nullable=True, index=True)
    # Publish attempt counter (incremented on each failed publish; the poller
    # stops retrying after a cap to avoid hot-looping a poison row).
    attempts = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<OutboxEvent(id={self.id}, subject="
            f"'{self.aggregate_type}.{self.event_type}', "
            f"published={self.published_at is not None})>"
        )
