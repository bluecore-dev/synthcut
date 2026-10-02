"""What a running job handler gets: its job, project-scoped helpers, a scratch
directory and cooperative cancellation."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import redis
from sqlalchemy.orm import Session, sessionmaker
from synthcut_core.events import commit_and_publish_sync, emit, publish_ephemeral_sync
from synthcut_core.jobs import ClaimedJob
from synthcut_core.settings import Settings
from synthcut_schemas.enums import EventLevel
from synthcut_schemas.events import EventType
from synthcut_storage import Storage


class RetryableError(RuntimeError):
    """Transient failure: the job is retried with backoff."""


class PermanentError(RuntimeError):
    """The job cannot succeed as specified: it is marked dead immediately."""


class JobCancelled(RuntimeError):
    pass


class JobInterrupted(RuntimeError):
    """The worker is shutting down; the job is handed back without counting an attempt."""


class LeaseLost(RuntimeError):
    """Another worker owns this job now; stop and discard the result."""


class JobContext:
    def __init__(
        self,
        job: ClaimedJob,
        *,
        settings: Settings,
        storage: Storage,
        redis_client: redis.Redis | None,
        session_factory: sessionmaker[Session],
        shutdown: threading.Event,
    ) -> None:
        self.job = job
        self.settings = settings
        self.storage = storage
        self.redis = redis_client
        self._session_factory = session_factory
        self.shutdown = shutdown
        self.cancel = threading.Event()
        self.lost = threading.Event()
        self.progress_value: float | None = None
        self.progress_message: str | None = None
        self._last_progress_publish = 0.0
        self._scratch: Path | None = None

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._session_factory() as s:
            yield s

    def check(self) -> None:
        """Call between steps of long work."""
        if self.lost.is_set():
            raise LeaseLost(str(self.job.id))
        if self.cancel.is_set():
            raise JobCancelled(str(self.job.id))
        if self.shutdown.is_set():
            raise JobInterrupted(str(self.job.id))

    def progress(self, fraction: float, message: str | None = None) -> None:
        self.progress_value = max(0.0, min(1.0, fraction))
        self.progress_message = message
        now = time.monotonic()
        if self.job.project_id is not None and now - self._last_progress_publish >= 1.0:
            self._last_progress_publish = now
            publish_ephemeral_sync(
                self.redis,
                project_id=self.job.project_id,
                type=EventType.JOB_PROGRESS,
                message=message or "progress",
                source="worker",
                data={"kind": self.job.kind, "progress": self.progress_value},
                job_id=self.job.id,
            )

    def emit(
        self,
        type: str,
        message: str,
        *,
        level: EventLevel = EventLevel.INFO,
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.job.project_id is None:
            return
        with self.session() as s:
            emit(
                s,
                project_id=self.job.project_id,
                type=type,
                message=message,
                source="worker",
                level=level,
                data=data,
                job_id=self.job.id,
            )
            commit_and_publish_sync(s, self.redis)

    @property
    def scratch_dir(self) -> Path:
        """NVMe scratch for this job only (spec §8); removed when the job ends."""
        if self._scratch is None:
            scope = str(self.job.project_id or "system")
            path = Path(self.settings.scratch_dir) / scope / str(self.job.id)
            path.mkdir(parents=True, exist_ok=True)
            self._scratch = path
        return self._scratch

    def cleanup(self) -> None:
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)
