"""Requesting shot analysis (Phase 5): one ``asset_analyses`` row per video
asset, re-used on every run; ``runs`` gives each request its own idempotency
key while a double tap still enqueues once."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from synthcut_schemas.enums import AnalysisStatus, JobPriority, JobQueue
from synthcut_schemas.jobs import JobKind

from .jobs import enqueue, enqueue_async
from .models import AssetAnalysis

ACTIVE = (AnalysisStatus.QUEUED.value, AnalysisStatus.RUNNING.value)


def _row_stmt(asset_id: uuid.UUID):
    return select(AssetAnalysis).where(AssetAnalysis.asset_id == asset_id).with_for_update()


def _prepare(row: AssetAnalysis | None, asset_id: uuid.UUID, project_id: uuid.UUID) -> AssetAnalysis:
    if row is None:
        row = AssetAnalysis(asset_id=asset_id, project_id=project_id, runs=0)
    row.status = AnalysisStatus.QUEUED.value
    row.error = None
    row.runs = (row.runs or 0) + 1
    return row


def _job(asset_id: uuid.UUID, project_id: uuid.UUID, force: bool, runs: int) -> dict:
    return {
        "kind": JobKind.ANALYZE_ASSET,
        "queue": JobQueue.CPU,
        "payload": {"asset_id": str(asset_id), "force": force},
        "project_id": project_id,
        # After ingestion (HIGH), before the slow transcription (LOW): seconds, not minutes.
        "priority": JobPriority.NORMAL,
        "idempotency_key": f"{JobKind.ANALYZE_ASSET}:{asset_id}:r{runs}",
        "max_attempts": 3,
    }


def request_analysis(
    s: Session, *, asset_id: uuid.UUID, project_id: uuid.UUID, force: bool = False
) -> AssetAnalysis:
    row = s.execute(_row_stmt(asset_id)).scalar_one_or_none()
    if row is not None and (not force or row.status in ACTIVE):
        return row
    row = _prepare(row, asset_id, project_id)
    s.add(row)
    s.flush()
    enqueue(s, **_job(asset_id, project_id, force, row.runs))
    return row


async def request_analysis_async(
    s: AsyncSession, *, asset_id: uuid.UUID, project_id: uuid.UUID, force: bool = False
) -> AssetAnalysis:
    row = (await s.execute(_row_stmt(asset_id))).scalar_one_or_none()
    if row is not None and (not force or row.status in ACTIVE):
        return row
    row = _prepare(row, asset_id, project_id)
    s.add(row)
    await s.flush()
    await enqueue_async(s, **_job(asset_id, project_id, force, row.runs))
    return row
