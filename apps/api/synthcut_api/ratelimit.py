"""Fixed-window rate limiting in Redis. Fails open: if Redis is unavailable
the request proceeds, because the real gate (HMAC / token) is elsewhere."""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from .errors import ApiError

log = logging.getLogger(__name__)


async def rate_limit(client: aioredis.Redis | None, key: str, *, limit: int, window_seconds: int) -> None:
    if client is None:
        return
    redis_key = f"sc:rl:{key}"
    try:
        count = await client.incr(redis_key)
        if count == 1:
            await client.expire(redis_key, window_seconds)
    except Exception:
        log.warning("rate limiter unavailable", exc_info=True)
        return
    if count > limit:
        raise ApiError(429, "rate_limited", "Juda ko'p so'rov — biroz kuting")
