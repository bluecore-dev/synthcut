"""The PostgreSQL-leased job queue and the worker (spec §30, §44)."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from synthcut_core.jobs import (
    claim,
    complete,
    enqueue,
    fail,
    heartbeat,
    reap_expired,
    release,
    request_cancel,
)
from synthcut_core.models import Event, Job, UploadSession
from synthcut_schemas.enums import JobQueue
from synthcut_worker.main import Worker

from .conftest import make_project
from .test_uploads import put_part, start_upload

KINDS = ["test.kind", "other.kind"]


def _enqueue(Session, **kw):
    with Session() as s:
        job_id, created = enqueue(
            s, kind=kw.pop("kind", "test.kind"), queue=kw.pop("queue", JobQueue.IO), **kw
        )
        s.commit()
        return job_id, created


def _claim(Session, owner="w1", queues=("io",), kinds=KINDS, lease=30):
    with Session() as s:
        job = claim(s, owner=owner, queues=list(queues), kinds=list(kinds), lease_seconds=lease)
        s.commit()
        return job


def test_idempotency_key_dedupes(Session):
    a, created_a = _enqueue(Session, idempotency_key="render:v1")
    b, created_b = _enqueue(Session, idempotency_key="render:v1")
    assert a == b and created_a and not created_b


def test_claim_respects_priority_queue_kind_and_run_after(Session):
    _enqueue(Session, priority=3)
    urgent, _ = _enqueue(Session, priority=0)
    _enqueue(Session, queue=JobQueue.CPU, priority=0)
    _enqueue(Session, kind="unknown.kind", priority=0)
    _enqueue(Session, priority=0, run_after=datetime.now(UTC) + timedelta(hours=1))
    first = _claim(Session)
    assert first.id == urgent and first.attempts == 1
    second = _claim(Session)
    assert second is not None and second.id != urgent
    assert _claim(Session) is None  # remaining: other queue, unknown kind, future


def test_concurrent_claims_never_share_a_job(Session):
    for _ in range(40):
        _enqueue(Session)
    claimed: list = []
    lock = threading.Lock()

    def worker(name):
        while (job := _claim(Session, owner=name)) is not None:
            with lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 40 and len(set(claimed)) == 40


def test_fenced_writes_after_lease_loss(Session):
    _enqueue(Session)
    job = _claim(Session, owner="slow")
    with Session() as s:  # lease expires, the reaper hands the job to someone else
        s.execute(update(Job).values(lease_expires_at=datetime.now(UTC) - timedelta(minutes=5)))
        assert reap_expired(s) == 1
        s.execute(update(Job).values(run_after=datetime.now(UTC)))  # skip the reaper's 5s cool-down
        s.commit()
    fresh = _claim(Session, owner="fast")
    assert fresh.id == job.id and fresh.attempts == 2
    with Session() as s:
        assert complete(s, job, {"from": "slow"}) is False  # zombie cannot overwrite
        assert heartbeat(s, job_id=job.id, owner="slow", lease_seconds=30).owned is False
        assert complete(s, fresh, {"from": "fast"}) is True
        s.commit()
        assert s.get(Job, job.id).result == {"from": "fast"}


def test_retry_with_backoff_then_dead(Session):
    _enqueue(Session, max_attempts=2)
    job = _claim(Session)
    with Session() as s:
        assert fail(s, job, error_type="Boom", message="transient", retryable=True) == "queued"
        s.commit()
        row = s.get(Job, job.id)
        assert row.run_after > datetime.now(UTC) + timedelta(seconds=10)  # backoff applied
        s.execute(update(Job).values(run_after=datetime.now(UTC)))
        s.commit()
    job2 = _claim(Session)
    assert job2.attempts == 2
    with Session() as s:
        assert fail(s, job2, error_type="Boom", message="again", retryable=True) == "dead"
        s.commit()


def test_permanent_failure_skips_retries(Session):
    _enqueue(Session, max_attempts=5)
    job = _claim(Session)
    with Session() as s:
        assert fail(s, job, error_type="Bad", message="invalid payload", retryable=False) == "dead"


def test_release_does_not_charge_an_attempt(Session):
    _enqueue(Session)
    job = _claim(Session)
    with Session() as s:
        assert release(s, job)
        s.commit()
    assert _claim(Session).attempts == 1


def test_cancel_queued_and_running(Session):
    queued, _ = _enqueue(Session, kind="other.kind")
    _enqueue(Session)
    running = _claim(Session, kinds=["test.kind"])
    with Session() as s:
        assert request_cancel(s, queued) == "cancelled"
        request_cancel(s, running.id)
        s.commit()
        assert heartbeat(s, job_id=running.id, owner="w1", lease_seconds=30).cancel_requested


async def test_worker_runs_maintenance_jobs_and_expires_stale_uploads(client, auth, Session, settings):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    await put_part(client, auth, session, 1)
    with Session() as s:
        s.execute(update(UploadSession).values(last_activity_at=datetime.now(UTC) - timedelta(days=3)))
        s.commit()

    worker = Worker(settings.model_copy(update={"worker_queues": "io"}), worker_id="test-worker")
    assert worker.schedule_periodic() == 3
    assert worker.schedule_periodic() == 0  # same period bucket: no duplicates
    ran = []
    while (job := worker._claim()) is not None:
        worker._run(job)
        ran.append(job.kind)
    assert sorted(ran) == [
        "maintenance.expire_uploads",
        "maintenance.prune_jobs",
        "maintenance.sweep_orphan_uploads",
    ]

    with Session() as s:
        statuses = dict(s.execute(select(Job.kind, Job.status).where(Job.project_id.is_(None))).all())
        assert set(statuses.values()) == {"succeeded"}
        expire = s.scalar(select(Job).where(Job.kind == "maintenance.expire_uploads"))
        assert expire.result["expired"] == 1
        assert s.get(UploadSession, uuid.UUID(session["id"])).status == "expired"
        types = s.scalars(select(Event.type).where(Event.project_id == uuid.UUID(project["id"]))).all()
        assert "upload.expired" in types
    # the multipart upload is gone from storage too
    r = await client.get(f"/api/v1/uploads/{session['id']}", headers=auth)
    assert r.json()["status"] == "expired"
    assets = (await client.get(f"/api/v1/projects/{project['id']}/assets", headers=auth)).json()["items"]
    assert assets[0]["status"] == "failed"


async def test_worker_leaves_unknown_kinds_queued(client, auth, Session, settings):
    """Phase 2 enqueues ingest.asset; until the Phase 3 handler ships it waits."""
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    for n in (1, 2, 3):
        await put_part(client, auth, session, n)
    await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    worker = Worker(settings, worker_id="test-worker")
    assert "ingest.asset" not in worker.kinds
    assert worker._claim() is None
    with Session() as s:
        assert s.scalar(select(Job.status).where(Job.kind == "ingest.asset")) == "queued"


def test_crashing_handler_is_retried_and_recorded(Session, settings, monkeypatch):
    from synthcut_worker import registry

    calls = []

    def boom(ctx, payload):
        calls.append(ctx.job.attempts)
        raise RuntimeError("disk on fire")

    spec = registry.HANDLERS["maintenance.prune_jobs"]
    monkeypatch.setitem(
        registry.HANDLERS,
        "maintenance.prune_jobs",
        spec.__class__(spec.kind, spec.queue, spec.payload_model, boom),
    )
    worker = Worker(settings.model_copy(update={"worker_queues": "io"}), worker_id="crashy")
    _enqueue(Session, kind="maintenance.prune_jobs", max_attempts=2)
    worker._run(worker._claim())
    with Session() as s:
        job = s.scalar(select(Job))
        assert (
            job.status == "queued"
            and job.error["type"] == "RuntimeError"
            and "disk on fire" in job.error["message"]
        )
        s.execute(text("UPDATE jobs SET run_after = now()"))
        s.commit()
    worker._run(worker._claim())
    with Session() as s:
        assert s.scalar(select(Job.status)) == "dead"
    assert calls == [1, 2]
