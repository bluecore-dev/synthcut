"""Server-Sent Events for the dashboard (spec §32).

The stream subscribes to the project's Redis channel *before* replaying from
PostgreSQL, so nothing falls between replay and live. Because event ids come
from an identity column, two transactions can commit out of id order; a
periodic catch-up query over a short look-back window picks up anything the
live channel missed, and a bounded set of already-sent ids prevents
duplicates. If Redis is down the stream degrades to polling the table.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import redis.asyncio as aioredis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthcut_core.models import Event
from synthcut_core.redis import project_channel
from synthcut_schemas.events import EventEnvelope

log = logging.getLogger(__name__)

LOOKBACK = timedelta(seconds=90)


def sse_frame(payload: str, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}data: {payload}\n\n"


class _SentIds:
    def __init__(self, capacity: int = 4000) -> None:
        self._order: deque[int] = deque()
        self._set: set[int] = set()
        self._capacity = capacity

    def add(self, event_id: int) -> bool:
        if event_id in self._set:
            return False
        self._order.append(event_id)
        self._set.add(event_id)
        if len(self._order) > self._capacity:
            self._set.discard(self._order.popleft())
        return True


async def _fetch_since(
    sessionmaker: async_sessionmaker[AsyncSession], project_id: uuid.UUID, after_id: int, limit: int
) -> list[Event]:
    async with sessionmaker() as session:
        if after_id <= 0:  # fresh client: the most recent events, oldest first
            rows = await session.execute(
                select(Event).where(Event.project_id == project_id).order_by(Event.id.desc()).limit(limit)
            )
            return list(reversed(list(rows.scalars())))
        anchor = (await session.execute(select(Event.created_at).where(Event.id == after_id))).scalar()
        cond = Event.id > after_id
        if anchor is not None:
            cond = or_(cond, Event.created_at > anchor - LOOKBACK)
        rows = await session.execute(
            select(Event).where(Event.project_id == project_id, cond).order_by(Event.id).limit(limit)
        )
        return list(rows.scalars())


async def project_event_stream(
    *,
    project_id: uuid.UUID,
    after_id: int,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: aioredis.Redis | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_seconds: float = 15.0,
    catchup_seconds: float = 10.0,
    replay_limit: int = 500,
) -> AsyncIterator[str]:
    sent = _SentIds()
    pubsub = None
    if redis is not None:
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(project_channel(project_id))
        except Exception:
            log.warning("redis subscribe failed; SSE falls back to polling", exc_info=True)
            pubsub = None

    last_id = after_id
    try:
        yield "retry: 3000\n\n"
        for ev in await _fetch_since(sessionmaker, project_id, after_id, replay_limit):
            if sent.add(ev.id):
                last_id = max(last_id, ev.id)
                yield sse_frame(EventEnvelope.model_validate(ev).model_dump_json(), ev.id)

        last_beat = last_catchup = time.monotonic()
        while not await is_disconnected():
            now = time.monotonic()
            if pubsub is not None:
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                except Exception:
                    log.warning("redis pubsub failed; SSE falls back to polling", exc_info=True)
                    pubsub = None
                    msg = None
                if msg and msg.get("type") == "message":
                    raw = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                    event_id = json.loads(raw).get("id")
                    if event_id is None:
                        yield sse_frame(raw)
                    elif sent.add(int(event_id)):
                        last_id = max(last_id, int(event_id))
                        yield sse_frame(raw, int(event_id))
            else:
                await asyncio.sleep(1.0)

            interval = catchup_seconds if pubsub is not None else 2.0
            if now - last_catchup >= interval:
                last_catchup = now
                for ev in await _fetch_since(sessionmaker, project_id, last_id, replay_limit):
                    if sent.add(ev.id):
                        last_id = max(last_id, ev.id)
                        yield sse_frame(EventEnvelope.model_validate(ev).model_dump_json(), ev.id)
            if now - last_beat >= heartbeat_seconds:
                last_beat = now
                yield ": ping\n\n"
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:
                log.debug("pubsub close failed", exc_info=True)
