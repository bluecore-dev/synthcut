"""Emitting project events (spec §32, §43).

Persisted events are written in the caller's transaction and published to
Redis only *after* the commit succeeds, so a live subscriber can never see an
event whose transaction rolled back. Use :func:`commit_and_publish` (async) or
:func:`commit_and_publish_sync` instead of a bare ``commit()`` whenever events
were emitted.

Ephemeral events (progress ticks) skip the database entirely.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import redis
import redis.asyncio as aioredis
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from synthcut_schemas.enums import EventLevel
from synthcut_schemas.events import EPHEMERAL_EVENT_TYPES, EventEnvelope

from .models import Event, utcnow
from .redis import project_channel, wake_channel

log = logging.getLogger(__name__)

_PENDING = "sc_pending_events"
_WAKE = "sc_wake_queues"


@sa_event.listens_for(Session, "after_rollback")
def _drop_pending_on_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)
    session.info.pop(_WAKE, None)


def mark_wake(session: Session | AsyncSession, queue: str) -> None:
    """Ring the queue's doorbell once the current transaction commits."""
    session.info.setdefault(_WAKE, set()).add(queue)


def emit(
    session: Session | AsyncSession,
    *,
    project_id: uuid.UUID | None,
    type: str,
    message: str,
    source: str,
    level: EventLevel = EventLevel.INFO,
    data: dict[str, Any] | None = None,
    job_id: uuid.UUID | None = None,
) -> Event:
    """Add a persisted event to the session; it is published after commit."""
    if type in EPHEMERAL_EVENT_TYPES:
        raise ValueError(f"{type} is ephemeral; use publish_ephemeral")
    ev = Event(
        project_id=project_id,
        type=type,
        level=level.value,
        source=source,
        message=message,
        data=data or {},
        job_id=job_id,
        created_at=utcnow(),
    )
    session.add(ev)
    session.info.setdefault(_PENDING, []).append(ev)
    return ev


def _serialize(ev: Event) -> str:
    return EventEnvelope.model_validate(ev).model_dump_json()


def _ephemeral(
    project_id: uuid.UUID,
    type: str,
    message: str,
    source: str,
    data: dict[str, Any] | None,
    job_id: uuid.UUID | None,
) -> str:
    return EventEnvelope(
        id=None,
        project_id=project_id,
        type=type,
        level=EventLevel.DEBUG,
        source=source,
        message=message,
        data=data or {},
        job_id=job_id,
        created_at=utcnow(),
    ).model_dump_json()


def _outbox(session: Session | AsyncSession) -> list[tuple[str, str]]:
    messages = [
        (project_channel(ev.project_id), _serialize(ev))
        for ev in session.info.pop(_PENDING, [])
        if ev.project_id is not None
    ]
    messages += [(wake_channel(q), "1") for q in sorted(session.info.pop(_WAKE, set()))]
    return messages


async def commit_and_publish(session: AsyncSession, client: aioredis.Redis | None) -> None:
    await session.commit()
    messages = _outbox(session)
    if not client:
        return
    for channel, payload in messages:
        try:
            await client.publish(channel, payload)
        except Exception:  # Redis is a doorbell; the event is safe in PostgreSQL
            log.warning("event publish failed", extra={"channel": channel}, exc_info=True)
            return


def commit_and_publish_sync(session: Session, client: redis.Redis | None) -> None:
    session.commit()
    messages = _outbox(session)
    if not client:
        return
    for channel, payload in messages:
        try:
            client.publish(channel, payload)
        except Exception:
            log.warning("event publish failed", extra={"channel": channel}, exc_info=True)
            return


async def publish_ephemeral(
    client: aioredis.Redis | None,
    *,
    project_id: uuid.UUID,
    type: str,
    message: str,
    source: str,
    data: dict[str, Any] | None = None,
    job_id: uuid.UUID | None = None,
) -> None:
    if not client:
        return
    try:
        await client.publish(
            project_channel(project_id), _ephemeral(project_id, type, message, source, data, job_id)
        )
    except Exception:
        log.debug("ephemeral publish failed", exc_info=True)


def publish_ephemeral_sync(
    client: redis.Redis | None,
    *,
    project_id: uuid.UUID,
    type: str,
    message: str,
    source: str,
    data: dict[str, Any] | None = None,
    job_id: uuid.UUID | None = None,
) -> None:
    if not client:
        return
    try:
        client.publish(
            project_channel(project_id), _ephemeral(project_id, type, message, source, data, job_id)
        )
    except Exception:
        log.debug("ephemeral publish failed", exc_info=True)
