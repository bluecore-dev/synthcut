"""Preferences and feedback (spec §26 Memory, Phase 10): what the next Tez
montaj starts from, and quick corrections on a finished video that change
it by fixed, explained rules."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from synthcut_core.events import commit_and_publish, emit
from synthcut_core.models import EditPlanRow, Feedback, Project, Render
from synthcut_core.preferences import FEEDBACK_RULES, apply_feedback, effective_defaults, store
from synthcut_core.renders import not_ready_reason_async, request_auto_edit_async
from synthcut_core.stages import StageState, set_stage_async
from synthcut_schemas.api import (
    EditPreferencesOut,
    ErrorResponse,
    FeedbackList,
    FeedbackOption,
    FeedbackOut,
    FeedbackRequest,
)
from synthcut_schemas.enums import ProjectStatus, Stage, StageStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import AutoEditOptions

from ..deps import CurrentUser, DbSession, RedisClient
from ..errors import ApiError, not_found
from .edits import owned_project

router = APIRouter(tags=["memory"], responses={404: {"model": ErrorResponse}})

PER_VIDEO = ("preset", "target_duration", "title", "cta")


@router.get("/preferences/edit", response_model=EditPreferencesOut)
async def get_edit_preferences(user: CurrentUser, db: DbSession) -> EditPreferencesOut:
    values, sources = await effective_defaults(db, user.id)
    return EditPreferencesOut(
        values=values,
        sources=sources,
        feedback_options=[
            FeedbackOption(code=code, label=label) for code, (label, _) in FEEDBACK_RULES.items()
        ],
    )


@router.post("/renders/{render_id}/feedback", response_model=FeedbackOut, status_code=201)
async def give_feedback(
    render_id: uuid.UUID, body: FeedbackRequest, user: CurrentUser, db: DbSession, redis: RedisClient
) -> FeedbackOut:
    """Quick codes change the user's preferences by fixed rules (returned as
    explained changes); a comment is kept for the Memory agent. ``remake``
    starts a new Tez montaj version from the corrected preferences, keeping
    this version's format, length, title and call to action."""
    found = (
        await db.execute(
            select(Render, Project)
            .join(Project, Project.id == Render.project_id)
            .where(Render.id == render_id, Project.owner_id == user.id)
        )
    ).one_or_none()
    if found is None:
        raise not_found("Render")
    render, project = found
    comment = (body.comment or "").strip() or None
    if not body.codes and comment is None:
        raise ApiError(422, "empty_feedback", "Fikr bo'sh: tugma tanlang yoki yozing")
    if body.remake:
        if project.status != ProjectStatus.ACTIVE.value:
            raise ApiError(409, "archived", "Arxivdagi loyihani montaj qilib bo'lmaydi")
        reason = await not_ready_reason_async(db, project.id)
        if reason is not None:
            raise ApiError(409, *reason)

    current, _ = await effective_defaults(db, user.id)
    updated, changes = apply_feedback(current, body.codes)
    row = Feedback(
        user_id=user.id,
        project_id=project.id,
        render_id=render.id,
        plan_version=render.plan_version,
        codes=list(body.codes),
        comment=comment,
        at_sec=body.at_sec,
        changes=[{"key": c.key, "before": c.before, "after": c.after, "label": c.label} for c in changes],
    )
    db.add(row)
    await db.flush()
    await store(db, user.id, {c.key: c.after for c in changes}, source="feedback", feedback_id=row.id)
    summary = "; ".join(c.label for c in changes) or "izoh saqlandi"
    emit(
        db,
        project_id=project.id,
        type=EventType.FEEDBACK_RECORDED,
        message=f"Fikr eslab qolindi (v{render.plan_version}): {summary}",
        source="api",
        data={"render_id": str(render.id), "feedback_id": str(row.id)},
    )

    remake_job = None
    if body.remake:
        plan = (
            await db.execute(select(EditPlanRow).where(EditPlanRow.id == render.plan_id))
        ).scalar_one_or_none()
        kept = {
            k: v
            for k, v in ((plan.options if plan else {}) or {}).items()
            if k in PER_VIDEO and v is not None
        }
        options = AutoEditOptions(**updated.model_dump(), **kept, render=True)
        remake_job, _ = await request_auto_edit_async(db, project.id, options)
        await set_stage_async(
            db,
            project.id,
            Stage.EDITOR,
            StageState(StageStatus.QUEUED, None, "Fikr asosida qayta montaj"),
            source="api",
        )
    await commit_and_publish(db, redis)
    out = FeedbackOut.model_validate(row)
    out.remake_job_id = remake_job
    return out


@router.get("/projects/{project_id}/feedback", response_model=FeedbackList)
async def list_feedback(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FeedbackList:
    project = await owned_project(db, user.id, project_id)
    rows = await db.execute(
        select(Feedback)
        .where(Feedback.project_id == project.id)
        .order_by(Feedback.created_at.desc())
        .limit(100)
    )
    return FeedbackList(items=[FeedbackOut.model_validate(r) for r in rows.scalars()])
