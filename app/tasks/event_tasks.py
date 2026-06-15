"""Event-bus Celery tasks (Phase 5, ADDITIVE).

Hosts the transactional-outbox publisher poller. Runs on the existing Celery
beat infra (~every 5s) and drains unpublished ``outbox_events`` rows to NATS
JetStream. Entirely inert when ``settings.nats_url`` is empty or nats-py is not
installed — it simply publishes 0 rows and returns, so it is safe to schedule
unconditionally and never interferes with existing flows.
"""

import asyncio

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.tasks.event_tasks.publish_outbox_events")
def publish_outbox_events(self):
    """Publish pending outbox rows to NATS JetStream (no-op when NATS is off)."""
    try:
        async def _run() -> int:
            # Lazy import keeps the task module importable without nats-py.
            from app.events.outbox import publish_pending

            async with AsyncSessionLocal() as db:
                return await publish_pending(db)

        count = asyncio.run(_run())
        if count:
            logger.info("outbox publisher published %s event(s)", count)
        return {"published": count}
    except Exception as exc:  # never let a publish error wedge the beat loop
        logger.error("outbox publisher failed: %s", exc)
        return {"published": 0, "error": str(exc)}
