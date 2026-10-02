"""Event schema (spec §32, §43).

Every observable thing that happens to a project is an event. Persisted events
form the project's activity log (PostgreSQL ``events`` table, monotonically
increasing ``id`` which doubles as the SSE ``Last-Event-ID``). Ephemeral events
(progress ticks) are only published live and are never stored.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import EventLevel


class EventType(StrEnum):
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_ARCHIVED = "project.archived"

    UPLOAD_STARTED = "upload.started"
    UPLOAD_RESUMED = "upload.resumed"
    UPLOAD_PROGRESS = "upload.progress"
    UPLOAD_COMPLETED = "upload.completed"
    UPLOAD_CANCELLED = "upload.cancelled"
    UPLOAD_EXPIRED = "upload.expired"
    UPLOAD_FAILED = "upload.failed"
    UPLOAD_CLIENT_ERROR = "upload.client_error"

    STAGE_UPDATED = "stage.updated"

    JOB_QUEUED = "job.queued"
    JOB_STARTED = "job.started"
    JOB_PROGRESS = "job.progress"
    JOB_SUCCEEDED = "job.succeeded"
    JOB_RETRYING = "job.retrying"
    JOB_FAILED = "job.failed"
    JOB_CANCELLED = "job.cancelled"


EPHEMERAL_EVENT_TYPES: frozenset[str] = frozenset({EventType.UPLOAD_PROGRESS, EventType.JOB_PROGRESS})


class EventEnvelope(BaseModel):
    """Wire format of an event, identical for the REST log and the SSE stream."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = Field(None, description="Null for ephemeral events")
    project_id: UUID | None = None
    type: str
    level: EventLevel = EventLevel.INFO
    source: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    job_id: UUID | None = None
    created_at: datetime
