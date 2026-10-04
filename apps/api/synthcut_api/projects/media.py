"""Read side of ingestion results: presigned links to derived files."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_core.models import Asset, AssetAnalysis, AssetTranscript, ClipAnalysisRow, Job, MediaFile
from synthcut_schemas.api import (
    AnalysisSummary,
    CaptionPreviewOut,
    ClipOut,
    EnhancePreviewOut,
    MediaFileOut,
    SignedUrl,
    TranscriptSummary,
)
from synthcut_schemas.jobs import JobKind
from synthcut_storage import Storage

# Bookkeeping files are not useful in the browser (the transcript has its own endpoint).
HIDDEN_KINDS = {
    "mediainfo",
    "shots",
    "audio_speech",
    "transcript",
    "clips",
    "caption_preview",
    "enhance_preview",
    "enhance_before",
    "enhance_after",
}


def sign(storage: Storage, key: str, ttl: int, *, download_name: str | None = None) -> SignedUrl:
    return SignedUrl(
        url=storage.presign_get(key, ttl, download_name=download_name),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )


async def posters(
    db: AsyncSession, storage: Storage, asset_ids: list[uuid.UUID], ttl: int
) -> dict[uuid.UUID, SignedUrl]:
    if not asset_ids:
        return {}
    rows = await db.execute(
        select(MediaFile.asset_id, MediaFile.storage_key).where(
            MediaFile.asset_id.in_(asset_ids), MediaFile.kind == "poster"
        )
    )
    return {asset_id: sign(storage, key, ttl) for asset_id, key in rows.all()}


async def files_for(
    db: AsyncSession, storage: Storage, asset_id: uuid.UUID, ttl: int
) -> tuple[list[MediaFileOut], list[dict]]:
    rows = list((await db.execute(select(MediaFile).where(MediaFile.asset_id == asset_id))).scalars())
    shots = next((r.meta.get("shots", []) for r in rows if r.kind == "shots"), [])
    files = [
        MediaFileOut(
            kind=r.kind,
            content_type=r.content_type,
            size_bytes=r.size_bytes,
            width=r.width,
            height=r.height,
            duration_sec=r.duration_sec,
            metadata={k: v for k, v in r.meta.items() if k != "shots"},
            url=sign(storage, r.storage_key, ttl),
        )
        for r in sorted(rows, key=lambda r: r.kind)
        if r.kind not in HIDDEN_KINDS
    ]
    return files, shots


TranscriptState = tuple[str, str | None, datetime | None]  # status, language, finished_at


async def transcript_states(db: AsyncSession, asset_ids: list[uuid.UUID]) -> dict[uuid.UUID, TranscriptState]:
    """asset id -> transcript state for list views."""
    if not asset_ids:
        return {}
    rows = await db.execute(
        select(
            AssetTranscript.asset_id,
            AssetTranscript.status,
            AssetTranscript.language,
            AssetTranscript.finished_at,
        ).where(AssetTranscript.asset_id.in_(asset_ids))
    )
    return {asset_id: (status, language, finished) for asset_id, status, language, finished in rows.all()}


async def transcript_summary(
    db: AsyncSession, storage: Storage, asset_id: uuid.UUID, ttl: int, *, filename: str = "subtitles"
) -> TranscriptSummary | None:
    row = (
        await db.execute(select(AssetTranscript).where(AssetTranscript.asset_id == asset_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    out = TranscriptSummary.model_validate(row)
    if row.status == "done":
        subs = await db.execute(
            select(MediaFile.kind, MediaFile.storage_key).where(
                MediaFile.asset_id == asset_id, MediaFile.kind.in_(["subtitles_vtt", "subtitles_srt"])
            )
        )
        stem = PurePosixPath(filename).stem or "subtitles"
        for kind, key in subs.all():
            # SRT downloads under the clip's own name; the VTT feeds the player.
            name = f"{stem}.srt" if kind == "subtitles_srt" else None
            setattr(out, kind, sign(storage, key, ttl, download_name=name))
    return out


AnalysisState = tuple[str, int | None, float | None]  # status, clip count, average usability


async def analysis_states(db: AsyncSession, asset_ids: list[uuid.UUID]) -> dict[uuid.UUID, AnalysisState]:
    if not asset_ids:
        return {}
    rows = await db.execute(
        select(
            AssetAnalysis.asset_id, AssetAnalysis.status, AssetAnalysis.clip_count, AssetAnalysis.usable_avg
        ).where(AssetAnalysis.asset_id.in_(asset_ids))
    )
    return {asset_id: (status, clips, usable) for asset_id, status, clips, usable in rows.all()}


async def analysis_summary(db: AsyncSession, asset_id: uuid.UUID) -> AnalysisSummary | None:
    row = (
        await db.execute(select(AssetAnalysis).where(AssetAnalysis.asset_id == asset_id))
    ).scalar_one_or_none()
    return AnalysisSummary.model_validate(row) if row is not None else None


async def clips_for(
    db: AsyncSession,
    storage: Storage,
    ttl: int,
    *,
    asset_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    min_usable: float | None = None,
) -> list[ClipOut]:
    stmt = select(ClipAnalysisRow, Asset.original_filename).join(Asset, Asset.id == ClipAnalysisRow.asset_id)
    if asset_id is not None:
        stmt = stmt.where(ClipAnalysisRow.asset_id == asset_id)
    if project_id is not None:
        stmt = stmt.where(ClipAnalysisRow.project_id == project_id, Asset.deleted_at.is_(None))
    if min_usable is not None:
        stmt = stmt.where(ClipAnalysisRow.usable_score >= min_usable)
    stmt = stmt.order_by(Asset.sort_index, Asset.created_at, ClipAnalysisRow.shot_index)
    out: list[ClipOut] = []
    for row, name in (await db.execute(stmt)).all():
        out.append(
            ClipOut(
                **row.data,
                asset_id=row.asset_id,
                asset_name=name,
                sheet=sign(storage, row.sheet_key, ttl) if row.sheet_key else None,
            )
        )
    return out


def latest_preview_job_stmt(asset_id: uuid.UUID, kind: str = JobKind.RENDER_CAPTION_PREVIEW):
    return (
        select(Job)
        .where(Job.kind == kind, Job.payload["asset_id"].astext == str(asset_id))
        .order_by(Job.created_at.desc())
        .limit(1)
    )


async def _preview(db: AsyncSession, asset_id: uuid.UUID, job_kind: str, file_kind: str):
    """(status, error, settings source, finished file, updated_at) of the latest
    request (the job) and the latest finished file — or None if neither exists."""
    job = (await db.execute(latest_preview_job_stmt(asset_id, job_kind))).scalar_one_or_none()
    done = (
        await db.execute(select(MediaFile).where(MediaFile.asset_id == asset_id, MediaFile.kind == file_kind))
    ).scalar_one_or_none()
    if job is None and done is None:
        return None
    if job is not None and job.status in ("queued", "running"):
        return job.status, None, job.payload, done, job.updated_at
    if (
        job is not None
        and job.status in ("dead", "cancelled")
        and (done is None or done.updated_at < job.updated_at)
    ):
        return "failed", ((job.error or {}).get("message") or "xato")[:300], job.payload, done, job.updated_at
    return (
        "done",
        None,
        (done.meta if done is not None else job.payload),
        done,
        (done.updated_at if done else None),
    )


async def caption_preview_state(
    db: AsyncSession, storage: Storage, asset_id: uuid.UUID, ttl: int, *, filename: str
) -> CaptionPreviewOut | None:
    """Latest request (the job) plus the latest finished file, if any."""
    found = await _preview(db, asset_id, JobKind.RENDER_CAPTION_PREVIEW, "caption_preview")
    if found is None:
        return None
    status, error, source, done, updated = found
    links = {}
    if done is not None:
        stem = PurePosixPath(filename).stem or "video"
        links = {
            "video": sign(storage, done.storage_key, ttl),
            "download": sign(storage, done.storage_key, ttl, download_name=f"{stem}_subtitr.mp4"),
        }
    return CaptionPreviewOut(
        status=status,
        style=source.get("style", "dynamic"),
        position=source.get("position", "bottom"),
        error=error,
        updated_at=updated,
        **links,
    )


async def enhance_preview_state(
    db: AsyncSession, storage: Storage, asset_id: uuid.UUID, ttl: int, *, filename: str
) -> EnhancePreviewOut | None:
    found = await _preview(db, asset_id, JobKind.RENDER_ENHANCE_PREVIEW, "enhance_preview")
    if found is None:
        return None
    status, error, source, done, updated = found
    extra: dict = {}
    if done is not None:
        stem = PurePosixPath(filename).stem or "video"
        stills = {
            m.kind: m
            for m in (
                await db.execute(
                    select(MediaFile).where(
                        MediaFile.asset_id == asset_id,
                        MediaFile.kind.in_(["enhance_before", "enhance_after"]),
                    )
                )
            ).scalars()
        }
        extra = {
            "video": sign(storage, done.storage_key, ttl),
            "download": sign(storage, done.storage_key, ttl, download_name=f"{stem}_enhanced.mp4"),
            "before": sign(storage, stills["enhance_before"].storage_key, ttl)
            if "enhance_before" in stills
            else None,
            "after": sign(storage, stills["enhance_after"].storage_key, ttl)
            if "enhance_after" in stills
            else None,
            "notes": done.meta.get("notes", []),
            "lufs_before": done.meta.get("lufs_before"),
            "lufs_after": done.meta.get("lufs_after"),
            "grade": done.meta.get("grade"),
        }
    return EnhancePreviewOut(
        status=status,
        profile=source.get("profile", "cinematic_clean"),
        intensity=source.get("intensity", 0.8),
        target=source.get("target", "social"),
        error=error,
        updated_at=updated,
        **extra,
    )
