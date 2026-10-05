"""AI montaj (Phase 6): the agent team edits on top of the rules draft, then
the chosen version is rendered and delivered like any other plan.

Runs on the ``llm`` queue (network-bound; the media work it causes goes to
the render queue as usual). Without an API key the job refuses with a
reason instead of pretending.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from synthcut_agents.runtime.orchestrator import Outcome, run_ai_edit
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import EditPlanRow, Project
from synthcut_core.renders import request_render
from synthcut_core.settings import Settings
from synthcut_core.stages import StageState, set_stage
from synthcut_model_router import AnthropicProvider, ModelRouter, RouteTable
from synthcut_schemas.enums import EventLevel, JobQueue, Stage, StageStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import AgentEditPayload, JobKind

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError
from ..registry import handler

SOURCE = "worker"


def default_router(settings: Settings) -> ModelRouter:
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        raise PermanentError("AI kaliti ulanmagan — ANTHROPIC_API_KEY kerak")
    return ModelRouter(
        RouteTable.from_json(settings.model_routes or None), {"anthropic": AnthropicProvider(key)}
    )


# Replaced in tests with a router on a ScriptedProvider.
router_factory: Callable[[Settings], ModelRouter] = default_router


def _stage(ctx: JobContext, stage: Stage, status: StageStatus, detail: str | None, progress=None) -> None:
    with ctx.session() as s:
        set_stage(s, ctx.job.project_id, stage, StageState(status, progress, detail), source=SOURCE)
        commit_and_publish_sync(s, ctx.redis)


def _finish(ctx: JobContext, payload: AgentEditPayload, outcome: Outcome) -> dict[str, Any]:
    project_id = ctx.job.project_id
    with ctx.session() as s:
        if outcome.final_version is None:
            reason = outcome.stopped or "Agentlar yaroqli versiya yozmadi"
            set_stage(
                s, project_id, Stage.DIRECTOR, StageState(StageStatus.FAILED, None, reason), source=SOURCE
            )
            emit(s, project_id=project_id, type=EventType.PLAN_FAILED, level=EventLevel.ERROR,
                 message=f"AI montaj natija bermadi — {reason}", source=SOURCE, job_id=ctx.job.id)  # fmt: skip
            commit_and_publish_sync(s, ctx.redis)
            return {"final_version": None, "cost_usd": outcome.cost_usd, "stopped": outcome.stopped}
        row = s.scalar(
            select(EditPlanRow).where(
                EditPlanRow.project_id == project_id, EditPlanRow.version == outcome.final_version
            )
        )
        detail = f"v{row.version} · ${outcome.cost_usd:.2f}" + (
            f" · {outcome.stopped}" if outcome.stopped else ""
        )
        set_stage(s, project_id, Stage.DIRECTOR, StageState(StageStatus.DONE, 1.0, detail), source=SOURCE)
        set_stage(
            s,
            project_id,
            Stage.EDITOR,
            StageState(StageStatus.DONE, 1.0, f"v{row.version} (AI) · {row.duration_sec:.1f} s"),
            source=SOURCE,
        )
        emit(
            s,
            project_id=project_id,
            type=EventType.PLAN_READY,
            message=f"AI montaj v{row.version}: {row.clip_count} bo'lak, {row.duration_sec:.1f} s, ${outcome.cost_usd:.2f}",
            source=SOURCE,
            data={"version": row.version, "plan_id": str(row.id), "agent": True},
            job_id=ctx.job.id,
        )
        render_id = None
        if payload.render:
            preset = (row.options or {}).get("preset") or s.get(Project, project_id).preset
            render, _ = request_render(s, row, preset=preset, deliver=payload.deliver, force=True)
            render_id = str(render.id)
            set_stage(
                s, project_id, Stage.RENDER, StageState(StageStatus.QUEUED, None, "Navbatda"), source=SOURCE
            )
        commit_and_publish_sync(s, ctx.redis)
    return {
        "final_version": outcome.final_version,
        "cost_usd": outcome.cost_usd,
        "render_id": render_id,
        "runs": len(outcome.runs),
    }


@handler(JobKind.AGENT_EDIT, queue=JobQueue.LLM)
def agent_edit(ctx: JobContext, payload: AgentEditPayload) -> dict[str, Any]:
    if ctx.job.project_id is None:
        raise PermanentError("project_missing")
    router = router_factory(ctx.settings)
    _stage(ctx, Stage.DIRECTOR, StageStatus.RUNNING, "AI jamoa ishlayapti", 0.0)

    def progress(fraction: float, message: str) -> None:
        ctx.progress(fraction, message)

    try:
        outcome = run_ai_edit(
            project_id=ctx.job.project_id,
            base_version=payload.base_version,
            request=payload.prompt,
            router=router,
            sessions=ctx.sessions,
            storage=ctx.storage,
            budget_usd=ctx.settings.agent_budget_usd,
            job_id=ctx.job.id,
            progress=progress,
            check=ctx.check,
        )
    except (LeaseLost, JobInterrupted, JobCancelled):
        raise
    except Exception as exc:
        if ctx.job.attempts >= ctx.job.max_attempts:
            _stage(ctx, Stage.DIRECTOR, StageStatus.FAILED, f"{type(exc).__name__}: {exc}"[:200])
        raise
    return _finish(ctx, payload, outcome)
