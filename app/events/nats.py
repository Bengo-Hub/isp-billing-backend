"""Lazy NATS / JetStream connection helpers (nats-py).

All ``nats`` imports happen INSIDE functions so that importing this module (and
therefore ``app.main`` / the Celery worker) never requires ``nats-py`` to be
installed. When ``settings.nats_url`` is empty the helpers return ``None`` and
callers treat the event subsystem as inert.

The JetStream stream that carries this service's published subjects
(``isp.>``) is ensured idempotently via ``ensure_stream`` so a fresh
environment does not need a manual ``nats stream add``. We DO NOT create or
manage streams owned by other services (treasury/auth/subscription) — we only
bind durable consumers to them, which JetStream allows against an existing
stream.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def nats_enabled() -> bool:
    """True when a NATS URL is configured (the event subsystem is active)."""
    return bool(settings.nats_url)


def nats_available() -> bool:
    """True when nats-py is importable in this environment.

    Used to log a clear, actionable message (rather than crash) when NATS is
    configured but the dependency is missing from the image.
    """
    try:
        import nats  # noqa: F401

        return True
    except Exception:  # pragma: no cover - depends on image
        return False


async def connect() -> Optional[Any]:
    """Open a NATS connection, or return ``None`` when NATS is not usable.

    Returns the ``nats.aio.client.Client`` on success. Callers must close it
    (``await nc.drain()`` / ``await nc.close()``). Never raises on a missing
    dependency or empty config — those degrade to ``None`` so the caller can
    no-op (additive / fail-open).
    """
    if not nats_enabled():
        return None
    if not nats_available():
        logger.warning(
            "NATS_URL is set (%s) but nats-py is not installed in this image; "
            "event publishing/consuming is disabled. Add 'nats-py' to "
            "requirements.txt and rebuild to enable Phase-5 eventing.",
            settings.nats_url,
        )
        return None

    import nats

    try:
        nc = await nats.connect(
            settings.nats_url,
            name=settings.nats_connection_name,
            max_reconnect_attempts=-1,  # reconnect forever
            reconnect_time_wait=2,
        )
        return nc
    except Exception as exc:  # connection failure → inert, don't crash caller
        logger.warning("failed to connect to NATS at %s: %s", settings.nats_url, exc)
        return None


async def jetstream(nc: Any) -> Any:
    """Return the JetStream context for an open connection."""
    return nc.jetstream()


async def ensure_stream(js: Any) -> None:
    """Idempotently ensure the ``isp`` stream exists, capturing ``isp.>``.

    Best-effort: if stream management is restricted or the stream already
    exists with a different (compatible) config, we log and continue — the
    important guarantee is that publishing ``isp.*`` does not fail because the
    stream is missing on a fresh environment.
    """
    from nats.js.api import StreamConfig, RetentionPolicy

    stream = settings.nats_stream_name
    subject = f"{stream}.>"
    try:
        await js.stream_info(stream)
        return  # already exists
    except Exception:
        pass

    try:
        await js.add_stream(
            StreamConfig(
                name=stream,
                subjects=[subject],
                retention=RetentionPolicy.LIMITS,
            )
        )
        logger.info("ensured JetStream stream %s (subjects=%s)", stream, subject)
    except Exception as exc:  # pragma: no cover - server policy dependent
        logger.warning("could not ensure JetStream stream %s: %s", stream, exc)
