"""Read side of ingestion results: presigned links to derived files."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_core.models import AssetTranscript, MediaFile
from synthcut_schemas.api import MediaFileOut, SignedUrl, TranscriptSummary
from synthcut_storage import Storage

# Bookkeeping files are not useful in the browser (the transcript has its own endpoint).
HIDDEN_KINDS = {"mediainfo", "shots", "audio_speech", "transcript"}


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
