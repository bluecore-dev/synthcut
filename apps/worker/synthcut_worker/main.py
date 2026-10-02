"""Worker process (spec §30-31, §44).

    python -m synthcut_worker            # queues/concurrency from WORKER_* env

Each slot thread claims one job at a time. While a job runs, a heartbeat
thread renews its lease and relays progress, cancellation requests and lease
loss. On SIGTERM the worker stops claiming, gives running jobs a grace period
and hands back whatever is still running without charging an attempt.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from synthcut_core.db import make_sync_engine, make_sync_sessionmaker
from synthcut_core.events import commit_and_publish_sync
from synthcut_core.jobs import (
    ClaimedJob,
    claim,
    complete,
    enqueue,
    fail,
    heartbeat,
    mark_cancelled,
    reap_expired,
    release,
)
from synthcut_core.redis import make_sync_redis, wake_channel
from synthcut_core.settings import Settings, get_settings
from synthcut_schemas.enums import JobPriority, JobQueue
from synthcut_schemas.jobs import JobKind
from synthcut_storage import Storage, StorageConfig
from synthcut_telemetry import setup_logging

from .context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from .registry import HandlerSpec, load_handlers

log = logging.getLogger("synthcut.worker")

REAP_EVERY_SECONDS = 30
SCHEDULE_EVERY_SECONDS = 60
SHUTDOWN_GRACE_SECONDS = 45

# kind -> period in seconds. Each period bucket enqueues at most one job
# (idempotency key ``kind@bucket``), however many schedulers are running.
PERIODIC: dict[str, int] = {
    JobKind.EXPIRE_UPLOADS: 15 * 60,
    JobKind.SWEEP_ORPHAN_UPLOADS: 6 * 3600,
    JobKind.PRUNE_JOBS: 24 * 3600,
}


class Worker:
    def __init__(self, settings: Settings, *, worker_id: str | None = None) -> None:
        self.settings = settings
        self.id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.handlers: dict[str, HandlerSpec] = load_handlers()
        self.queues = settings.queues()
        self.kinds = sorted(k for k, h in self.handlers.items() if h.queue.value in self.queues)
        self.engine = make_sync_engine(settings.database_url, pool_size=settings.worker_concurrency + 3)
        self.Session = make_sync_sessionmaker(self.engine)
        self.redis = make_sync_redis(settings.redis_url)
        self.storage = Storage(
            StorageConfig(
                endpoint_internal=settings.s3_endpoint_internal,
                endpoint_public=settings.s3_endpoint_public,
                region=settings.s3_region,
                bucket=settings.s3_bucket,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            )
        )
        self.stop = threading.Event()
        self.wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self._running: dict[Any, ClaimedJob] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle

    def run(self) -> None:
        log.info("worker starting", extra={"worker": self.id, "queues": self.queues, "kinds": self.kinds})
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.request_stop())
        self._spawn(self._listen_wakeups, "wakeups")
        self._spawn(self._maintenance_loop, "maintenance")
        slots = [self._spawn(self._slot_loop, f"slot-{i}") for i in range(self.settings.worker_concurrency)]
        while not self.stop.is_set():
            self.stop.wait(1.0)
        deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
        for t in slots:
            t.join(timeout=max(0.0, deadline - time.monotonic()))
        log.info("worker stopped", extra={"worker": self.id})

    def request_stop(self) -> None:
        self.stop.set()
        self.wake.set()

    def _spawn(self, target, name: str) -> threading.Thread:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)
        return t

    # ------------------------------------------------------------------ claiming

    def _listen_wakeups(self) -> None:
        channels = [wake_channel(q) for q in self.queues]
        while not self.stop.is_set():
            pubsub = None
            try:
                pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(*channels)
                while not self.stop.is_set():
                    if pubsub.get_message(timeout=1.0):
                        self.wake.set()
            except Exception:
                log.warning("wakeup listener lost Redis; polling continues", exc_info=True)
                self.stop.wait(5.0)
            finally:
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:
                        log.debug("pubsub close failed", exc_info=True)

    def _slot_loop(self) -> None:
        while not self.stop.is_set():
            job = self._claim()
            if job is None:
                self.wake.wait(timeout=self.settings.worker_poll_seconds)
                self.wake.clear()
                continue
            self._run(job)

    def _claim(self) -> ClaimedJob | None:
        if not self.kinds:
            return None
        try:
            with self.Session() as s:
                job = claim(
                    s,
                    owner=self.id,
                    queues=self.queues,
                    kinds=self.kinds,
                    lease_seconds=self.settings.worker_lease_seconds,
                )
                commit_and_publish_sync(s, self.redis)
                return job
        except Exception:
            log.exception("claim failed")
            self.stop.wait(3.0)
            return None

    # ------------------------------------------------------------------ running

    def _heartbeat_loop(self, ctx: JobContext, done: threading.Event) -> None:
        interval = max(2.0, self.settings.worker_lease_seconds / 3)
        while not done.wait(interval):
            try:
                with self.Session() as s:
                    hb = heartbeat(
                        s,
                        job_id=ctx.job.id,
                        owner=ctx.job.owner,
                        lease_seconds=self.settings.worker_lease_seconds,
                        progress=ctx.progress_value,
                        message=ctx.progress_message,
                    )
                    s.commit()
            except Exception:
                log.warning("heartbeat failed", extra={"job_id": str(ctx.job.id)}, exc_info=True)
                continue
            if not hb.owned:
                ctx.lost.set()
                return
            if hb.cancel_requested:
                ctx.cancel.set()

    def _run(self, job: ClaimedJob) -> None:
        spec = self.handlers[job.kind]
        ctx = JobContext(
            job,
            settings=self.settings,
            storage=self.storage,
            redis_client=self.redis,
            session_factory=self.Session,
            shutdown=self.stop,
        )
        done = threading.Event()
        beat = threading.Thread(
            target=self._heartbeat_loop, args=(ctx, done), name=f"hb-{job.id}", daemon=True
        )
        beat.start()
        started = time.monotonic()
        outcome, result, error = "failed", None, None
        retryable = True
        try:
            payload = spec.payload_model.model_validate(job.payload)
            result = spec.fn(ctx, payload) or {}
            outcome = "succeeded"
        except ValidationError as exc:
            error, retryable = exc, False
        except JobCancelled:
            outcome = "cancelled"
        except JobInterrupted:
            outcome = "interrupted"
        except LeaseLost:
            outcome = "lost"
        except PermanentError as exc:
            error, retryable = exc, False
        except RetryableError as exc:
            error, retryable = exc, True
        except Exception as exc:
            error, retryable = exc, True
            log.exception("job crashed", extra={"job_id": str(job.id), "kind": job.kind})
        finally:
            done.set()
            beat.join(timeout=5)
            ctx.cleanup()

        if ctx.lost.is_set() or outcome == "lost":
            log.warning("lease lost; result discarded", extra={"job_id": str(job.id), "kind": job.kind})
            return
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            with self.Session() as s:
                if outcome == "succeeded":
                    complete(s, job, {**(result or {}), "duration_ms": duration_ms})
                elif outcome == "cancelled":
                    mark_cancelled(s, job)
                elif outcome == "interrupted":
                    release(s, job)
                else:
                    fail(
                        s,
                        job,
                        error_type=type(error).__name__,
                        message=str(error) or type(error).__name__,
                        retryable=retryable,
                    )
                commit_and_publish_sync(s, self.redis)
        except Exception:
            log.exception("could not record job outcome; the lease will expire and the job retry")
        log.info(
            "job finished",
            extra={"job_id": str(job.id), "kind": job.kind, "outcome": outcome, "duration_ms": duration_ms},
        )

    # ------------------------------------------------------------------ maintenance

    def _maintenance_loop(self) -> None:
        last_reap = last_schedule = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            if now - last_reap >= REAP_EVERY_SECONDS:
                last_reap = now
                try:
                    with self.Session() as s:
                        n = reap_expired(s, source=f"reaper:{self.id}")
                        commit_and_publish_sync(s, self.redis)
                    if n:
                        log.warning("recovered jobs with expired leases", extra={"count": n})
                        self.wake.set()
                except Exception:
                    log.exception("reaper failed")
            if self.settings.worker_scheduler and now - last_schedule >= SCHEDULE_EVERY_SECONDS:
                last_schedule = now
                self.schedule_periodic()
            self.stop.wait(5.0)

    def schedule_periodic(self, at: datetime | None = None) -> int:
        moment = at or datetime.now(UTC)
        created = 0
        try:
            with self.Session() as s:
                for kind, period in PERIODIC.items():
                    bucket = int(moment.timestamp()) // period
                    _, new = enqueue(
                        s,
                        kind=kind,
                        queue=JobQueue.IO,
                        priority=JobPriority.LOW,
                        idempotency_key=f"{kind}@{bucket}",
                        max_attempts=2,
                    )
                    created += int(new)
                commit_and_publish_sync(s, self.redis)
        except Exception:
            log.exception("scheduler failed")
        return created


def main() -> None:  # pragma: no cover - container entry point
    settings = get_settings()
    setup_logging("worker", settings.log_level)
    Worker(settings).run()
