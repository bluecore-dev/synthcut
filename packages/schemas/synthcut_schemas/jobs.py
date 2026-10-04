"""Typed payloads for background jobs (spec §30).

A job's ``kind`` names its handler; its payload is validated against the model
registered here before the handler runs, so a malformed payload fails fast and
permanently instead of crashing deep inside media code.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobKind:
    INGEST_ASSET = "ingest.asset"
    TRANSCRIBE_ASSET = "speech.transcribe"
    ANALYZE_ASSET = "analysis.asset"
    RENDER_CAPTION_PREVIEW = "render.caption_preview"
    RENDER_ENHANCE_PREVIEW = "render.enhance_preview"
    EXPIRE_UPLOADS = "maintenance.expire_uploads"
    SWEEP_ORPHAN_UPLOADS = "maintenance.sweep_orphan_uploads"
    PRUNE_JOBS = "maintenance.prune_jobs"
    NOTIFY_TELEGRAM = "notify.telegram"


JOB_LABELS: dict[str, str] = {
    JobKind.INGEST_ASSET: "Media ingest",
    JobKind.TRANSCRIBE_ASSET: "Nutqni matnga o'girish",
    JobKind.ANALYZE_ASSET: "Kadrlar tahlili",
    JobKind.RENDER_CAPTION_PREVIEW: "Subtitrli video",
    JobKind.RENDER_ENHANCE_PREVIEW: "Rang va ovoz",
    JobKind.EXPIRE_UPLOADS: "Eskirgan yuklashlarni tozalash",
    JobKind.SWEEP_ORPHAN_UPLOADS: "Yetim multipart yuklashlarni tozalash",
    JobKind.PRUNE_JOBS: "Eski tizim job'larini tozalash",
    JobKind.NOTIFY_TELEGRAM: "Telegram xabari",
}


def job_label(kind: str) -> str:
    return JOB_LABELS.get(kind, kind)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IngestAssetPayload(_Payload):
    asset_id: UUID
    # Re-run on an asset that is already ready (the media engine improved).
    # Only derived files are rewritten; the original is never touched.
    force: bool = False


class TranscribeAssetPayload(_Payload):
    asset_id: UUID
    # None = the project's language ("auto" detects); an explicit code forces it.
    language: str | None = Field(default=None, pattern=r"^(auto|[a-z]{2,3})$")
    # Re-run on an asset whose transcript is already done.
    force: bool = False


class AnalyzeAssetPayload(_Payload):
    asset_id: UUID
    force: bool = False  # re-run on an asset whose analysis is already done


class CaptionPreviewPayload(_Payload):
    asset_id: UUID
    style: Literal["dynamic", "karaoke", "minimal", "bold"] = "dynamic"
    position: Literal["bottom", "center", "top"] = "bottom"


class EnhancePreviewPayload(_Payload):
    asset_id: UUID
    profile: Literal["neutral", "cinematic_clean", "warm_film", "cool_teal", "vivid_social", "bw_classic"] = (
        "cinematic_clean"
    )
    intensity: float = Field(0.8, ge=0, le=1)
    target: Literal["social", "youtube", "podcast", "broadcast"] = "social"
    denoise: Literal["auto", "off", "light", "medium", "strong"] = "auto"


class ExpireUploadsPayload(_Payload):
    pass


class SweepOrphanUploadsPayload(_Payload):
    pass


class PruneJobsPayload(_Payload):
    pass


class NotifyTelegramPayload(_Payload):
    chat_id: int
    text: str = Field(max_length=4000)
    open_project_id: UUID | None = None


PAYLOAD_MODELS: dict[str, type[_Payload]] = {
    JobKind.INGEST_ASSET: IngestAssetPayload,
    JobKind.TRANSCRIBE_ASSET: TranscribeAssetPayload,
    JobKind.ANALYZE_ASSET: AnalyzeAssetPayload,
    JobKind.RENDER_CAPTION_PREVIEW: CaptionPreviewPayload,
    JobKind.RENDER_ENHANCE_PREVIEW: EnhancePreviewPayload,
    JobKind.EXPIRE_UPLOADS: ExpireUploadsPayload,
    JobKind.SWEEP_ORPHAN_UPLOADS: SweepOrphanUploadsPayload,
    JobKind.PRUNE_JOBS: PruneJobsPayload,
    JobKind.NOTIFY_TELEGRAM: NotifyTelegramPayload,
}
