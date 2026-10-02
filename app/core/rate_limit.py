"""Redis-backed rate limiting for public credential endpoints.

State lives in Redis, so the limit holds across every backend replica. Each hit is one atomic
Lua call (INCR, set the window TTL on the first hit, return the remaining TTL when over the
limit), so concurrent requests cannot slip past the count and a key can never lose its TTL.

Two layers are applied on login-like routes:
  * per client IP, from RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW seconds. Kept generous because
    hotspot customers of one ISP often share a single public IP (CGNAT).
  * per account or code (username, email, voucher), strict, so one account cannot be guessed
    no matter how many addresses the attacker uses.

RATE_LIMIT_ENABLED=false turns both off. A Redis outage lets requests through (logged), so a
cache problem never locks customers out of the portal.
"""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# Strict per-identifier limit: attempts per window for one account, email or code.
IDENTIFIER_LIMIT = 10
IDENTIFIER_WINDOW_SECONDS = 300

_HIT_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
if n > tonumber(ARGV[1]) then
  local ttl = redis.call('PTTL', KEYS[1])
  if ttl < 0 then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    ttl = tonumber(ARGV[2])
  end
  return ttl
end
return -1
"""


def client_ip(request: Request) -> str:
    """Client IP. ingress-nginx sets X-Real-IP from Cloudflare's CF-Connecting-IP, which the
    client cannot forge; the first X-Forwarded-For hop can be forged and is never used."""
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    return request.client.host if request.client else "unknown"


async def enforce(key: str, limit: int, window_seconds: int) -> None:
    """Count one hit on key; raise 429 with Retry-After once limit is exceeded in the window."""
    if not settings.rate_limit_enabled:
        return
    try:
        if not redis_client.redis:
            await redis_client.connect()
        ttl_ms = await redis_client.redis.eval(
            _HIT_SCRIPT, 1, "isp:rl:" + key, limit, window_seconds * 1000
        )
    except Exception as exc:  # Redis down: let the request through
        logger.warning("rate limit check skipped (redis unavailable): %s", exc)
        return
    if ttl_ms is not None and int(ttl_ms) >= 0:
        retry_after = max(1, -(-int(ttl_ms) // 1000))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(retry_after)},
        )


async def limit_credential_attempt(
    request: Request, scope: str, identifier: Optional[str] = None
) -> None:
    """Apply the per-IP and (when given) per-identifier limits for a credential endpoint."""
    await enforce(
        f"{scope}:ip:{client_ip(request)}",
        settings.rate_limit_requests,
        settings.rate_limit_window,
    )
    if identifier:
        await enforce(
            f"{scope}:id:{identifier.strip().lower()}",
            IDENTIFIER_LIMIT,
            IDENTIFIER_WINDOW_SECONDS,
        )
