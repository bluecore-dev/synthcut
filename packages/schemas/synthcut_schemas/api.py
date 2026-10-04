"""HTTP API contract (v1). FastAPI turns these models into the OpenAPI document
from which the Mini App's TypeScript types are generated — one source of truth
from Pydantic to React.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .analysis import ClipAnalysis
from .enums import (
    AnalysisStatus,
    AssetKind,
    AssetStatus,
    DeliveryStatus,
    JobQueue,
    JobStatus,
    PlanSource,
    ProjectLanguage,
    ProjectMode,
    ProjectPreset,
    ProjectStatus,
    QaStatus,
    RenderStatus,
    Stage,
    StageStatus,
    TranscriptStatus,
    UploadSessionStatus,
)
from .events import EventEnvelope
from .jobs import AutoEditOptions
from .media import MediaInfo
from .preferences import EditDefaults, FeedbackCode, PreferenceSource
from .qa import QaReport

FpsChoice = Literal[24, 25, 30, 50, 60]  # kept equal to enums.ALLOWED_FPS by a test


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- errors


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ApiErrorBody


# --------------------------------------------------------------------------- auth


class TelegramAuthRequest(_In):
    init_data: str = Field(min_length=1, max_length=8192)


class UserOut(_Out):
    id: UUID
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    photo_url: str | None


class LimitsOut(BaseModel):
    max_upload_bytes: int
    storage_quota_bytes: int
    storage_used_bytes: int
    storage_reserved_bytes: int = Field(description="Declared size of uploads still in progress")
    disk_free_bytes: int | None
    part_size_bytes: int


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    user: UserOut


class MeOut(BaseModel):
    user: UserOut
    limits: LimitsOut


# --------------------------------------------------------------------------- projects


class PresetOut(BaseModel):
    id: ProjectPreset
    width: int
    height: int
    aspect: str
    label: str
    family: str


class ProjectCreate(_In):
    name: str = Field(min_length=1, max_length=120)
    preset: ProjectPreset = ProjectPreset.REELS_9X16
    fps: FpsChoice = 30
    target_duration_sec: int | None = Field(default=None, ge=5, le=4 * 3600)
    mode: ProjectMode = ProjectMode.AUTO
    language: ProjectLanguage = ProjectLanguage.AUTO
    brief: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(_In):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    preset: ProjectPreset | None = None
    fps: FpsChoice | None = None
    target_duration_sec: int | None = Field(default=None, ge=5, le=4 * 3600)
    mode: ProjectMode | None = None
    language: ProjectLanguage | None = None
    brief: str | None = Field(default=None, max_length=4000)


class StageOut(BaseModel):
    stage: Stage
    label: str
    status: StageStatus
    progress: float | None
    detail: str | None
    phase: int = Field(description="Development phase in which this stage becomes operational")
    available: bool = Field(description="False until the stage's phase has been built")
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime | None


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    preset: ProjectPreset
    fps: int
    mode: ProjectMode
    status: ProjectStatus
    asset_count: int
    total_bytes: int
    progress: float = Field(ge=0, le=1)
    active_stage: Stage | None
    active_stage_label: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectOut(ProjectSummary):
    target_duration_sec: int | None
    language: ProjectLanguage
    brief: str | None
    stages: list[StageOut]
    cost_usd: float
    current_agent: str | None


class ProjectList(BaseModel):
    items: list[ProjectSummary]


# --------------------------------------------------------------------------- assets & uploads


class UploadStateOut(BaseModel):
    session_id: UUID
    status: UploadSessionStatus
    bytes_reported: int
    part_size: int
    part_count: int


class SignedUrl(BaseModel):
    """Short-lived presigned GET on the Mini App's own origin."""

    url: str
    expires_at: datetime


class AssetOut(_Out):
    id: UUID
    project_id: UUID
    kind: AssetKind
    status: AssetStatus
    original_filename: str
    extension: str
    content_type: str
    size_bytes: int
    sort_index: int
    etag: str | None
    sha256: str | None
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    error: str | None
    created_at: datetime
    uploaded_at: datetime | None
    ready_at: datetime | None
    upload: UploadStateOut | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    color_profile: str | None = None
    color_label: str | None = None
    has_audio: bool | None = None
    bit_depth: int | None = None
    thumbnail: SignedUrl | None = None
    transcript_status: TranscriptStatus | None = None
    transcript_language: str | None = None
    transcript_finished_at: datetime | None = None
    analysis_status: AnalysisStatus | None = None
    clip_count: int | None = None
    usable_avg: float | None = None


class AssetList(BaseModel):
    items: list[AssetOut]


class MediaFileOut(BaseModel):
    kind: str
    content_type: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_sec: float | None
    metadata: dict[str, Any]
    url: SignedUrl


class ShotOut(BaseModel):
    index: int
    start: float
    end: float
    duration: float


class TranscriptSummary(BaseModel):
    """The state of an asset's transcription; the words themselves come from
    ``GET /assets/{id}/transcript``."""

    model_config = ConfigDict(from_attributes=True)

    status: TranscriptStatus
    requested_language: str
    language: str | None
    language_probability: float | None
    engine: str | None
    duration_sec: float | None
    speech_sec: float | None
    word_count: int | None
    segment_count: int | None
    engine_seconds: float | None
    error: str | None
    updated_at: datetime
    finished_at: datetime | None
    subtitles_vtt: SignedUrl | None = None
    subtitles_srt: SignedUrl | None = None


class AnalysisSummary(BaseModel):
    """State of an asset's shot analysis; the shots come from ``GET /assets/{id}/clips``."""

    model_config = ConfigDict(from_attributes=True)

    status: AnalysisStatus
    source: str | None
    clip_count: int | None
    usable_avg: float | None
    error: str | None
    updated_at: datetime
    finished_at: datetime | None


class ClipOut(ClipAnalysis):
    asset_id: UUID
    asset_name: str
    sheet: SignedUrl | None = None  # three stills of the shot (early, middle, late)


class ClipList(BaseModel):
    items: list[ClipOut]


CaptionStyle = Literal["dynamic", "karaoke", "minimal", "bold"]
CaptionPosition = Literal["bottom", "center", "top"]


class CaptionPreviewRequest(_In):
    style: CaptionStyle = "dynamic"
    position: CaptionPosition = "bottom"


class CaptionPreviewOut(BaseModel):
    """The asset with animated captions burned in (Phase 7 motion engine)."""

    status: Literal["queued", "running", "done", "failed"]
    style: CaptionStyle
    position: CaptionPosition
    error: str | None = None
    updated_at: datetime | None = None
    video: SignedUrl | None = None  # inline playback
    download: SignedUrl | None = None  # Content-Disposition: attachment


EnhanceProfile = Literal["neutral", "cinematic_clean", "warm_film", "cool_teal", "vivid_social", "bw_classic"]
LoudnessTarget = Literal["social", "youtube", "podcast", "broadcast"]


class EnhancePreviewRequest(_In):
    profile: EnhanceProfile = "cinematic_clean"
    intensity: float = Field(0.8, ge=0, le=1)
    target: LoudnessTarget = "social"
    denoise: Literal["auto", "off", "light", "medium", "strong"] = "auto"


class EnhancePreviewOut(BaseModel):
    """Automatic colour grade + voice cleanup and loudness on one clip (Phase 8)."""

    status: Literal["queued", "running", "done", "failed"]
    profile: EnhanceProfile
    intensity: float
    target: LoudnessTarget
    error: str | None = None
    updated_at: datetime | None = None
    video: SignedUrl | None = None
    download: SignedUrl | None = None
    before: SignedUrl | None = None
    after: SignedUrl | None = None
    notes: list[str] = Field(default_factory=list)
    lufs_before: float | None = None
    lufs_after: float | None = None
    grade: dict[str, Any] | None = None  # grade/1


class TranscribeRequest(_In):
    # None = the project's language; "auto" detects.
    language: ProjectLanguage | None = None


class AssetDetail(AssetOut):
    media_info: MediaInfo | None
    files: list[MediaFileOut]
    shots: list[ShotOut]
    transcript: TranscriptSummary | None = None
    analysis: AnalysisSummary | None = None
    caption_preview: CaptionPreviewOut | None = None
    enhance_preview: EnhancePreviewOut | None = None


class UploadCreate(_In):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(default="application/octet-stream", max_length=127)
    last_modified_ms: int | None = Field(default=None, ge=0)
    fingerprint: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class UploadPartOut(BaseModel):
    number: int
    size: int
    etag: str


class UploadSessionOut(BaseModel):
    id: UUID
    asset_id: UUID
    project_id: UUID
    status: UploadSessionStatus
    size_bytes: int
    part_size: int
    part_count: int
    uploaded_parts: list[UploadPartOut]
    bytes_uploaded: int
    resumed: bool = False
    asset: AssetOut


class PartSignItem(_In):
    number: int = Field(ge=1, le=10_000)
    md5_b64: str = Field(pattern=r"^[A-Za-z0-9+/]{22}==$", description="base64 of the part's 16-byte MD5")


class PartSignRequest(_In):
    parts: list[PartSignItem] = Field(min_length=1, max_length=50)


class SignedPart(BaseModel):
    number: int
    url: str
    method: str = "PUT"
    headers: dict[str, str]
    expires_at: datetime


class PartSignResponse(BaseModel):
    parts: list[SignedPart]


class UploadProgressReport(_In):
    bytes_uploaded: int = Field(ge=0)
    error: str | None = Field(
        default=None, max_length=300, description="Last client-side failure (network, storage status)"
    )


# --------------------------------------------------------------------------- events & jobs


class EventPage(BaseModel):
    items: list[EventEnvelope]
    next_after_id: int | None


class JobOut(_Out):
    id: UUID
    kind: str
    queue: JobQueue
    priority: int
    status: JobStatus
    attempts: int
    max_attempts: int
    progress: float | None
    progress_message: str | None
    error: dict[str, Any] | None
    created_at: datetime
    run_after: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    items: list[JobOut]


# --------------------------------------------------------------------------- edit plans and renders


class AutoEditRequest(AutoEditOptions):
    """ "Tez montaj": the rule-based editor, then the final render and delivery."""


class EditJobOut(BaseModel):
    id: UUID
    status: JobStatus
    progress: float | None = None
    step: str | None = None
    error: str | None = None
    created_at: datetime


class PlanSummary(_Out):
    id: UUID
    version: int
    source: PlanSource
    duration_sec: float
    clip_count: int
    notes: str | None
    options: dict[str, Any]
    created_at: datetime


class PlanClipOut(BaseModel):
    id: str
    asset_id: UUID
    asset_name: str | None = None
    source_in: float
    source_out: float
    timeline_start: float
    timeline_end: float
    reframed: bool  # moved to keep a face in view
    fill: Literal["cover", "blur"]  # blur: fitted over a blurred copy of itself
    exposure: float | None = None  # the clip's grade, stops


class PlanGraphicOut(BaseModel):
    id: str
    component: str
    timeline_start: float
    timeline_end: float
    text: str | None = None


class PlanOut(PlanSummary):
    """A plan version as the timeline view needs it (the full ``editplan/1``
    document stays server-side; agents and renderers read it there)."""

    width: int
    height: int
    fps: int
    captions: str | None  # caption style, None = off
    loudness_lufs: float | None
    clips: list[PlanClipOut]
    graphics: list[PlanGraphicOut]


class PlanList(BaseModel):
    items: list[PlanSummary]


class RenderRequest(_In):
    preset: ProjectPreset | None = None  # None = the preset the plan was made for
    deliver: bool = False
    force: bool = False  # render again even if this version is done


class RenderOut(_Out):
    id: UUID
    plan_id: UUID
    plan_version: int
    preset: ProjectPreset
    status: RenderStatus
    progress: float | None
    step: str | None
    error: str | None
    size_bytes: int | None
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: int | None
    qa_status: QaStatus | None
    qa: QaReport | None
    deliver: bool
    delivery_status: DeliveryStatus
    delivery_error: str | None
    delivered_at: datetime | None
    created_at: datetime
    finished_at: datetime | None
    video: SignedUrl | None = None
    download: SignedUrl | None = None
    poster: SignedUrl | None = None


class RenderList(BaseModel):
    items: list[RenderOut]


class EditStateOut(BaseModel):
    """What the "Tez montaj" card shows: the running request, the newest plan
    and the newest render."""

    job: EditJobOut | None = None
    plan: PlanSummary | None = None
    render: RenderOut | None = None


# --------------------------------------------------------------------------- memory


class FeedbackOption(BaseModel):
    code: FeedbackCode
    label: str


class EditPreferencesOut(BaseModel):
    """What the next Tez montaj starts from. ``sources`` names the keys the
    user's own choices or feedback set; the rest are built-in defaults."""

    values: EditDefaults
    sources: dict[str, PreferenceSource]
    feedback_options: list[FeedbackOption]


class FeedbackRequest(_In):
    codes: list[FeedbackCode] = Field(default_factory=list, max_length=10)
    comment: str | None = Field(None, max_length=2000)
    at_sec: float | None = Field(None, ge=0, le=4 * 3600)
    remake: bool = False  # a new Tez montaj version from the corrected preferences


class PreferenceChange(BaseModel):
    key: str
    before: Any
    after: Any
    label: str


class FeedbackOut(_Out):
    id: UUID
    render_id: UUID | None
    plan_version: int | None
    codes: list[FeedbackCode]
    comment: str | None
    at_sec: float | None
    changes: list[PreferenceChange]
    created_at: datetime
    remake_job_id: UUID | None = None


class FeedbackList(BaseModel):
    items: list[FeedbackOut]


# --------------------------------------------------------------------------- health


class HealthOut(BaseModel):
    status: str
    version: str
    release: str


class ComponentCheck(BaseModel):
    ok: bool
    detail: str | None = None


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, ComponentCheck]
