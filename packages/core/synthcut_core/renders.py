"""Edit plans, renders and deliveries (Phases 6/9/11/12 without a model).

* ``request_auto_edit`` queues the rule-based editor ("Tez montaj"); a
  second tap while one is queued or running returns the same job.
* ``request_render`` creates or re-uses the one ``renders`` row of a
  (plan version, preset, kind) and queues it — a finished render is returned
  as it is unless ``force``.
* ``request_delivery`` queues sending a finished render to the owner's chat.

Each has a sync variant (worker) and an async one (API); the rules live in
the shared ``_prepare_*`` helpers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from synthcut_schemas.enums import (
    AnalysisStatus,
    AssetStatus,
    DeliveryStatus,
    JobPriority,
    JobQueue,
    ProjectStatus,
    RenderKind,
    RenderStatus,
    Stage,
    StageStatus,
    TranscriptStatus,
)
from synthcut_schemas.jobs import AutoEditOptions, JobKind

from .jobs import enqueue, enqueue_async
from .models import Asset, AssetAnalysis, AssetTranscript, EditPlanRow, Job, Project, Render
from .stages import StageState, set_stage_async

ACTIVE_JOB = ("queued", "running")
ACTIVE_RENDER = (RenderStatus.QUEUED.value, RenderStatus.RUNNING.value)


def _active_edit_stmt(project_id: uuid.UUID):
    return (
        select(Job)
        .where(Job.project_id == project_id, Job.kind == JobKind.EDIT_AUTO, Job.status.in_(ACTIVE_JOB))
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def _edit_job(project_id: uuid.UUID, options: AutoEditOptions) -> dict:
    return {
        "kind": JobKind.EDIT_AUTO,
        "queue": JobQueue.CPU,
        "payload": options.model_dump(mode="json"),
        "project_id": project_id,
        "priority": JobPriority.HIGH,  # seconds of work; the owner is waiting
        "idempotency_key": f"{JobKind.EDIT_AUTO}:{project_id}:{uuid.uuid4().hex}",
        "max_attempts": 2,
    }


def request_auto_edit(s: Session, project_id: uuid.UUID, options: AutoEditOptions) -> tuple[uuid.UUID, bool]:
    """(job id, created) — a request while one is queued or running returns that one."""
    active = s.execute(_active_edit_stmt(project_id)).scalar_one_or_none()
    if active is not None:
        return active.id, False
    job_id, _ = enqueue(s, **_edit_job(project_id, options))
    return job_id, True


async def request_auto_edit_async(
    s: AsyncSession, project_id: uuid.UUID, options: AutoEditOptions
) -> tuple[uuid.UUID, bool]:
    active = (await s.execute(_active_edit_stmt(project_id))).scalar_one_or_none()
    if active is not None:
        return active.id, False
    job_id, _ = await enqueue_async(s, **_edit_job(project_id, options))
    return job_id, True


async def not_ready_reason_async(db: AsyncSession, project_id: uuid.UUID) -> tuple[str, str] | None:
    """Why Tez montaj cannot start yet (code, Uzbek message) — the cut follows
    speech and shots, so it waits for ingestion, transcription and analysis."""
    videos = (
        await db.execute(
            select(Asset.status, func.count())
            .where(Asset.project_id == project_id, Asset.deleted_at.is_(None), Asset.uploaded_at.is_not(None))
            .group_by(Asset.status)
        )
    ).all()
    counts = {status: int(n) for status, n in videos}
    if counts.get(AssetStatus.UPLOADED.value) or counts.get(AssetStatus.INGESTING.value):
        return "ingest_running", "Fayllar hali o'qilmoqda — tugashini kuting"
    ready_videos = (
        await db.execute(
            select(func.count()).where(
                Asset.project_id == project_id,
                Asset.deleted_at.is_(None),
                Asset.kind == "video",
                Asset.status == AssetStatus.READY.value,
            )
        )
    ).scalar_one()
    if not ready_videos:
        return "no_video", "Loyihada tayyor video yo'q"
    speech = (
        await db.execute(
            select(func.count()).where(
                AssetTranscript.project_id == project_id,
                AssetTranscript.status.in_([TranscriptStatus.QUEUED.value, TranscriptStatus.RUNNING.value]),
            )
        )
    ).scalar_one()
    if speech:
        return "speech_running", "Nutq hali matnga o'girilmoqda — montaj nutq bo'yicha kesadi, kuting"
    analysis = (
        await db.execute(
            select(func.count()).where(
                AssetAnalysis.project_id == project_id,
                AssetAnalysis.status.in_([AnalysisStatus.QUEUED.value, AnalysisStatus.RUNNING.value]),
            )
        )
    ).scalar_one()
    if analysis:
        return "analysis_running", "Kadrlar tahlili hali tugamagan — kuting"
    return None


@dataclass(frozen=True, slots=True)
class AutoEditStart:
    job_id: uuid.UUID | None
    created: bool  # False: one was already queued or running, that one stands
    refused: tuple[str, str] | None = None  # (code, message)


async def start_auto_edit_async(
    s: AsyncSession, project: Project, options: AutoEditOptions, *, source: str
) -> AutoEditStart:
    """Tez montaj for an active, ready project — from the Mini App or the chat."""
    if project.status != ProjectStatus.ACTIVE.value:
        return AutoEditStart(None, False, ("archived", "Arxivdagi loyihani montaj qilib bo'lmaydi"))
    reason = await not_ready_reason_async(s, project.id)
    if reason is not None:
        return AutoEditStart(None, False, reason)
    job_id, created = await request_auto_edit_async(s, project.id, options)
    if created:
        await set_stage_async(
            s,
            project.id,
            Stage.EDITOR,
            StageState(StageStatus.QUEUED, None, "Tez montaj navbatda"),
            source=source,
        )
    return AutoEditStart(job_id, created)


def next_version_stmt(project_id: uuid.UUID):
    return select(func.coalesce(func.max(EditPlanRow.version), 0) + 1).where(
        EditPlanRow.project_id == project_id
    )


# --------------------------------------------------------------------------- renders


def _render_stmt(project_id: uuid.UUID, version: int, preset: str, kind: str):
    return (
        select(Render)
        .where(
            Render.project_id == project_id,
            Render.plan_version == version,
            Render.preset == preset,
            Render.kind == kind,
        )
        .with_for_update()
    )


def _prepare_render(
    row: Render | None, plan: EditPlanRow, preset: str, deliver: bool, force: bool
) -> tuple[Render, bool]:
    """(row, queue it?)"""
    if row is None:
        row = Render(
            project_id=plan.project_id,
            plan_id=plan.id,
            plan_version=plan.version,
            preset=preset,
            kind=RenderKind.FINAL.value,
            runs=0,
        )
    elif row.status in ACTIVE_RENDER or (row.status == RenderStatus.DONE.value and not force):
        row.deliver = row.deliver or deliver
        return row, False
    row.status = RenderStatus.QUEUED.value
    row.progress = None
    row.step = None
    row.error = None
    row.qa = None
    row.qa_status = None
    row.deliver = deliver
    row.delivery_status = DeliveryStatus.NONE.value
    row.delivery_error = None
    row.runs = (row.runs or 0) + 1
    return row, True


def _render_job(row: Render) -> dict:
    return {
        "kind": JobKind.RENDER_FINAL,
        "queue": JobQueue.RENDER,
        "payload": {"render_id": str(row.id)},
        "project_id": row.project_id,
        "priority": JobPriority.NORMAL,
        "idempotency_key": f"{JobKind.RENDER_FINAL}:{row.id}:r{row.runs}",
        "max_attempts": 2,
    }


def request_render(
    s: Session, plan: EditPlanRow, *, preset: str, deliver: bool, force: bool = False
) -> tuple[Render, bool]:
    row = s.execute(
        _render_stmt(plan.project_id, plan.version, preset, RenderKind.FINAL.value)
    ).scalar_one_or_none()
    row, queue = _prepare_render(row, plan, preset, deliver, force)
    s.add(row)
    s.flush()
    if queue:
        enqueue(s, **_render_job(row))
    return row, queue


async def request_render_async(
    s: AsyncSession, plan: EditPlanRow, *, preset: str, deliver: bool, force: bool = False
) -> tuple[Render, bool]:
    stmt = _render_stmt(plan.project_id, plan.version, preset, RenderKind.FINAL.value)
    row = (await s.execute(stmt)).scalar_one_or_none()
    row, queue = _prepare_render(row, plan, preset, deliver, force)
    s.add(row)
    await s.flush()
    if queue:
        await enqueue_async(s, **_render_job(row))
    return row, queue


# --------------------------------------------------------------------------- delivery


def _delivery_job(row: Render) -> dict:
    return {
        "kind": JobKind.DELIVER_TELEGRAM,
        "queue": JobQueue.IO,
        "payload": {"render_id": str(row.id)},
        "project_id": row.project_id,
        "priority": JobPriority.HIGH,
        "idempotency_key": f"{JobKind.DELIVER_TELEGRAM}:{row.id}:{uuid.uuid4().hex}",
        "max_attempts": 4,
    }


def can_deliver(row: Render) -> bool:
    return row.status == RenderStatus.DONE.value and row.delivery_status != DeliveryStatus.QUEUED.value


def request_delivery(s: Session, row: Render) -> bool:
    if not can_deliver(row):
        return False
    row.delivery_status = DeliveryStatus.QUEUED.value
    row.delivery_error = None
    enqueue(s, **_delivery_job(row))
    return True


async def request_delivery_async(s: AsyncSession, row: Render) -> bool:
    if not can_deliver(row):
        return False
    row.delivery_status = DeliveryStatus.QUEUED.value
    row.delivery_error = None
    await enqueue_async(s, **_delivery_job(row))
    return True
