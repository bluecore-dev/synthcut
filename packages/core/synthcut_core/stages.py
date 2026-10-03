"""Project pipeline stages (spec §32, §37).

``project_stages`` is the materialized state behind the dashboard's pipeline
list. A persisted ``stage.updated`` event is written only when a stage's
*status* changes; progress-only updates go out as ephemeral events so the
activity log does not fill with percentages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from synthcut_schemas.enums import (
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_WEIGHTS,
    AnalysisStatus,
    AssetStatus,
    EventLevel,
    Stage,
    StageStatus,
    TranscriptStatus,
    UploadSessionStatus,
)
from synthcut_schemas.events import EventType

from .events import emit
from .models import Asset, AssetAnalysis, AssetTranscript, ProjectStage, UploadSession, utcnow

_TERMINAL = {StageStatus.DONE, StageStatus.FAILED, StageStatus.SKIPPED}


@dataclass(frozen=True, slots=True)
class StageState:
    status: StageStatus
    progress: float | None
    detail: str | None


def _upsert(project_id: uuid.UUID, stage: Stage, state: StageState, *, started: bool):
    now = utcnow()
    finished = now if state.status in _TERMINAL else None
    stmt = pg_insert(ProjectStage).values(
        project_id=project_id,
        stage=stage.value,
        status=state.status.value,
        progress=state.progress,
        detail=state.detail,
        started_at=now if started else None,
        finished_at=finished,
        updated_at=now,
    )
    return stmt.on_conflict_do_update(
        index_elements=[ProjectStage.project_id, ProjectStage.stage],
        set_={
            "status": stmt.excluded.status,
            "progress": stmt.excluded.progress,
            "detail": stmt.excluded.detail,
            "updated_at": stmt.excluded.updated_at,
            "finished_at": stmt.excluded.finished_at,
            "started_at": func.coalesce(ProjectStage.started_at, stmt.excluded.started_at),
        },
    )


def _status_event(session, project_id: uuid.UUID, stage: Stage, state: StageState, source: str) -> None:
    level = EventLevel.ERROR if state.status is StageStatus.FAILED else EventLevel.INFO
    label = STAGE_LABELS[stage]
    message = f"{label}: {state.status.value}" + (f" — {state.detail}" if state.detail else "")
    emit(
        session,
        project_id=project_id,
        type=EventType.STAGE_UPDATED,
        level=level,
        message=message,
        source=source,
        data={
            "stage": stage.value,
            "status": state.status.value,
            "progress": state.progress,
            "detail": state.detail,
        },
    )


def _previous_stmt(project_id: uuid.UUID, stage: Stage):
    return (
        select(ProjectStage.status)
        .where(ProjectStage.project_id == project_id, ProjectStage.stage == stage.value)
        .with_for_update()
    )


def set_stage(
    session: Session, project_id: uuid.UUID, stage: Stage, state: StageState, *, source: str
) -> bool:
    previous = session.execute(_previous_stmt(project_id, stage)).scalar_one_or_none()
    started = state.status is StageStatus.RUNNING
    session.execute(_upsert(project_id, stage, state, started=started))
    changed = previous != state.status.value
    if changed:
        _status_event(session, project_id, stage, state, source)
    return changed


async def set_stage_async(
    session: AsyncSession, project_id: uuid.UUID, stage: Stage, state: StageState, *, source: str
) -> bool:
    previous = (await session.execute(_previous_stmt(project_id, stage))).scalar_one_or_none()
    started = state.status is StageStatus.RUNNING
    await session.execute(_upsert(project_id, stage, state, started=started))
    changed = previous != state.status.value
    if changed:
        _status_event(session, project_id, stage, state, source)
    return changed


async def init_stages_async(session: AsyncSession, project_id: uuid.UUID) -> None:
    now = utcnow()
    await session.execute(
        pg_insert(ProjectStage)
        .values(
            [
                {
                    "project_id": project_id,
                    "stage": stage.value,
                    "status": StageStatus.PENDING.value,
                    "updated_at": now,
                }
                for stage in STAGE_ORDER
            ]
        )
        .on_conflict_do_nothing()
    )


def overall_progress(stages: dict[str, tuple[str, float | None]]) -> float:
    total = sum(STAGE_WEIGHTS.values())
    done = 0.0
    for stage, weight in STAGE_WEIGHTS.items():
        status, progress = stages.get(stage.value, (StageStatus.PENDING.value, None))
        if status in (StageStatus.DONE.value, StageStatus.SKIPPED.value):
            done += weight
        elif status == StageStatus.RUNNING.value and progress is not None:
            done += weight * max(0.0, min(1.0, progress))
    return round(done / total, 4)


def active_stage(stages: dict[str, tuple[str, float | None]]) -> Stage | None:
    for stage in STAGE_ORDER:
        status = stages.get(stage.value, (StageStatus.PENDING.value, None))[0]
        if status in (
            StageStatus.RUNNING.value,
            StageStatus.QUEUED.value,
            StageStatus.WAITING_USER.value,
            StageStatus.FAILED.value,
        ):
            return stage
    return None


# --------------------------------------------------------------------------- upload stage


def _upload_aggregate_stmt(project_id: uuid.UUID):
    return (
        select(Asset.status, func.count(), func.coalesce(func.sum(Asset.size_bytes), 0))
        .where(Asset.project_id == project_id, Asset.deleted_at.is_(None))
        .group_by(Asset.status)
    )


def _reported_stmt(project_id: uuid.UUID):
    return select(
        func.coalesce(func.sum(func.least(UploadSession.bytes_reported, UploadSession.size_bytes)), 0)
    ).where(
        UploadSession.project_id == project_id,
        UploadSession.status.in_([UploadSessionStatus.ACTIVE.value, UploadSessionStatus.COMPLETING.value]),
    )


def _upload_state(rows: list[tuple[str, int, int]], reported: int) -> StageState:
    # SUM(bigint) is NUMERIC in PostgreSQL -> Decimal; keep event payloads JSON-safe.
    by_status = {status: (int(count), int(size)) for status, count, size in rows}
    uploading_count, uploading_size = by_status.get(AssetStatus.UPLOADING.value, (0, 0))
    finished = [
        by_status.get(s.value, (0, 0))
        for s in (AssetStatus.UPLOADED, AssetStatus.INGESTING, AssetStatus.READY)
    ]
    done_count = sum(c for c, _ in finished)
    done_size = sum(s for _, s in finished)
    if uploading_count:
        progress = min(1.0, reported / uploading_size) if uploading_size else 0.0
        return StageState(StageStatus.RUNNING, round(progress, 4), f"{uploading_count} ta fayl yuklanmoqda")
    if done_count:
        gb = done_size / 1024**3
        return StageState(StageStatus.DONE, 1.0, f"{done_count} ta fayl · {gb:.2f} GB")
    return StageState(StageStatus.PENDING, None, None)


def refresh_upload_stage(session: Session, project_id: uuid.UUID, *, source: str) -> StageState:
    session.flush()  # the aggregate must see this transaction's pending changes
    rows = [tuple(r) for r in session.execute(_upload_aggregate_stmt(project_id)).all()]
    reported = int(session.execute(_reported_stmt(project_id)).scalar_one())
    state = _upload_state(rows, reported)
    set_stage(session, project_id, Stage.UPLOAD, state, source=source)
    return state


async def refresh_upload_stage_async(
    session: AsyncSession, project_id: uuid.UUID, *, source: str
) -> StageState:
    await session.flush()  # the aggregate must see this transaction's pending changes
    rows = [tuple(r) for r in (await session.execute(_upload_aggregate_stmt(project_id))).all()]
    reported = int((await session.execute(_reported_stmt(project_id))).scalar_one())
    state = _upload_state(rows, reported)
    await set_stage_async(session, project_id, Stage.UPLOAD, state, source=source)
    return state


# --------------------------------------------------------------------------- ingest stage


def _ingest_aggregate_stmt(project_id: uuid.UUID):
    # Only uploaded files take part: a failed *upload* (never reached storage)
    # is not an ingestion failure.
    return (
        select(Asset.status, func.count())
        .where(Asset.project_id == project_id, Asset.deleted_at.is_(None), Asset.uploaded_at.is_not(None))
        .group_by(Asset.status)
    )


def _ingest_state(rows: list[tuple[str, int]]) -> StageState:
    counts = {status: int(n) for status, n in rows}
    waiting = counts.get(AssetStatus.UPLOADED.value, 0)
    running = counts.get(AssetStatus.INGESTING.value, 0)
    ready = counts.get(AssetStatus.READY.value, 0)
    failed = counts.get(AssetStatus.FAILED.value, 0)
    total = waiting + running + ready + failed
    if running:
        return StageState(StageStatus.RUNNING, round((ready + failed) / total, 4), f"{ready}/{total} tayyor")
    if waiting:
        return StageState(StageStatus.QUEUED, None, f"{waiting} ta fayl navbatda")
    if ready:
        detail = f"{ready} ta fayl tayyor" + (f", {failed} ta o'qilmadi" if failed else "")
        return StageState(StageStatus.DONE, 1.0, detail)
    if failed:
        return StageState(StageStatus.FAILED, None, f"{failed} ta fayl o'qilmadi")
    return StageState(StageStatus.PENDING, None, None)


def refresh_ingest_stage(session: Session, project_id: uuid.UUID, *, source: str) -> tuple[StageState, bool]:
    session.flush()
    state = _ingest_state([tuple(r) for r in session.execute(_ingest_aggregate_stmt(project_id)).all()])
    changed = set_stage(session, project_id, Stage.INGEST, state, source=source)
    return state, changed


async def refresh_ingest_stage_async(
    session: AsyncSession, project_id: uuid.UUID, *, source: str
) -> tuple[StageState, bool]:
    await session.flush()
    rows = [tuple(r) for r in (await session.execute(_ingest_aggregate_stmt(project_id))).all()]
    state = _ingest_state(rows)
    changed = await set_stage_async(session, project_id, Stage.INGEST, state, source=source)
    return state, changed


# --------------------------------------------------------------------------- transcription stage


def _transcription_aggregate_stmt(project_id: uuid.UUID):
    return (
        select(AssetTranscript.status, func.count(), func.coalesce(func.sum(AssetTranscript.word_count), 0))
        .join(Asset, Asset.id == AssetTranscript.asset_id)
        .where(AssetTranscript.project_id == project_id, Asset.deleted_at.is_(None))
        .group_by(AssetTranscript.status)
    )


def _audio_pending_stmt(project_id: uuid.UUID):
    """Uploaded files that may still bring speech: not ingested yet, or ingested with audio."""
    return select(func.count()).where(
        Asset.project_id == project_id,
        Asset.deleted_at.is_(None),
        Asset.uploaded_at.is_not(None),
        (Asset.status.in_([AssetStatus.UPLOADED.value, AssetStatus.INGESTING.value]))
        | (Asset.has_audio.is_(True)),
    )


def _transcription_state(rows: list[tuple[str, int, int]], audio_pending: int, ingested: bool) -> StageState:
    counts = {status: (int(n), int(words)) for status, n, words in rows}
    queued = counts.get(TranscriptStatus.QUEUED.value, (0, 0))[0]
    running = counts.get(TranscriptStatus.RUNNING.value, (0, 0))[0]
    done, words = counts.get(TranscriptStatus.DONE.value, (0, 0))
    failed = counts.get(TranscriptStatus.FAILED.value, (0, 0))[0]
    total = queued + running + done + failed
    if running:
        return StageState(StageStatus.RUNNING, round((done + failed) / total, 4), f"{done}/{total} tayyor")
    if queued:
        return StageState(StageStatus.QUEUED, None, f"{queued} ta fayl navbatda")
    if done:
        detail = f"{done} ta faylda nutq · {words} so'z" + (f", {failed} ta o'qilmadi" if failed else "")
        return StageState(StageStatus.DONE, 1.0, detail)
    if failed:
        return StageState(StageStatus.FAILED, None, f"{failed} ta faylda nutq o'qilmadi")
    if ingested and not audio_pending:
        return StageState(StageStatus.SKIPPED, None, "Ovozli fayl yo'q")
    return StageState(StageStatus.PENDING, None, None)


def _ingested_stmt(project_id: uuid.UUID):
    return select(func.count()).where(
        Asset.project_id == project_id, Asset.deleted_at.is_(None), Asset.status == AssetStatus.READY.value
    )


def refresh_transcription_stage(
    session: Session, project_id: uuid.UUID, *, source: str
) -> tuple[StageState, bool]:
    session.flush()
    rows = [tuple(r) for r in session.execute(_transcription_aggregate_stmt(project_id)).all()]
    pending = int(session.execute(_audio_pending_stmt(project_id)).scalar_one())
    ingested = int(session.execute(_ingested_stmt(project_id)).scalar_one()) > 0
    state = _transcription_state(rows, pending, ingested)
    changed = set_stage(session, project_id, Stage.TRANSCRIPTION, state, source=source)
    return state, changed


async def refresh_transcription_stage_async(
    session: AsyncSession, project_id: uuid.UUID, *, source: str
) -> tuple[StageState, bool]:
    await session.flush()
    rows = [tuple(r) for r in (await session.execute(_transcription_aggregate_stmt(project_id))).all()]
    pending = int((await session.execute(_audio_pending_stmt(project_id))).scalar_one())
    ingested = int((await session.execute(_ingested_stmt(project_id))).scalar_one()) > 0
    state = _transcription_state(rows, pending, ingested)
    changed = await set_stage_async(session, project_id, Stage.TRANSCRIPTION, state, source=source)
    return state, changed


# --------------------------------------------------------------------------- analysis stage


def _analysis_aggregate_stmt(project_id: uuid.UUID):
    return (
        select(AssetAnalysis.status, func.count(), func.coalesce(func.sum(AssetAnalysis.clip_count), 0))
        .join(Asset, Asset.id == AssetAnalysis.asset_id)
        .where(AssetAnalysis.project_id == project_id, Asset.deleted_at.is_(None))
        .group_by(AssetAnalysis.status)
    )


def _video_pending_stmt(project_id: uuid.UUID):
    """Uploaded files that may still turn out to be video, or are video."""
    return select(func.count()).where(
        Asset.project_id == project_id,
        Asset.deleted_at.is_(None),
        Asset.uploaded_at.is_not(None),
        (Asset.status.in_([AssetStatus.UPLOADED.value, AssetStatus.INGESTING.value]))
        | ((Asset.kind == "video") & (Asset.status == AssetStatus.READY.value)),
    )


def _analysis_state(rows: list[tuple[str, int, int]], video_pending: int, ingested: bool) -> StageState:
    counts = {status: (int(n), int(clips)) for status, n, clips in rows}
    queued = counts.get(AnalysisStatus.QUEUED.value, (0, 0))[0]
    running = counts.get(AnalysisStatus.RUNNING.value, (0, 0))[0]
    done, clips = counts.get(AnalysisStatus.DONE.value, (0, 0))
    failed = counts.get(AnalysisStatus.FAILED.value, (0, 0))[0]
    total = queued + running + done + failed
    if running:
        return StageState(StageStatus.RUNNING, round((done + failed) / total, 4), f"{done}/{total} tayyor")
    if queued:
        return StageState(StageStatus.QUEUED, None, f"{queued} ta video navbatda")
    if done:
        detail = f"{done} ta video · {clips} ta kadr" + (f", {failed} ta o'qilmadi" if failed else "")
        return StageState(StageStatus.DONE, 1.0, detail)
    if failed:
        return StageState(StageStatus.FAILED, None, f"{failed} ta video tahlil qilinmadi")
    if ingested and not video_pending:
        return StageState(StageStatus.SKIPPED, None, "Video fayl yo'q")
    return StageState(StageStatus.PENDING, None, None)


def refresh_analysis_stage(
    session: Session, project_id: uuid.UUID, *, source: str
) -> tuple[StageState, bool]:
    session.flush()
    rows = [tuple(r) for r in session.execute(_analysis_aggregate_stmt(project_id)).all()]
    pending = int(session.execute(_video_pending_stmt(project_id)).scalar_one())
    ingested = int(session.execute(_ingested_stmt(project_id)).scalar_one()) > 0
    state = _analysis_state(rows, pending, ingested)
    changed = set_stage(session, project_id, Stage.ANALYSIS, state, source=source)
    return state, changed


async def refresh_analysis_stage_async(
    session: AsyncSession, project_id: uuid.UUID, *, source: str
) -> tuple[StageState, bool]:
    await session.flush()
    rows = [tuple(r) for r in (await session.execute(_analysis_aggregate_stmt(project_id))).all()]
    pending = int((await session.execute(_video_pending_stmt(project_id))).scalar_one())
    ingested = int((await session.execute(_ingested_stmt(project_id))).scalar_one()) > 0
    state = _analysis_state(rows, pending, ingested)
    changed = await set_stage_async(session, project_id, Stage.ANALYSIS, state, source=source)
    return state, changed
