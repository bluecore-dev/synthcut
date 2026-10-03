"""Recording derived files (spec §7): one ``media_files`` row per (asset,
kind), so a re-run overwrites the row it wrote last time."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from synthcut_core.ids import new_id
from synthcut_core.models import MediaFile


def upsert_media_file(
    s: Session,
    *,
    asset_id: uuid.UUID,
    project_id: uuid.UUID,
    kind: str,
    storage_key: str,
    content_type: str,
    size_bytes: int,
    now: datetime,
    width: int | None = None,
    height: int | None = None,
    duration_sec: float | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    stmt = pg_insert(MediaFile).values(
        id=new_id(),
        asset_id=asset_id,
        project_id=project_id,
        kind=kind,
        storage_key=storage_key,
        content_type=content_type,
        size_bytes=size_bytes,
        width=width,
        height=height,
        duration_sec=duration_sec,
        meta=meta or {},
        created_at=now,
        updated_at=now,
    )
    s.execute(
        stmt.on_conflict_do_update(
            index_elements=[MediaFile.asset_id, MediaFile.kind],
            set_={
                "storage_key": stmt.excluded.storage_key,
                "content_type": stmt.excluded.content_type,
                "size_bytes": stmt.excluded.size_bytes,
                "width": stmt.excluded.width,
                "height": stmt.excluded.height,
                "duration_sec": stmt.excluded.duration_sec,
                "metadata": stmt.excluded.metadata,
                "updated_at": now,
            },
        )
    )
