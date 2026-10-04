"""ORM models — the implemented part of the ERD (docs/ERD.md).

Phase 1–2 tables: users, projects, project_stages, assets, upload_sessions,
jobs, events. Later phases add their own tables in their own migrations.

State columns are TEXT guarded by CHECK constraints generated from the enums
in ``synthcut_schemas`` — adding a state is a one-line migration, renaming one
is forbidden.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from synthcut_schemas.enums import (
    AnalysisStatus,
    AssetKind,
    AssetStatus,
    DeliveryStatus,
    EventLevel,
    JobQueue,
    JobStatus,
    PlanSource,
    ProjectStatus,
    QaStatus,
    RenderKind,
    RenderStatus,
    StageStatus,
    TranscriptStatus,
    UploadSessionStatus,
)

from .db import Base
from .ids import new_id


def utcnow() -> datetime:
    return datetime.now(UTC)


def _one_of(column: str, enum: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, server_default=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    last_seen_at: Mapped[datetime | None]


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint(_one_of("status", ProjectStatus), name="status"),
        Index("ix_projects_owner_updated", "owner_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    preset: Mapped[str] = mapped_column(Text)
    fps: Mapped[int] = mapped_column(SmallInteger, default=30, server_default=text("30"))
    target_duration_sec: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, default="auto", server_default=text("'auto'"))
    brief: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, default=ProjectStatus.ACTIVE.value, server_default=text("'active'")
    )
    archived_at: Mapped[datetime | None]


class ProjectStage(Base):
    __tablename__ = "project_stages"
    __table_args__ = (
        CheckConstraint(_one_of("status", StageStatus), name="status"),
        CheckConstraint("progress IS NULL OR (progress >= 0 AND progress <= 1)", name="progress_range"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    stage: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    progress: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, server_default=func.now())


class Asset(TimestampMixin, Base):
    """An immutable original source file inside a project (spec §7, §10)."""

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(_one_of("kind", AssetKind), name="kind"),
        CheckConstraint(_one_of("status", AssetStatus), name="status"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_assets_project_sort", "project_id", "sort_index"),
        # One in-flight upload per file per project: re-selecting the same file
        # resumes the existing multipart upload instead of starting another.
        Index(
            "uq_assets_uploading_fingerprint",
            "project_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status = 'uploading'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    extension: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    fingerprint: Mapped[str] = mapped_column(Text)
    file_last_modified: Mapped[datetime | None]
    etag: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    media_info: Mapped[dict[str, Any] | None]
    duration_sec: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    # Phase 3 (ingestion) — denormalized from media_info for listing and queries.
    video_codec: Mapped[str | None] = mapped_column(Text)
    audio_codec: Mapped[str | None] = mapped_column(Text)
    color_profile: Mapped[str | None] = mapped_column(Text)
    has_audio: Mapped[bool | None]
    bit_depth: Mapped[int | None] = mapped_column(SmallInteger)
    rotation: Mapped[int | None] = mapped_column(SmallInteger)
    uploaded_at: Mapped[datetime | None]
    ready_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class MediaFile(TimestampMixin, Base):
    """A derived file of an asset: proxy, thumbnails, speech audio, analysis
    JSON (spec §7, §10). Deterministic keys, one row per (asset, kind), so a
    re-run of ingestion overwrites instead of duplicating."""

    __tablename__ = "media_files"
    __table_args__ = (
        Index("uq_media_files_asset_kind", "asset_id", "kind", unique=True),
        Index("ix_media_files_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, server_default=text("'{}'::jsonb"))


class AssetTranscript(TimestampMixin, Base):
    """Speech of one asset (spec §13, Phase 4). The row exists from the moment
    transcription is queued, so the pipeline stage can count it; ``data`` holds
    the ``transcript/1`` document once it is done."""

    __tablename__ = "transcripts"
    __table_args__ = (
        CheckConstraint(_one_of("status", TranscriptStatus), name="status"),
        Index("ix_transcripts_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    # What was asked for ("auto" = detect) and what the engine settled on.
    requested_language: Mapped[str] = mapped_column(Text, default="auto", server_default=text("'auto'"))
    language: Mapped[str | None] = mapped_column(Text)
    language_probability: Mapped[float | None] = mapped_column(Float)
    engine: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    speech_sec: Mapped[float | None] = mapped_column(Float)
    word_count: Mapped[int | None] = mapped_column(Integer)
    segment_count: Mapped[int | None] = mapped_column(Integer)
    engine_seconds: Mapped[float | None] = mapped_column(Float)
    data: Mapped[dict[str, Any] | None]
    error: Mapped[str | None] = mapped_column(Text)
    # Bumped on every request, so each re-run gets its own idempotency key.
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class AssetAnalysis(TimestampMixin, Base):
    """Shot analysis of one video asset (spec §12, Phase 5): the job's state and
    a summary; the per-shot records are ``clip_analyses``."""

    __tablename__ = "asset_analyses"
    __table_args__ = (
        CheckConstraint(_one_of("status", AnalysisStatus), name="status"),
        Index("ix_asset_analyses_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)  # "metrics" | "metrics+vision"
    clip_count: Mapped[int | None] = mapped_column(Integer)
    usable_avg: Mapped[float | None] = mapped_column(Float)
    sample_fps: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ClipAnalysisRow(TimestampMixin, Base):
    """One shot of an asset with its ``clipanalysis/1`` record. Hot fields are
    columns (filtering, sorting, duplicate search); the record is ``data``."""

    __tablename__ = "clip_analyses"
    __table_args__ = (
        Index("uq_clip_analyses_asset_shot", "asset_id", "shot_index", unique=True),
        Index("ix_clip_analyses_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    clip_id: Mapped[str] = mapped_column(Text)
    shot_index: Mapped[int] = mapped_column(Integer)
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    shot_type: Mapped[str] = mapped_column(Text)
    camera_motion: Mapped[str] = mapped_column(Text)
    usable_score: Mapped[float] = mapped_column(Float)
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    dhash: Mapped[str | None] = mapped_column(Text)
    sheet_key: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]]


class EditPlanRow(TimestampMixin, Base):
    """One version of a project's timeline (spec §22-23, §34). Versions are
    append-only: a new decision is a new row, so every earlier cut stays
    restorable. ``plan`` is the validated ``editplan/1`` document."""

    __tablename__ = "edit_plans"
    __table_args__ = (
        CheckConstraint(_one_of("source", PlanSource), name="source"),
        Index("uq_edit_plans_project_version", "project_id", "version", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict[str, Any]]
    duration_sec: Mapped[float] = mapped_column(Float)
    clip_count: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # What was asked for (target duration, caption style, look, loudness ...).
    options: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


class Render(TimestampMixin, Base):
    """A rendered output of one plan version in one preset (spec §27-29): the
    final file, its QA report and its delivery. One row per (plan version,
    preset, kind) — rendering the same cut twice re-uses it."""

    __tablename__ = "renders"
    __table_args__ = (
        CheckConstraint(_one_of("status", RenderStatus), name="status"),
        CheckConstraint(_one_of("kind", RenderKind), name="kind"),
        CheckConstraint(f"qa_status IS NULL OR {_one_of('qa_status', QaStatus)}", name="qa_status"),
        CheckConstraint(_one_of("delivery_status", DeliveryStatus), name="delivery_status"),
        Index("uq_renders_plan_preset_kind", "project_id", "plan_version", "preset", "kind", unique=True),
        Index("ix_renders_project_created", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("edit_plans.id", ondelete="CASCADE"))
    plan_version: Mapped[int] = mapped_column(Integer)
    preset: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default=RenderKind.FINAL.value)
    status: Mapped[str] = mapped_column(Text)
    progress: Mapped[float | None] = mapped_column(Float)
    step: Mapped[str | None] = mapped_column(Text)
    output_key: Mapped[str | None] = mapped_column(Text)
    poster_key: Mapped[str | None] = mapped_column(Text)
    # A smaller copy for the chat when the final is over Telegram's upload limit.
    telegram_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[int | None] = mapped_column(Integer)
    qa: Mapped[dict[str, Any] | None]
    qa_status: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    deliver: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    delivery_status: Mapped[str] = mapped_column(
        Text, default=DeliveryStatus.NONE.value, server_default=text("'none'")
    )
    delivery_error: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    delivered_at: Mapped[datetime | None]
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Preference(TimestampMixin, Base):
    """A remembered choice (spec §26 Memory). One row per (user, key) for the
    user's defaults; project-scoped rows (``project_id``) are reserved for
    the Memory agent."""

    __tablename__ = "preferences"
    __table_args__ = (
        CheckConstraint("scope IN ('user', 'project')", name="scope"),
        CheckConstraint("source IN ('choice', 'feedback', 'agent')", name="source"),
        Index(
            "uq_preferences_user_key",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_preferences_project_key",
            "user_id",
            "project_id",
            "key",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(Text, default="user")
    key: Mapped[str] = mapped_column(Text)
    value: Mapped[Any] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(Text)
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feedback.id", ondelete="SET NULL"))


class Feedback(TimestampMixin, Base):
    """What the owner said about a render: quick codes (each a fixed rule on
    preferences, recorded in ``changes``) and a free-text ``comment`` kept
    for the Memory agent."""

    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_project_created", "project_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    render_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("renders.id", ondelete="SET NULL"))
    plan_version: Mapped[int | None] = mapped_column(Integer)
    codes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    comment: Mapped[str | None] = mapped_column(Text)
    at_sec: Mapped[float | None] = mapped_column(Float)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )


class UploadSession(TimestampMixin, Base):
    """A resumable S3 multipart upload of one asset (spec §6). Parts are not
    mirrored here: storage's ListParts is the source of truth for progress."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint(_one_of("status", UploadSessionStatus), name="status"),
        CheckConstraint("part_count BETWEEN 1 AND 10000", name="part_count_range"),
        Index("ix_upload_sessions_status_activity", "status", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    s3_upload_id: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    part_size: Mapped[int] = mapped_column(BigInteger)
    part_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default=UploadSessionStatus.ACTIVE.value)
    bytes_reported: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    last_activity_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    completed_at: Mapped[datetime | None]


class Job(TimestampMixin, Base):
    """Durable background job (spec §30, §43, §44).

    PostgreSQL is the ledger: jobs are claimed with ``FOR UPDATE SKIP LOCKED``,
    held under a renewable lease and written back only by the lease owner.
    Redis is merely the doorbell that wakes idle workers.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_one_of("status", JobStatus), name="status"),
        CheckConstraint(_one_of("queue", JobQueue), name="queue"),
        CheckConstraint("priority BETWEEN 0 AND 3", name="priority_range"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempts_range"),
        Index("ix_jobs_claim", "queue", "priority", "run_after", postgresql_where=text("status = 'queued'")),
        Index("ix_jobs_running_lease", "lease_expires_at", postgresql_where=text("status = 'running'")),
        Index("ix_jobs_project_created", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(Text)
    queue: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger, default=2, server_default=text("2"))
    status: Mapped[str] = mapped_column(Text, default=JobStatus.QUEUED.value, server_default=text("'queued'"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    result: Mapped[dict[str, Any] | None]
    error: Mapped[dict[str, Any] | None]
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    run_after: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    progress: Mapped[float | None] = mapped_column(Float)
    progress_message: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Event(Base):
    """Append-only project activity log (spec §32). ``id`` is the SSE event id."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_one_of("level", EventLevel), name="level"),
        Index("ix_events_project_id", "project_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text, default=EventLevel.INFO.value, server_default=text("'info'"))
    source: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    job_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
