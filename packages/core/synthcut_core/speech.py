"""Requesting a transcription (Phase 4): one ``transcripts`` row per asset,
re-used on every run; each request bumps ``runs`` so its job gets a fresh
idempotency key while a double-click still enqueues once."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from synthcut_schemas.enums import JobPriority, JobQueue, TranscriptStatus
from synthcut_schemas.jobs import JobKind

from .jobs import enqueue, enqueue_async
from .models import AssetTranscript

ACTIVE = (TranscriptStatus.QUEUED.value, TranscriptStatus.RUNNING.value)


def _row_stmt(asset_id: uuid.UUID):
    return select(AssetTranscript).where(AssetTranscript.asset_id == asset_id).with_for_update()


def _prepare(row: AssetTranscript | None, asset_id: uuid.UUID, project_id: uuid.UUID, language: str):
    if row is None:
        row = AssetTranscript(asset_id=asset_id, project_id=project_id, runs=0)
    row.status = TranscriptStatus.QUEUED.value
    row.requested_language = language
    row.error = None
    row.runs = (row.runs or 0) + 1
    return row


def _job(asset_id: uuid.UUID, project_id: uuid.UUID, language: str, force: bool, runs: int) -> dict:
    return {
        "kind": JobKind.TRANSCRIBE_ASSET,
        "queue": JobQueue.CPU,  # no GPU on this host; the gpu queue takes it when one exists
        "payload": {"asset_id": str(asset_id), "language": language, "force": force},
        "project_id": project_id,
        # Below ingestion (HIGH): every file gets its proxy before speech starts.
        "priority": JobPriority.NORMAL,
        "idempotency_key": f"{JobKind.TRANSCRIBE_ASSET}:{asset_id}:r{runs}",
        "max_attempts": 2,
    }


def request_transcription(
    s: Session, *, asset_id: uuid.UUID, project_id: uuid.UUID, language: str, force: bool = False
) -> AssetTranscript:
    """Without ``force`` an existing transcript (any status) is left alone."""
    row = s.execute(_row_stmt(asset_id)).scalar_one_or_none()
    if row is not None and (not force or row.status in ACTIVE):
        return row
    row = _prepare(row, asset_id, project_id, language)
    s.add(row)
    s.flush()
    enqueue(s, **_job(asset_id, project_id, language, force, row.runs))
    return row


async def request_transcription_async(
    s: AsyncSession, *, asset_id: uuid.UUID, project_id: uuid.UUID, language: str, force: bool = False
) -> AssetTranscript:
    row = (await s.execute(_row_stmt(asset_id))).scalar_one_or_none()
    if row is not None and (not force or row.status in ACTIVE):
        return row
    row = _prepare(row, asset_id, project_id, language)
    s.add(row)
    await s.flush()
    await enqueue_async(s, **_job(asset_id, project_id, language, force, row.runs))
    return row
