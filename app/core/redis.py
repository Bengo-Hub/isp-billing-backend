"""Redis configuration and utilities."""

import json
from typing import Any, Optional, Union
import redis.asyncio as redis
from app.core.config import settings


class RedisClient:
    """Redis client wrapper with async support."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self.redis = redis.from_url(
            settings.redis_url,
            password=settings.redis_password,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self.redis:
            await self.redis.close()

    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        if not self.redis:
            await self.connect()
        return await self.redis.get(key)

    async def set(
        self, 
        key: str, 
        value: Union[str, dict, list], 
        expire: Optional[int] = None
    ) -> bool:
        """Set value with optional expiration."""
        if not self.redis:
            await self.connect()
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        
        return await self.redis.set(key, value, ex=expire)

    async def delete(self, key: str) -> bool:
        """Delete key."""
        if not self.redis:
            await self.connect()
        return bool(await self.redis.delete(key))

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not self.redis:
            await self.connect()
        return bool(await self.redis.exists(key))

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration for key."""
        if not self.redis:
            await self.connect()
        return await self.redis.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """Get time to live for key."""
        if not self.redis:
            await self.connect()
        return await self.redis.ttl(key)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value."""
        if not self.redis:
            await self.connect()
        return await self.redis.hget(name, key)

    async def hset(self, name: str, key: str, value: Union[str, dict, list]) -> int:
        """Set hash field value."""
        if not self.redis:
            await self.connect()
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        
        return await self.redis.hset(name, key, value)

    async def hgetall(self, name: str) -> dict:
        """Get all hash fields and values."""
        if not self.redis:
            await self.connect()
        return await self.redis.hgetall(name)

    async def hdel(self, name: str, key: str) -> int:
        """Delete hash field."""
        if not self.redis:
            await self.connect()
        return await self.redis.hdel(name, key)

    async def lpush(self, name: str, value: Union[str, dict, list]) -> int:
        """Push value to list left."""
        if not self.redis:
            await self.connect()
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        
        return await self.redis.lpush(name, value)

    async def rpop(self, name: str) -> Optional[str]:
        """Pop value from list right."""
        if not self.redis:
            await self.connect()
        return await self.redis.rpop(name)

    async def llen(self, name: str) -> int:
        """Get list length."""
        if not self.redis:
            await self.connect()
        return await self.redis.llen(name)

    async def sadd(self, name: str, value: str) -> int:
        """Add value to set."""
        if not self.redis:
            await self.connect()
        return await self.redis.sadd(name, value)

    async def srem(self, name: str, value: str) -> int:
        """Remove value from set."""
        if not self.redis:
            await self.connect()
        return await self.redis.srem(name, value)

    async def smembers(self, name: str) -> set:
        """Get all set members."""
        if not self.redis:
            await self.connect()
        return await self.redis.smembers(name)

    async def sismember(self, name: str, value: str) -> bool:
        """Check if value is in set."""
        if not self.redis:
            await self.connect()
        return bool(await self.redis.sismember(name, value))

    # ---- Pub/Sub + capped-list helpers (used by provisioning WS fan-out) ----

    async def publish(self, channel: str, message: Union[str, dict, list]) -> int:
        """Publish a message to a pub/sub channel. Returns subscriber count."""
        if not self.redis:
            await self.connect()

        if isinstance(message, (dict, list)):
            message = json.dumps(message)

        return await self.redis.publish(channel, message)

    async def lpush_capped(
        self,
        name: str,
        value: Union[str, dict, list],
        max_len: int,
        expire: Optional[int] = None,
    ) -> None:
        """LPUSH a value, trim the list to ``max_len`` newest items, set TTL.

        Used as a small replay buffer so a WS that connects slightly after a
        broadcast can still receive recent history. Index 0 is the newest item
        after LPUSH; LTRIM 0..max_len-1 keeps the newest ``max_len`` entries.
        """
        if not self.redis:
            await self.connect()

        if isinstance(value, (dict, list)):
            value = json.dumps(value)

        # Pipeline so the three ops are a single round-trip and stay consistent.
        pipe = self.redis.pipeline()
        pipe.lpush(name, value)
        pipe.ltrim(name, 0, max(0, max_len - 1))
        if expire:
            pipe.expire(name, expire)
        await pipe.execute()

    async def lrange(self, name: str, start: int = 0, end: int = -1) -> list:
        """Return a range of list elements (oldest→newest when reversed)."""
        if not self.redis:
            await self.connect()
        return await self.redis.lrange(name, start, end)

    def raw(self):
        """Return the underlying redis.asyncio client (for pubsub objects).

        Callers must ensure :meth:`connect` has run first (e.g. via
        ``await get_redis()``). Returns ``None`` if not yet connected.
        """
        return self.redis


# Global Redis client instance
redis_client = RedisClient()


async def get_redis() -> RedisClient:
    """Get Redis client instance."""
    if not redis_client.redis:
        await redis_client.connect()
    return redis_client
