"""AI montaj (Phase 6): the agent team on top of the rules draft, and what
each agent decided (the AI Decisions tab)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select
from synthcut_core.events import commit_and_publish
from synthcut_core.jobs import enqueue_async
from synthcut_core.models import AgentRun, EditPlanRow, Job
from synthcut_core.preferences import effective_defaults
from synthcut_core.renders import not_ready_reason_async, start_auto_edit_async
from synthcut_core.stages import StageState, set_stage_async
from synthcut_model_router import ModelRole, RouteTable
from synthcut_schemas.api import (
    AgentRunList,
    AgentRunOut,
    AiEditRequest,
    AiStatusOut,
    EditStateOut,
    ErrorResponse,
)
from synthcut_schemas.enums import JobPriority, JobQueue, ProjectStatus, Stage, StageStatus
from synthcut_schemas.jobs import AutoEditPayload, JobKind

from ..deps import AppSettings, CurrentUser, DbSession, RedisClient, StorageClient
from ..errors import ApiError
from .edits import edit_state, owned_project

router = APIRouter(tags=["ai"], responses={404: {"model": ErrorResponse}})


@router.get("/ai/status", response_model=AiStatusOut)
async def ai_status(_: CurrentUser, settings: AppSettings) -> AiStatusOut:
    table = RouteTable.from_json(settings.model_routes or None)
    return AiStatusOut(
        enabled=bool(settings.anthropic_api_key.get_secret_value()),
        models={role.value: [str(t) for t in table.targets(role)] for role in ModelRole},
        budget_usd=settings.agent_budget_usd,
    )


@router.post("/projects/{project_id}/ai-edit", response_model=EditStateOut, status_code=202)
async def ai_edit(
    project_id: uuid.UUID,
    body: AiEditRequest,
    user: CurrentUser,
    db: DbSession,
    redis: RedisClient,
    storage: StorageClient,
    settings: AppSettings,
) -> EditStateOut:
    """The agents edit on top of the rules draft: the latest plan if there is
    one (or a fresh draft first), then render and delivery as usual."""
    if not settings.anthropic_api_key.get_secret_value():
        raise ApiError(
            409,
            "ai_unavailable",
            "AI kaliti ulanmagan — ANTHROPIC_API_KEY kerak. Hozircha «Tez montaj» ishlaydi.",
        )
    project = await owned_project(db, user.id, project_id)
    if project.status != ProjectStatus.ACTIVE.value:
        raise ApiError(409, "archived", "Arxivdagi loyihani montaj qilib bo'lmaydi")
    running = (
        await db.execute(
            select(func.count()).where(
                Job.project_id == project.id,
                Job.kind.in_([JobKind.AGENT_EDIT, JobKind.EDIT_AUTO]),
                Job.status.in_(["queued", "running"]),
            )
        )
    ).scalar_one()
    if running:
        raise ApiError(409, "busy", "Montaj allaqachon jarayonda")
    latest = (
        await db.execute(select(func.max(EditPlanRow.version)).where(EditPlanRow.project_id == project.id))
    ).scalar_one()
    if latest is None or body.redraft:
        defaults, _ = await effective_defaults(db, user.id)
        draft = AutoEditPayload(
            **defaults.model_dump(exclude={"deliver"}),
            deliver=body.deliver,
            render=False,
            ai_prompt=body.prompt,
        )
        started = await start_auto_edit_async(db, project, draft, source="api")
        if started.refused is not None:
            raise ApiError(409, *started.refused)
    else:
        reason = await not_ready_reason_async(db, project.id)
        if reason is not None:
            raise ApiError(409, *reason)
        await enqueue_async(
            db,
            kind=JobKind.AGENT_EDIT,
            queue=JobQueue.LLM,
            payload={"base_version": latest, "prompt": body.prompt, "deliver": body.deliver},
            project_id=project.id,
            priority=JobPriority.HIGH,
            idempotency_key=f"{JobKind.AGENT_EDIT}:{project.id}:v{latest}:{uuid.uuid4().hex[:8]}",
            max_attempts=1,
        )
        await set_stage_async(
            db,
            project.id,
            Stage.DIRECTOR,
            StageState(StageStatus.QUEUED, None, "AI jamoa navbatda"),
            source="api",
        )
    await commit_and_publish(db, redis)
    return await edit_state(db, storage, settings.media_url_ttl_seconds, project)


@router.get("/projects/{project_id}/agent-runs", response_model=AgentRunList)
async def agent_runs(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AgentRunList:
    project = await owned_project(db, user.id, project_id)
    rows = list(
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.project_id == project.id)
                .order_by(AgentRun.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    return AgentRunList(
        items=[AgentRunOut.model_validate(r) for r in rows],
        total_cost_usd=round(sum(r.cost_usd for r in rows), 4),
    )
