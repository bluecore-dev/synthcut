"""Durable job queue on PostgreSQL (ADR-0002).

Guarantees (spec §44):

* **No lost jobs** — enqueueing is part of the caller's transaction.
* **No duplicate jobs** — ``idempotency_key`` is UNIQUE; enqueueing the same
  logical work twice returns the existing job.
* **One runner at a time** — a job is claimed with ``FOR UPDATE SKIP LOCKED``
  and held under a lease that the runner renews with heartbeats.
* **Fenced writes** — completion, failure and heartbeats only apply while the
  caller still owns the lease, so a worker that stalled past its lease cannot
  overwrite the result of the worker that took over.
* **Recovery** — expired leases are reaped back to ``queued`` (or ``dead``
  once attempts are exhausted).
* **Rolling upgrades** — a worker only claims kinds it has handlers for, so a
  job enqueued for a later phase simply waits for a worker that knows it.

Handlers must be idempotent: a crash between a handler's own commit and the
completion write means the job runs again.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from synthcut_schemas.enums import EventLevel, JobPriority, JobQueue, JobStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import job_label

from .events import emit, mark_wake
from .ids import new_id
from .models import Job, utcnow

RETRY_BASE_SECONDS = 15
RETRY_CAP_SECONDS = 600


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    queue: str
    project_id: uuid.UUID | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    idempotency_key: str | None
    owner: str


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    owned: bool
    cancel_requested: bool


# --------------------------------------------------------------------------- enqueue


def _insert(
    *,
    kind: str,
    queue: JobQueue,
    payload: dict[str, Any] | None,
    project_id: uuid.UUID | None,
    priority: JobPriority,
    idempotency_key: str | None,
    max_attempts: int,
    run_after: datetime | None,
    parent_id: uuid.UUID | None,
):
    now = utcnow()
    return (
        pg_insert(Job)
        .values(
            id=new_id(),
            kind=kind,
            queue=queue.value,
            priority=int(priority),
            status=JobStatus.QUEUED.value,
            project_id=project_id,
            idempotency_key=idempotency_key,
            payload=payload or {},
            attempts=0,
            max_attempts=max_attempts,
            run_after=run_after or now,
            parent_id=parent_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        .returning(Job.id)
    )


def _queued_event(
    session: Session | AsyncSession, job_id: uuid.UUID, kind: str, project_id: uuid.UUID | None
):
    if project_id is not None:
        emit(
            session,
            project_id=project_id,
            type=EventType.JOB_QUEUED,
            message=f"{job_label(kind)}: navbatga qo'yildi",
            source="queue",
            data={"kind": kind},
            job_id=job_id,
        )


def enqueue(
    session: Session,
    *,
    kind: str,
    queue: JobQueue,
    payload: dict[str, Any] | None = None,
    project_id: uuid.UUID | None = None,
    priority: JobPriority = JobPriority.NORMAL,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    run_after: datetime | None = None,
    parent_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, bool]:
    """Insert a job in the caller's transaction. Returns ``(job_id, created)``."""
    stmt = _insert(
        kind=kind,
        queue=queue,
        payload=payload,
        project_id=project_id,
        priority=priority,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        run_after=run_after,
        parent_id=parent_id,
    )
    job_id = session.execute(stmt).scalar_one_or_none()
    if job_id is None:
        existing = session.execute(select(Job.id).where(Job.idempotency_key == idempotency_key)).scalar_one()
        return existing, False
    _queued_event(session, job_id, kind, project_id)
    mark_wake(session, queue.value)
    return job_id, True


async def enqueue_async(
    session: AsyncSession,
    *,
    kind: str,
    queue: JobQueue,
    payload: dict[str, Any] | None = None,
    project_id: uuid.UUID | None = None,
    priority: JobPriority = JobPriority.NORMAL,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    run_after: datetime | None = None,
    parent_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, bool]:
    stmt = _insert(
        kind=kind,
        queue=queue,
        payload=payload,
        project_id=project_id,
        priority=priority,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        run_after=run_after,
        parent_id=parent_id,
    )
    job_id = (await session.execute(stmt)).scalar_one_or_none()
    if job_id is None:
        existing = (
            await session.execute(select(Job.id).where(Job.idempotency_key == idempotency_key))
        ).scalar_one()
        return existing, False
    _queued_event(session, job_id, kind, project_id)
    mark_wake(session, queue.value)
    return job_id, True


# --------------------------------------------------------------------------- claim / lease

_CLAIM = text(
    """
    UPDATE jobs SET
        status = 'running',
        lease_owner = :owner,
        lease_expires_at = now() + (:lease * interval '1 second'),
        heartbeat_at = now(),
        attempts = attempts + 1,
        started_at = COALESCE(started_at, now()),
        progress = NULL,
        progress_message = NULL,
        updated_at = now()
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
          AND queue = ANY(:queues)
          AND kind = ANY(:kinds)
          AND run_after <= now()
        ORDER BY priority, run_after, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, queue, project_id, payload, attempts, max_attempts, idempotency_key
    """
)


def claim(
    session: Session, *, owner: str, queues: list[str], kinds: list[str], lease_seconds: int
) -> ClaimedJob | None:
    """Claim the most urgent runnable job. Caller commits."""
    if not queues or not kinds:
        return None
    row = session.execute(
        _CLAIM, {"owner": owner, "lease": lease_seconds, "queues": queues, "kinds": kinds}
    ).one_or_none()
    if row is None:
        return None
    job = ClaimedJob(
        id=row.id,
        kind=row.kind,
        queue=row.queue,
        project_id=row.project_id,
        payload=dict(row.payload or {}),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        idempotency_key=row.idempotency_key,
        owner=owner,
    )
    if job.project_id is not None:
        emit(
            session,
            project_id=job.project_id,
            type=EventType.JOB_STARTED,
            message=f"{job_label(job.kind)}: boshlandi (urinish {job.attempts}/{job.max_attempts})",
            source=f"worker:{owner}",
            data={"kind": job.kind, "attempt": job.attempts},
            job_id=job.id,
        )
    return job


_HEARTBEAT = text(
    """
    UPDATE jobs SET
        lease_expires_at = now() + (:lease * interval '1 second'),
        heartbeat_at = now(),
        progress = COALESCE(:progress, progress),
        progress_message = COALESCE(:message, progress_message),
        updated_at = now()
    WHERE id = :id AND lease_owner = :owner AND status = 'running'
    RETURNING cancel_requested
    """
)


def heartbeat(
    session: Session,
    *,
    job_id: uuid.UUID,
    owner: str,
    lease_seconds: int,
    progress: float | None = None,
    message: str | None = None,
) -> HeartbeatResult:
    row = session.execute(
        _HEARTBEAT,
        {"id": job_id, "owner": owner, "lease": lease_seconds, "progress": progress, "message": message},
    ).one_or_none()
    if row is None:
        return HeartbeatResult(owned=False, cancel_requested=False)
    return HeartbeatResult(owned=True, cancel_requested=bool(row.cancel_requested))


# --------------------------------------------------------------------------- finish


def complete(session: Session, job: ClaimedJob, result: dict[str, Any] | None = None) -> bool:
    stmt = (
        update(Job)
        .where(Job.id == job.id, Job.lease_owner == job.owner, Job.status == JobStatus.RUNNING.value)
        .values(
            status=JobStatus.SUCCEEDED.value,
            result=result,
            error=None,
            progress=1.0,
            finished_at=utcnow(),
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    ok = session.execute(stmt).rowcount == 1
    if ok and job.project_id is not None:
        emit(
            session,
            project_id=job.project_id,
            type=EventType.JOB_SUCCEEDED,
            message=f"{job_label(job.kind)}: bajarildi",
            source=f"worker:{job.owner}",
            data={"kind": job.kind},
            job_id=job.id,
        )
    return ok


_FAIL = text(
    """
    UPDATE jobs SET
        status = CASE WHEN :retryable AND attempts < max_attempts THEN 'queued' ELSE 'dead' END,
        run_after = CASE WHEN :retryable AND attempts < max_attempts
            THEN now() + (LEAST(:base * power(4, attempts - 1), :cap) * interval '1 second')
            ELSE run_after END,
        finished_at = CASE WHEN :retryable AND attempts < max_attempts THEN NULL ELSE now() END,
        error = CAST(:error AS jsonb),
        lease_owner = NULL,
        lease_expires_at = NULL,
        updated_at = now()
    WHERE id = :id AND lease_owner = :owner AND status = 'running'
    RETURNING status, attempts, max_attempts, run_after
    """
)


def fail(
    session: Session,
    job: ClaimedJob,
    *,
    error_type: str,
    message: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> str | None:
    """Record a failure. Returns the new status (``queued`` = will retry,
    ``dead`` = gave up) or ``None`` if the lease was lost meanwhile."""
    error = {"type": error_type, "message": message[:2000], "retryable": retryable, **(details or {})}
    row = session.execute(
        _FAIL,
        {
            "id": job.id,
            "owner": job.owner,
            "retryable": retryable,
            "base": RETRY_BASE_SECONDS,
            "cap": RETRY_CAP_SECONDS,
            "error": json.dumps(error),
        },
    ).one_or_none()
    if row is None:
        return None
    if job.project_id is not None:
        if row.status == JobStatus.QUEUED.value:
            delay = max(0, int((row.run_after - utcnow()).total_seconds()))
            emit(
                session,
                project_id=job.project_id,
                type=EventType.JOB_RETRYING,
                level=EventLevel.WARNING,
                message=f"{job_label(job.kind)}: xato, {delay}s dan keyin qayta urinish — {message[:200]}",
                source=f"worker:{job.owner}",
                data={"kind": job.kind, "attempt": row.attempts, "error": error},
                job_id=job.id,
            )
        else:
            emit(
                session,
                project_id=job.project_id,
                type=EventType.JOB_FAILED,
                level=EventLevel.ERROR,
                message=f"{job_label(job.kind)}: muvaffaqiyatsiz — {message[:200]}",
                source=f"worker:{job.owner}",
                data={"kind": job.kind, "attempt": row.attempts, "error": error},
                job_id=job.id,
            )
    return str(row.status)


def mark_cancelled(session: Session, job: ClaimedJob) -> bool:
    stmt = (
        update(Job)
        .where(Job.id == job.id, Job.lease_owner == job.owner, Job.status == JobStatus.RUNNING.value)
        .values(
            status=JobStatus.CANCELLED.value, finished_at=utcnow(), lease_owner=None, lease_expires_at=None
        )
    )
    ok = session.execute(stmt).rowcount == 1
    if ok and job.project_id is not None:
        emit(
            session,
            project_id=job.project_id,
            type=EventType.JOB_CANCELLED,
            level=EventLevel.WARNING,
            message=f"{job_label(job.kind)}: bekor qilindi",
            source=f"worker:{job.owner}",
            data={"kind": job.kind},
            job_id=job.id,
        )
    return ok


def release(session: Session, job: ClaimedJob) -> bool:
    """Hand a job back without counting the attempt (graceful shutdown)."""
    stmt = (
        update(Job)
        .where(Job.id == job.id, Job.lease_owner == job.owner, Job.status == JobStatus.RUNNING.value)
        .values(
            status=JobStatus.QUEUED.value,
            attempts=Job.attempts - 1,
            run_after=utcnow(),
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    return session.execute(stmt).rowcount == 1


def request_cancel(session: Session, job_id: uuid.UUID) -> str | None:
    """Cancel a queued job immediately or ask a running one to stop."""
    job = session.get(Job, job_id, with_for_update=True)
    if job is None:
        return None
    if job.status == JobStatus.QUEUED.value:
        job.status = JobStatus.CANCELLED.value
        job.finished_at = utcnow()
    elif job.status == JobStatus.RUNNING.value:
        job.cancel_requested = True
    return job.status


# --------------------------------------------------------------------------- recovery

_REAP = text(
    """
    UPDATE jobs SET
        status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
        finished_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END,
        run_after = now() + interval '5 seconds',
        error = jsonb_build_object(
            'type', 'LeaseExpired',
            'message', 'worker stopped heartbeating (crash or restart)',
            'retryable', true,
            'lease_owner', lease_owner),
        lease_owner = NULL,
        lease_expires_at = NULL,
        updated_at = now()
    WHERE status = 'running' AND lease_expires_at < now() - (:grace * interval '1 second')
    RETURNING id, kind, status, project_id, attempts, max_attempts
    """
)


def reap_expired(session: Session, *, grace_seconds: int = 10, source: str = "reaper") -> int:
    rows = session.execute(_REAP, {"grace": grace_seconds}).all()
    for row in rows:
        if row.project_id is None:
            continue
        dead = row.status == JobStatus.DEAD.value
        emit(
            session,
            project_id=row.project_id,
            type=EventType.JOB_FAILED if dead else EventType.JOB_RETRYING,
            level=EventLevel.ERROR if dead else EventLevel.WARNING,
            message=(
                f"{job_label(row.kind)}: worker javob bermay qoldi — "
                + ("urinishlar tugadi" if dead else "qayta navbatga qo'yildi")
            ),
            source=source,
            data={"kind": row.kind, "attempt": row.attempts, "recovered": True},
            job_id=row.id,
        )
    return len(rows)
