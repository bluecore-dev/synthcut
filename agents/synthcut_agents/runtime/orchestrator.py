"""AI montaj: the team at work on one project (spec §14-27).

The Master's job — who runs next, when to stop — is done here in code, not
by another model call: the order is fixed and cheap to reason about.

    Director  → the story (create_edit_plan)
    Editor    → cut points, punch-ins, cutaways, transitions, speed (update_edit_plan)
    Motion    → titles, key words, call to action (place_graphics)
    QA        → validation + a read against the transcript (report_issues)
    Editor    → one fix round if QA reported errors

Every run is recorded (``agent_runs``): status, steps, tokens, cost, tool
calls, the plan versions it wrote, what it told the owner. One budget covers
the whole montaj; a run never gets more than what is left of it.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from synthcut_agent_sdk import AgentRunResult, ToolContext, run_agent
from synthcut_core.models import AgentRun, EditPlanRow, Project, utcnow
from synthcut_model_router import Message, ModelRouter, TextBlock
from synthcut_timeline import load_plan

from ..team import TEAM
from .planedit import summary
from .playbook import DIRECTOR_TASK, EDITOR_TASK, FIX_TASK, MOTION_TASK, QA_TASK, system_prompt
from .tools import build_live_registry

TITLES = {
    "director": "Rejissor",
    "editor": "Montajchi",
    "motion": "Grafika",
    "qa": "Sifat nazorati",
}
SHARE = {
    "director": (0.0, 0.35),
    "editor": (0.35, 0.7),
    "motion": (0.7, 0.82),
    "qa": (0.82, 0.92),
    "fix": (0.92, 1.0),
}


@dataclass
class Outcome:
    final_version: int | None
    cost_usd: float = 0.0
    runs: list[uuid.UUID] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stopped: str | None = None


Progress = Callable[[float, str], None]


def _latest(sessions, project_id: uuid.UUID) -> int | None:
    with sessions() as s:
        return s.scalar(select(func.max(EditPlanRow.version)).where(EditPlanRow.project_id == project_id))


def _brief(sessions, project_id: uuid.UUID, version: int) -> tuple[str, str]:
    with sessions() as s:
        project = s.get(Project, project_id)
        row = s.scalar(
            select(EditPlanRow).where(EditPlanRow.project_id == project_id, EditPlanRow.version == version)
        )
        context = (
            f"{project.name}; preset {project.preset}, {project.fps} fps, "
            f"target {project.target_duration_sec or 'none'} s, language {project.language}; brief: {project.brief or '-'}"
        )
        return context, summary(load_plan(row.plan)) + (f" — {row.notes}" if row.notes else "")


def _record(
    sessions, project_id, job_id, name, result: AgentRunResult | None, services, model, started, error=None
):
    calls = []
    for c in result.tool_calls if result else []:
        calls.append(
            {
                "tool": c.tool,
                "ok": c.ok,
                "error": c.error_code,
                "ms": c.duration_ms,
                "input": json.dumps(c.input, ensure_ascii=False, default=str)[:400],
            }
        )
    with sessions() as s:
        row = AgentRun(
            project_id=project_id,
            job_id=job_id,
            agent=name,
            status=result.status if result else "failed",
            steps=result.steps if result else 0,
            model=model,
            input_tokens=result.usage.input_tokens if result else 0,
            output_tokens=result.usage.output_tokens if result else 0,
            cache_read_tokens=result.usage.cache_read_input_tokens if result else 0,
            cache_write_tokens=result.usage.cache_creation_input_tokens if result else 0,
            cost_usd=result.cost_usd if result else 0.0,
            summary=(result.final_text or None) if result else None,
            tool_calls=calls,
            versions=list(services.get("versions", [])),
            findings=list(services.get("findings", [])),
            error=error,
            started_at=started,
            finished_at=utcnow(),
        )
        s.add(row)
        s.commit()
        return row.id


def run_ai_edit(
    *,
    project_id: uuid.UUID,
    base_version: int,
    request: str,
    router: ModelRouter,
    sessions,
    storage: Any = None,
    budget_usd: float = 3.0,
    job_id: uuid.UUID | None = None,
    progress: Progress | None = None,
    check: Callable[[], None] | None = None,
) -> Outcome:
    registry = build_live_registry()
    outcome = Outcome(final_version=None)
    context, base_summary = _brief(sessions, project_id, base_version)
    request = request.strip() or "Make the best short edit of this material for social media."

    def run(name: str, step: str, task: str) -> dict[str, Any]:
        if check:
            check()
        remaining = budget_usd - outcome.cost_usd
        if remaining <= 0.01:
            outcome.stopped = f"Byudjet tugadi (${budget_usd:g})"
            return {}
        agent = dataclasses.replace(TEAM[name], max_cost_usd=min(TEAM[name].max_cost_usd, remaining))
        services: dict[str, Any] = {"sessions": sessions, "storage": storage, "agent": name}
        model: dict[str, str] = {}
        lo, hi = SHARE[step]

        def on_step(n: int, response, records) -> None:
            model["name"] = f"{response.provider}:{response.model}"
            if progress:
                done = [r.tool for r in records]
                progress(
                    lo + (hi - lo) * min(1.0, n / agent.max_steps),
                    f"{TITLES[name]}: {', '.join(done) or 'fikrlayapti'}",
                )

        started = utcnow()
        if progress:
            progress(lo, f"{TITLES[name]} ishlayapti")
        try:
            result = run_agent(
                agent,
                router=router,
                registry=registry,
                ctx=ToolContext(project_id=project_id, job_id=job_id, services=services),
                system=system_prompt(agent),
                messages=[Message(role="user", content=[TextBlock(text=task)])],
                on_step=on_step,
            )
        except Exception as exc:
            outcome.runs.append(
                _record(
                    sessions,
                    project_id,
                    job_id,
                    name,
                    None,
                    services,
                    model.get("name"),
                    started,
                    f"{type(exc).__name__}: {exc}"[:500],
                )
            )
            raise
        outcome.cost_usd = round(outcome.cost_usd + result.cost_usd, 6)
        outcome.runs.append(
            _record(sessions, project_id, job_id, name, result, services, model.get("name"), started)
        )
        if result.final_text:
            outcome.notes.append(f"{TITLES[name]}: {result.final_text.strip()[:600]}")
        if result.status == "budget_exceeded":
            outcome.stopped = f"Byudjet tugadi (${budget_usd:g})"
        return services

    def latest() -> int:
        return _latest(sessions, project_id) or base_version

    director = run(
        "director",
        "director",
        DIRECTOR_TASK.format(base=base_version, request=request, context=context, base_summary=base_summary),
    )
    if outcome.stopped is None:
        notes = next((n for n in outcome.notes if n.startswith(TITLES["director"])), "-")
        run("editor", "editor", EDITOR_TASK.format(version=latest(), request=request, notes=notes))
    if outcome.stopped is None:
        run("motion", "motion", MOTION_TASK.format(version=latest(), request=request))
    qa: dict[str, Any] = {}
    if outcome.stopped is None:
        qa = run("qa", "qa", QA_TASK.format(version=latest()))
    errors = [f for f in qa.get("findings", []) if f.get("severity") == "error"]
    if errors and outcome.stopped is None:
        listed = "\n".join(
            f"- {f['message']}" + (f" (at {f['at']} s)" if f.get("at") is not None else "") for f in errors
        )
        run("editor", "fix", FIX_TASK.format(version=latest(), findings=listed))

    final = latest()
    outcome.final_version = final if final > base_version else None
    if not director and outcome.final_version is None and outcome.stopped is None:
        outcome.stopped = "Agentlar yangi versiya yozmadi"
    return outcome
