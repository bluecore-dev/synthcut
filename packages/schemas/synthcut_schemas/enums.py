"""Canonical enumerations shared by every SynthCut service.

Values are stored as plain text in PostgreSQL (with CHECK constraints on state
columns), so they must never be renamed — only added.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class ProjectPreset(StrEnum):
    REELS_9X16 = "reels_9x16"
    YOUTUBE_16X9_1080 = "youtube_16x9_1080"
    YOUTUBE_16X9_2160 = "youtube_16x9_2160"
    SQUARE_1X1 = "square_1x1"
    PORTRAIT_4X5 = "portrait_4x5"


@dataclass(frozen=True, slots=True)
class PresetSpec:
    width: int
    height: int
    aspect: str
    label: str
    family: str  # "short" | "long"


PRESET_SPECS: dict[ProjectPreset, PresetSpec] = {
    ProjectPreset.REELS_9X16: PresetSpec(1080, 1920, "9:16", "Reels / TikTok / Shorts", "short"),
    ProjectPreset.YOUTUBE_16X9_1080: PresetSpec(1920, 1080, "16:9", "YouTube 1080p", "long"),
    ProjectPreset.YOUTUBE_16X9_2160: PresetSpec(3840, 2160, "16:9", "YouTube 4K", "long"),
    ProjectPreset.SQUARE_1X1: PresetSpec(1080, 1080, "1:1", "Square 1:1", "short"),
    ProjectPreset.PORTRAIT_4X5: PresetSpec(1080, 1350, "4:5", "Portrait 4:5", "short"),
}

ALLOWED_FPS: tuple[int, ...] = (24, 25, 30, 50, 60)


class ProjectMode(StrEnum):
    AUTO = "auto"
    ASSISTED = "assisted"
    MANUAL = "manual"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProjectLanguage(StrEnum):
    AUTO = "auto"
    UZ = "uz"
    RU = "ru"
    EN = "en"


class AssetKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    OTHER = "other"


class AssetStatus(StrEnum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscriptStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RenderStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RenderKind(StrEnum):
    FINAL = "final"


class PlanSource(StrEnum):
    RULES = "rules"  # the rule-based editor ("Tez montaj"), no model involved
    DIRECTOR = "director"  # the Director / Editor agents (Phase 6)
    USER = "user"  # edited by hand


class QaStatus(StrEnum):
    PASS = "pass"  # noqa: S105 — a verdict, not a password
    WARN = "warn"
    FAIL = "fail"


class DeliveryStatus(StrEnum):
    NONE = "none"
    QUEUED = "queued"
    SENT = "sent"  # the video itself is in the chat
    FAILED = "failed"


class UploadSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETING = "completing"
    COMPLETED = "completed"
    ABORTED = "aborted"
    EXPIRED = "expired"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD = "dead"
    CANCELLED = "cancelled"


class JobQueue(StrEnum):
    """Separate queues so heavy work never starves light work (spec §30-31)."""

    IO = "io"  # maintenance, notifications, delivery
    CPU = "cpu"  # ffprobe / ffmpeg / proxies / audio
    GPU = "gpu"  # local whisper, vision models, enhancement
    RENDER = "render"  # remotion + final ffmpeg compositing
    LLM = "llm"  # agent reasoning calls (network bound)


class JobPriority(IntEnum):
    INTERACTIVE = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class Stage(StrEnum):
    UPLOAD = "upload"
    INGEST = "ingest"
    ANALYSIS = "analysis"
    TRANSCRIPTION = "transcription"
    DIRECTOR = "director"
    EDITOR = "editor"
    COLOR = "color"
    AUDIO = "audio"
    MOTION = "motion"
    CAPTIONS = "captions"
    QA = "qa"
    RENDER = "render"
    DELIVERY = "delivery"


STAGE_ORDER: tuple[Stage, ...] = tuple(Stage)

STAGE_LABELS: dict[Stage, str] = {
    Stage.UPLOAD: "Upload",
    Stage.INGEST: "Media Ingest",
    Stage.ANALYSIS: "Media Analysis",
    Stage.TRANSCRIPTION: "Transcription",
    Stage.DIRECTOR: "Director",
    Stage.EDITOR: "Editor",
    Stage.COLOR: "Color",
    Stage.AUDIO: "Audio",
    Stage.MOTION: "Motion",
    Stage.CAPTIONS: "Captions",
    Stage.QA: "QA",
    Stage.RENDER: "Render",
    Stage.DELIVERY: "Delivery",
}

# Stages that are built and deployed. The others are shown as "not yet
# available" instead of pretending. The Director (an AI agent) waits for a model
# key; everything after it runs on rules and measurements (ADR-0015).
BUILT_STAGES: frozenset[Stage] = frozenset(Stage) - {Stage.DIRECTOR}

# Development phase (spec §51) in which each stage becomes operational.
STAGE_PHASE: dict[Stage, int] = {
    Stage.UPLOAD: 2,
    Stage.INGEST: 3,
    Stage.ANALYSIS: 5,
    Stage.TRANSCRIPTION: 4,
    Stage.DIRECTOR: 6,
    Stage.EDITOR: 6,
    Stage.COLOR: 8,
    Stage.AUDIO: 8,
    Stage.MOTION: 7,
    Stage.CAPTIONS: 7,
    Stage.QA: 9,
    Stage.RENDER: 11,
    Stage.DELIVERY: 12,
}

# Relative weight of each stage in the overall project progress figure.
STAGE_WEIGHTS: dict[Stage, float] = {
    Stage.UPLOAD: 8,
    Stage.INGEST: 8,
    Stage.ANALYSIS: 10,
    Stage.TRANSCRIPTION: 8,
    Stage.DIRECTOR: 10,
    Stage.EDITOR: 10,
    Stage.COLOR: 7,
    Stage.AUDIO: 7,
    Stage.MOTION: 7,
    Stage.CAPTIONS: 5,
    Stage.QA: 5,
    Stage.RENDER: 12,
    Stage.DELIVERY: 3,
}


class StageStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    WAITING_USER = "waiting_user"


class EventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
