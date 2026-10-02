"""Redis: the doorbell and the loudspeaker, never the ledger (spec §42).

* ``sc:events:project:<id>`` — live fan-out of project events to SSE clients.
* ``sc:jobs:wake:<queue>``  — wakes idle workers when a job is enqueued.
* ``sc:rl:*``               — rate-limit counters.

Everything here is disposable: if Redis restarts, SSE clients replay from the
events table and workers fall back to polling PostgreSQL.
"""

from __future__ import annotations

import uuid

import redis
import redis.asyncio as aioredis

EVENT_CHANNEL_PREFIX = "sc:events:project:"
WAKE_CHANNEL_PREFIX = "sc:jobs:wake:"


def project_channel(project_id: uuid.UUID | str) -> str:
    return f"{EVENT_CHANNEL_PREFIX}{project_id}"


def wake_channel(queue: str) -> str:
    return f"{WAKE_CHANNEL_PREFIX}{queue}"


def make_sync_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, socket_timeout=5, socket_connect_timeout=3, health_check_interval=30)


def make_async_redis(url: str) -> aioredis.Redis:
    return aioredis.Redis.from_url(url, socket_connect_timeout=3, health_check_interval=30)
