"""Read side of ingestion results: presigned links to derived files."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_core.models import MediaFile
from synthcut_schemas.api import MediaFileOut, SignedUrl
from synthcut_storage import Storage

# Ingestion bookkeeping files are not useful in the browser.
HIDDEN_KINDS = {"mediainfo", "shots", "audio_speech"}


def sign(storage: Storage, key: str, ttl: int) -> SignedUrl:
    return SignedUrl(url=storage.presign_get(key, ttl), expires_at=datetime.now(UTC) + timedelta(seconds=ttl))


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
