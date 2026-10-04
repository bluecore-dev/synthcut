"""Edit plans, renders and delivery (Phases 6/9/11/12 without a model):
"Tez montaj", plan versions, final renders with their QA, and sending a
render to the owner's chat."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_core.events import commit_and_publish
from synthcut_core.models import Asset, AssetAnalysis, AssetTranscript, EditPlanRow, Job, Project, Render
from synthcut_core.preferences import remember_choice
from synthcut_core.projects import get_owned_project
from synthcut_core.renders import request_auto_edit_async, request_delivery_async, request_render_async
from synthcut_core.stages import StageState, set_stage_async
from synthcut_schemas.api import (
    AutoEditRequest,
    EditJobOut,
    EditStateOut,
    ErrorResponse,
    PlanClipOut,
    PlanGraphicOut,
    PlanList,
    PlanOut,
    PlanSummary,
    RenderList,
    RenderOut,
    RenderRequest,
)
from synthcut_schemas.enums import (
    AnalysisStatus,
    AssetStatus,
    ProjectStatus,
    RenderStatus,
    Stage,
    StageStatus,
    TranscriptStatus,
)
from synthcut_schemas.jobs import JobKind
from synthcut_storage import Storage

from ..deps import AppSettings, CurrentUser, DbSession, RedisClient, StorageClient
from ..errors import ApiError, not_found
from .media import sign

router = APIRouter(tags=["edits"], responses={404: {"model": ErrorResponse}})


async def owned_project(db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = await get_owned_project(db, user_id, project_id)
    if project is None:
        raise not_found("Loyiha")
    return project


# --------------------------------------------------------------------------- state


async def _render_jobs(db: AsyncSession, ids: list[uuid.UUID]) -> dict[str, Job]:
    """The newest ``render.final`` job of each render: a render whose worker
    died (job dead, row still running) is shown as failed, not forever busy."""
    if not ids:
        return {}
    rows = await db.execute(
        select(Job)
        .where(Job.kind == JobKind.RENDER_FINAL, Job.payload["render_id"].astext.in_([str(i) for i in ids]))
        .order_by(Job.created_at)
    )
    return {j.payload["render_id"]: j for j in rows.scalars()}


def render_out(row: Render, job: Job | None, storage: Storage, ttl: int, *, name: str) -> RenderOut:
    out = RenderOut.model_validate(row)
    if row.status in (RenderStatus.QUEUED.value, RenderStatus.RUNNING.value) and job is not None:
        if job.status in ("dead", "cancelled"):
            out.status = RenderStatus.FAILED
            out.error = ((job.error or {}).get("message") or "Render to'xtadi")[:300]
        elif job.status == "running" and job.progress is not None:
            out.progress, out.step = job.progress, job.progress_message or row.step
    if row.output_key:
        stem = PurePosixPath(name).stem or "video"
        out.video = sign(storage, row.output_key, ttl)
        out.download = sign(storage, row.output_key, ttl, download_name=f"{stem}_v{row.plan_version}.mp4")
    if row.poster_key:
        out.poster = sign(storage, row.poster_key, ttl)
    return out


async def _renders(
    db: AsyncSession, storage: Storage, ttl: int, project: Project, *, limit: int = 50
) -> list[RenderOut]:
    rows = list(
        (
            await db.execute(
                select(Render)
                .where(Render.project_id == project.id)
                .order_by(Render.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    jobs = await _render_jobs(db, [r.id for r in rows])
    return [render_out(r, jobs.get(str(r.id)), storage, ttl, name=project.name) for r in rows]


def _edit_job_out(job: Job) -> EditJobOut:
    return EditJobOut(
        id=job.id,
        status=job.status,
        progress=job.progress,
        step=job.progress_message,
        error=((job.error or {}).get("message") or None) if job.error else None,
        created_at=job.created_at,
    )


async def edit_state(db: AsyncSession, storage: Storage, ttl: int, project: Project) -> EditStateOut:
    job = (
        await db.execute(
            select(Job)
            .where(Job.project_id == project.id, Job.kind == JobKind.EDIT_AUTO)
            .order_by(Job.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    plan = (
        await db.execute(
            select(EditPlanRow)
            .where(EditPlanRow.project_id == project.id)
            .order_by(EditPlanRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    renders = await _renders(db, storage, ttl, project, limit=1)
    return EditStateOut(
        job=_edit_job_out(job) if job else None,
        plan=PlanSummary.model_validate(plan) if plan else None,
        render=renders[0] if renders else None,
    )


# --------------------------------------------------------------------------- endpoints


async def not_ready_reason(db: AsyncSession, project_id: uuid.UUID) -> tuple[str, str] | None:
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


@router.post("/projects/{project_id}/auto-edit", response_model=EditStateOut, status_code=202)
async def auto_edit(
    project_id: uuid.UUID,
    body: AutoEditRequest,
    user: CurrentUser,
    db: DbSession,
    redis: RedisClient,
    storage: StorageClient,
    settings: AppSettings,
) -> EditStateOut:
    """Tez montaj: pauses and bad shots cut, reframed, graded, mixed,
    captioned — then rendered from the originals and (optionally) sent to
    the chat. A second request while one is running returns that one."""
    project = await owned_project(db, user.id, project_id)
    if project.status != ProjectStatus.ACTIVE.value:
        raise ApiError(409, "archived", "Arxivdagi loyihani montaj qilib bo'lmaydi")
    reason = await not_ready_reason(db, project.id)
    if reason is not None:
        raise ApiError(409, *reason)
    await request_auto_edit_async(db, project.id, body)
    await remember_choice(db, user.id, body)  # the next Tez montaj starts from these
    await set_stage_async(
        db,
        project.id,
        Stage.EDITOR,
        StageState(StageStatus.QUEUED, None, "Tez montaj navbatda"),
        source="api",
    )
    await commit_and_publish(db, redis)
    return await edit_state(db, storage, settings.media_url_ttl_seconds, project)


@router.get("/projects/{project_id}/edit", response_model=EditStateOut)
async def get_edit_state(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: StorageClient, settings: AppSettings
) -> EditStateOut:
    project = await owned_project(db, user.id, project_id)
    return await edit_state(db, storage, settings.media_url_ttl_seconds, project)


@router.get("/projects/{project_id}/plans", response_model=PlanList)
async def list_plans(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PlanList:
    project = await owned_project(db, user.id, project_id)
    rows = await db.execute(
        select(EditPlanRow).where(EditPlanRow.project_id == project.id).order_by(EditPlanRow.version.desc())
    )
    return PlanList(items=[PlanSummary.model_validate(r) for r in rows.scalars()])


def plan_out(row: EditPlanRow, names: dict[str, str]) -> PlanOut:
    plan = row.plan
    seq = plan["sequence"]
    main = next((t for t in plan["video_tracks"] if t.get("role") == "main"), plan["video_tracks"][0])
    clips = []
    for c in sorted(main["clips"], key=lambda c: c["timeline_start"]):
        effects = {e["type"]: e.get("params", {}) for e in c.get("effects", [])}
        transform = c.get("transform") or {}
        clips.append(
            PlanClipOut(
                id=c["id"],
                asset_id=c["asset_id"],
                asset_name=names.get(str(c["asset_id"])),
                source_in=c["source_in"],
                source_out=c["source_out"],
                timeline_start=c["timeline_start"],
                timeline_end=c["timeline_end"],
                reframed=bool(transform.get("x") or transform.get("y")),
                fill="blur" if effects.get("background", {}).get("fill") == "blur" else "cover",
                exposure=effects["grade"].get("exposure") if "grade" in effects else None,
            )
        )
    graphics = [
        PlanGraphicOut(
            id=g["id"],
            component=g["component"],
            timeline_start=g["timeline_start"],
            timeline_end=g["timeline_end"],
            text=(g.get("props") or {}).get("title") or (g.get("props") or {}).get("text"),
        )
        for g in plan.get("graphics", [])
    ]
    mix = (plan.get("metadata") or {}).get("mix") or {}
    captions = plan.get("captions")
    return PlanOut(
        **PlanSummary.model_validate(row).model_dump(),
        width=seq["width"],
        height=seq["height"],
        fps=seq["fps"],
        captions=captions["style"] if captions and captions.get("enabled", True) else None,
        loudness_lufs=(mix.get("loudness") or {}).get("target_lufs"),
        clips=clips,
        graphics=graphics,
    )


async def _plan_row(db: AsyncSession, project_id: uuid.UUID, version: int) -> EditPlanRow:
    row = (
        await db.execute(
            select(EditPlanRow).where(EditPlanRow.project_id == project_id, EditPlanRow.version == version)
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Reja versiyasi")
    return row


@router.get("/projects/{project_id}/plans/{version}", response_model=PlanOut)
async def get_plan(project_id: uuid.UUID, version: int, user: CurrentUser, db: DbSession) -> PlanOut:
    project = await owned_project(db, user.id, project_id)
    row = await _plan_row(db, project.id, version)
    names = {
        str(i): n
        for i, n in (
            await db.execute(select(Asset.id, Asset.original_filename).where(Asset.project_id == project.id))
        ).all()
    }
    return plan_out(row, names)


@router.post("/projects/{project_id}/plans/{version}/render", response_model=RenderOut, status_code=202)
async def render_plan(
    project_id: uuid.UUID,
    version: int,
    body: RenderRequest,
    user: CurrentUser,
    db: DbSession,
    redis: RedisClient,
    storage: StorageClient,
    settings: AppSettings,
) -> RenderOut:
    """Render a plan version (again). The plan fixes the frame size, so the
    preset must be the one it was made for — another format is a new plan."""
    project = await owned_project(db, user.id, project_id)
    row = await _plan_row(db, project.id, version)
    preset = (row.options or {}).get("preset") or project.preset
    if body.preset is not None and body.preset.value != preset:
        raise ApiError(409, "preset_mismatch", "Boshqa format uchun yangi montaj qiling")
    render, queued = await request_render_async(
        db, row, preset=preset, deliver=body.deliver, force=body.force
    )
    if queued:
        await set_stage_async(
            db, project.id, Stage.RENDER, StageState(StageStatus.QUEUED, None, "Navbatda"), source="api"
        )
    elif body.deliver:
        await request_delivery_async(db, render)
    await commit_and_publish(db, redis)
    await db.refresh(render)
    jobs = await _render_jobs(db, [render.id])
    return render_out(
        render, jobs.get(str(render.id)), storage, settings.media_url_ttl_seconds, name=project.name
    )


@router.get("/projects/{project_id}/renders", response_model=RenderList)
async def list_renders(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: StorageClient, settings: AppSettings
) -> RenderList:
    project = await owned_project(db, user.id, project_id)
    return RenderList(items=await _renders(db, storage, settings.media_url_ttl_seconds, project))


@router.post("/renders/{render_id}/deliver", response_model=RenderOut, status_code=202)
async def deliver_render(
    render_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    redis: RedisClient,
    storage: StorageClient,
    settings: AppSettings,
) -> RenderOut:
    row = (
        await db.execute(
            select(Render)
            .join(Project, Project.id == Render.project_id)
            .where(Render.id == render_id, Project.owner_id == user.id)
            .with_for_update(of=Render)
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Render")
    if row.status != RenderStatus.DONE.value:
        raise ApiError(409, "not_ready", "Render hali tayyor emas")
    if await request_delivery_async(db, row):
        await set_stage_async(
            db,
            row.project_id,
            Stage.DELIVERY,
            StageState(StageStatus.QUEUED, None, "Telegramga"),
            source="api",
        )
    await commit_and_publish(db, redis)
    await db.refresh(row)
    project = await db.get(Project, row.project_id)
    jobs = await _render_jobs(db, [row.id])
    return render_out(row, jobs.get(str(row.id)), storage, settings.media_url_ttl_seconds, name=project.name)
