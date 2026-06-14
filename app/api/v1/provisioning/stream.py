"""
WebSocket endpoints for live streaming of provisioning logs.
Provides real-time updates during the provisioning process.

Multi-pod delivery
------------------
The backend runs multiple pods. A log produced on pod A must reach a WS client
connected to pod B. To achieve that, ``send_message`` does NOT write directly to
local sockets; instead it PUBLISHes the message to a Redis channel
``prov_ws:{session_id}``. A single process-wide subscriber (started at app
startup) PSUBSCRIBEs ``prov_ws:*`` and forwards each message to the LOCAL
sockets for that session. Every pod runs this subscriber, so each pod delivers
to its own clients regardless of which pod produced the log. This also makes the
subscriber the single delivery point to local sockets, avoiding double-delivery.

If Redis is unavailable, ``send_message`` falls back to delivering directly to
local sockets so single-pod / no-Redis deployments keep working.

Replay buffer
-------------
Every published message is also appended to a capped Redis list
``prov_ws_buf:{session_id}`` (newest-first, trimmed to ~100, ~1h TTL). When a WS
connects, it first drains this buffer (oldest→newest) so a client that connects
slightly after a broadcast still sees recent history.
"""
import logging
import json
import asyncio
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)
router = APIRouter()

# Store active WebSocket connections by session_id
active_connections: Dict[str, Set[WebSocket]] = {}

# Redis keys / channels for the cross-pod fan-out and replay buffer.
_CHANNEL_PREFIX = "prov_ws:"          # prov_ws:{session_id}
_CHANNEL_PATTERN = "prov_ws:*"        # PSUBSCRIBE pattern
_BUFFER_PREFIX = "prov_ws_buf:"       # prov_ws_buf:{session_id}
_BUFFER_MAX = 100                     # keep the newest N messages per session
_BUFFER_TTL = 3600                    # seconds (~1h)


class ConnectionManager:
    """Manages WebSocket connections for provisioning sessions.

    Local sockets live in ``active_connections``. Cross-pod delivery is handled
    via Redis pub/sub (see module docstring). The Redis subscriber calls
    :meth:`deliver_local` to write to this pod's sockets.
    """

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection and add it to the session."""
        await websocket.accept()

        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()

        self.active_connections[session_id].add(websocket)
        logger.info(f"WebSocket connected for session {session_id}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a WebSocket connection from the session."""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)

            # Clean up empty session
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

        logger.info(f"WebSocket disconnected for session {session_id}")

    async def deliver_local(self, session_id: str, message: dict):
        """Send a message to this pod's locally-connected sockets only.

        This is the single delivery point to local sockets. It is called by the
        Redis subscriber (normal multi-pod path) and by ``send_message`` when
        Redis is unavailable (single-pod fallback).
        """
        if session_id not in self.active_connections:
            return

        # Copy the set to avoid mutation during iteration.
        connections = self.active_connections[session_id].copy()
        payload = json.dumps(message)

        for websocket in connections:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(payload)
                else:
                    # Remove disconnected websockets
                    self.active_connections[session_id].discard(websocket)
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                self.active_connections[session_id].discard(websocket)

    async def send_message(self, session_id: str, message: dict):
        """Broadcast a message to all clients of a session, across all pods.

        Publishes to Redis (so every pod's subscriber delivers to its own local
        sockets) and appends to the replay buffer. If Redis is unavailable,
        falls back to delivering to this pod's local sockets directly so
        single-pod / no-Redis deployments keep working.

        The WS message shape is unchanged from before (callers pass the full
        ``{"type", "session_id", "data"}`` envelope).
        """
        published = False
        try:
            from app.core.redis import get_redis

            redis = await get_redis()
            channel = f"{_CHANNEL_PREFIX}{session_id}"
            await redis.publish(channel, message)
            published = True

            # Append to the capped replay buffer (best-effort; never block send).
            try:
                await redis.lpush_capped(
                    f"{_BUFFER_PREFIX}{session_id}",
                    message,
                    max_len=_BUFFER_MAX,
                    expire=_BUFFER_TTL,
                )
            except Exception as buf_err:
                logger.warning(
                    f"Replay-buffer append failed for session {session_id}: {buf_err}"
                )
        except Exception as e:
            # Redis down / not configured: keep single-pod delivery working by
            # writing straight to local sockets.
            logger.warning(
                f"Redis publish failed for session {session_id}; "
                f"falling back to local-only delivery: {e}"
            )

        if not published:
            await self.deliver_local(session_id, message)

    async def replay_buffer(self, websocket: WebSocket, session_id: str):
        """Send the buffered message history to a just-connected socket.

        Reads ``prov_ws_buf:{session_id}`` (stored newest-first via LPUSH) and
        replays it oldest→newest to the single ``websocket`` only. Best-effort:
        any failure is swallowed so a connect never fails because of replay.
        """
        try:
            from app.core.redis import get_redis

            redis = await get_redis()
            entries = await redis.lrange(f"{_BUFFER_PREFIX}{session_id}", 0, -1)
            if not entries:
                return

            # Stored newest-first → reverse to oldest-first for natural ordering.
            for raw in reversed(entries):
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
                try:
                    # Entries are already JSON strings; forward verbatim.
                    await websocket.send_text(
                        raw if isinstance(raw, str) else json.dumps(raw)
                    )
                except Exception as send_err:
                    logger.debug(
                        f"Replay send failed for session {session_id}: {send_err}"
                    )
                    break
        except Exception as e:
            logger.warning(
                f"Replay buffer fetch failed for session {session_id}: {e}"
            )

    async def broadcast_log(self, session_id: str, log_entry: dict):
        """Broadcast a log entry to all connected clients."""
        message = {
            "type": "log",
            "session_id": session_id,
            "data": log_entry
        }
        await self.send_message(session_id, message)

    async def broadcast_status(self, session_id: str, status: dict):
        """Broadcast status update to all connected clients."""
        message = {
            "type": "status",
            "session_id": session_id,
            "data": status
        }
        await self.send_message(session_id, message)


# Global connection manager instance
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Cross-pod Redis subscriber
# ---------------------------------------------------------------------------
# A single background task per process PSUBSCRIBEs prov_ws:* and forwards each
# message to local sockets. Started from the app lifespan in app/main.py.

_subscriber_task: Optional[asyncio.Task] = None
_subscriber_stop = asyncio.Event()


async def _run_subscriber() -> None:
    """Background loop: PSUBSCRIBE prov_ws:* and deliver to local sockets.

    Resilient: on any error it logs and reconnects after a short backoff. If
    Redis is never reachable it keeps retrying quietly while local-only delivery
    (the send_message fallback) keeps single-pod working.
    """
    backoff = 1
    while not _subscriber_stop.is_set():
        pubsub = None
        try:
            from app.core.redis import get_redis

            redis = await get_redis()
            raw = redis.raw()
            if raw is None:
                raise RuntimeError("Redis client not connected")

            pubsub = raw.pubsub()
            await pubsub.psubscribe(_CHANNEL_PATTERN)
            logger.info("Provisioning WS subscriber listening on %s", _CHANNEL_PATTERN)
            backoff = 1  # reset after a successful (re)connect

            while not _subscriber_stop.is_set():
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is None:
                    continue
                if msg.get("type") not in ("pmessage", "message"):
                    continue

                channel = msg.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8", "ignore")
                if not channel or not channel.startswith(_CHANNEL_PREFIX):
                    continue
                session_id = channel[len(_CHANNEL_PREFIX):]

                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "ignore")
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    logger.debug("Skipping non-JSON WS pubsub payload on %s", channel)
                    continue

                # Single delivery point to this pod's local sockets.
                await manager.deliver_local(session_id, payload)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Provisioning WS subscriber error (will retry in %ss): %s",
                backoff, e,
            )
            try:
                # Wait for either the backoff window or a stop signal.
                await asyncio.wait_for(_subscriber_stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    try:
                        await pubsub.close()
                    except Exception:
                        pass

    logger.info("Provisioning WS subscriber stopped")


async def start_ws_subscriber() -> None:
    """Start the process-wide WS pub/sub subscriber (idempotent).

    Called once from the app lifespan/startup. If Redis is unavailable the task
    still starts and retries in the background; delivery degrades to local-only
    via the send_message fallback in the meantime.
    """
    global _subscriber_task
    if _subscriber_task and not _subscriber_task.done():
        return
    _subscriber_stop.clear()
    _subscriber_task = asyncio.create_task(_run_subscriber())
    logger.info("Provisioning WS subscriber task created")


async def stop_ws_subscriber() -> None:
    """Stop the WS subscriber cleanly (called on app shutdown)."""
    global _subscriber_task
    _subscriber_stop.set()
    if _subscriber_task:
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except (asyncio.CancelledError, Exception):
            pass
        _subscriber_task = None


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for live provisioning updates."""
    await manager.connect(websocket, session_id)

    # Replay recent history so a client that connected just after a broadcast
    # (e.g. the "queued to agent" line emitted as POST /workflow returns) still
    # sees it. Guarded so a replay failure never breaks the connection.
    try:
        await manager.replay_buffer(websocket, session_id)
    except Exception as e:
        logger.warning(f"Replay buffer delivery failed for session {session_id}: {e}")

    try:
        while True:
            # Keep the connection alive and handle any incoming messages
            data = await websocket.receive_text()

            # Handle client messages if needed
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
        manager.disconnect(websocket, session_id)


# Function to broadcast provisioning updates (called by ProvisioningService)
async def broadcast_provisioning_update(session_id: str, update_type: str, data: dict):
    """Broadcast provisioning updates to connected WebSocket clients."""
    if update_type == "log":
        await manager.broadcast_log(session_id, data)
    elif update_type == "status":
        await manager.broadcast_status(session_id, data)
    elif update_type == "provisioning_complete":
        # Send a dedicated provisioning_complete message type for frontend redirect
        message = {
            "type": "provisioning_complete",
            "session_id": session_id,
            "data": data
        }
        await manager.send_message(session_id, message)


# Function to broadcast router logs (called by router monitoring)
async def broadcast_router_log(session_id: str, router_log: dict):
    """Broadcast router logs to connected WebSocket clients."""
    message = {
        "type": "router_log",
        "session_id": session_id,
        "data": router_log
    }
    await manager.send_message(session_id, message)
