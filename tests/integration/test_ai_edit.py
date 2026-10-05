"""AI montaj end to end with a scripted model (no API key, no cost): the rules
draft, then Director → Editor → Motion → QA through the live tools, a plan
with a crossfade and a punch-in, every run recorded with its cost, the
render from the originals — and the refusals: no key, an invalid edit."""

import shutil
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from synthcut_core.models import AgentRun, EditPlanRow, Render
from synthcut_model_router import (
    CompletionResponse,
    ModelRouter,
    RouteTable,
    ScriptedProvider,
    StopReason,
    TextBlock,
    ToolUseBlock,
    Usage,
)
from synthcut_worker.agents import jobs as agent_jobs

from . import test_speech
from .conftest import make_project
from .test_autoedit import fake_layer  # noqa: F401 — fixture
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media
fake_engine = test_speech.fake_engine


@pytest.fixture
def ai_settings(settings):
    return settings.model_copy(
        update={"speech_auto": True, "analysis_auto": True, "anthropic_api_key": SecretStr("test-key")}
    )


def say(*blocks, stop=StopReason.TOOL_USE) -> CompletionResponse:
    return CompletionResponse(
        provider="x",
        model="m",
        content=list(blocks),
        stop_reason=stop,
        usage=Usage(input_tokens=2000, output_tokens=300),
    )


def tool(name: str, args: dict, n: int = 1) -> ToolUseBlock:
    return ToolUseBlock(id=f"toolu_{name}_{n}", name=name, input=args)


def script(asset: str) -> list[CompletionResponse]:
    story = [
        {"asset_id": asset, "source_in": 2.0, "source_out": 3.2, "why": "savol bilan ochamiz"},
        {
            "asset_id": asset,
            "source_in": 0.1,
            "source_out": 1.6,
            "transition": {"type": "crossfade", "duration": 0.3},
        },
    ]
    polished = [
        story[0],
        {**story[1], "placement": {"scale": 1.15}, "keyframes": [{"t": 0, "property": "scale", "value": 1.15},
                                                                  {"t": 1.0, "property": "scale", "value": 1.25}]},
    ]  # fmt: skip
    return [
        # Director
        say(tool("get_project_context", {})),
        say(tool("get_transcript", {"asset_id": asset})),
        say(tool("create_edit_plan", {"main": story, "notes": "Savoldan boshlaymiz, keyin salom"})),
        say(TextBlock(text="Hook: savol. Tartib o'zgardi."), stop=StopReason.END_TURN),
        # Editor: a broken edit first (source past the end), then the fix
        say(
            tool(
                "update_edit_plan",
                {"main": [{"asset_id": asset, "source_in": 50, "source_out": 60}], "notes": "xato"},
            )
        ),
        say(
            tool(
                "update_edit_plan", {"main": polished, "notes": "Ikkinchi bo'lakka punch-in va sekin zoom"}, 2
            )
        ),
        say(TextBlock(text="Punch-in va crossfade qo'shildi."), stop=StopReason.END_TURN),
        # Motion
        say(TextBlock(text="Grafika kerak emas — video juda qisqa."), stop=StopReason.END_TURN),
        # QA
        say(tool("validate_plan", {})),
        say(
            tool(
                "report_issues",
                {"findings": [{"severity": "warning", "message": "Juda qisqa video", "at": 1.0}]},
            )
        ),
        say(TextBlock(text="OK"), stop=StopReason.END_TURN),
    ]


async def test_ai_montaj_end_to_end(app, client, auth, ai_settings, media, Session, fake_layer, monkeypatch):  # noqa: F811
    monkeypatch.setattr(app.state, "settings", ai_settings)  # the API sees the key
    project = await make_project(client, auth)
    pid = project["id"]
    talk = await upload(client, auth, pid, media / "talk.mp4", "video/mp4")
    run_worker(ai_settings)

    status = (await client.get("/api/v1/ai/status", headers=auth)).json()
    assert status["enabled"] is True and status["models"]["reasoning"] == ["anthropic:claude-opus-5"]

    scripted = ScriptedProvider("anthropic", script(talk["id"]))
    monkeypatch.setattr(
        agent_jobs,
        "router_factory",
        lambda s: ModelRouter(RouteTable.from_json(None), {"anthropic": scripted}),
    )
    r = await client.post(
        f"/api/v1/projects/{pid}/ai-edit",
        json={"prompt": "Qisqa reels, savol bilan boshlansin", "deliver": False},
        headers=auth,
    )
    assert r.status_code == 202, r.text
    busy = await client.post(f"/api/v1/projects/{pid}/ai-edit", json={"prompt": "yana"}, headers=auth)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "busy"

    assert run_worker(ai_settings) == ["edit.auto"]  # the rules draft, no render
    assert run_worker(ai_settings, queues="llm") == ["agent.edit"]
    system, first = scripted.requests[0][1].system, scripted.requests[0][1]
    assert "House style" in system and "Director Agent" in system
    assert "savol bilan boshlansin" in first.messages[0].content[0].text
    assert {t.name for t in first.tools} >= {
        "create_edit_plan",
        "get_transcript",
    }  # the Director's tools only
    assert "update_edit_plan" not in {t.name for t in first.tools}

    with Session() as s:
        plans = {
            p.version: p
            for p in s.scalars(select(EditPlanRow).where(EditPlanRow.project_id == uuid.UUID(pid)))
        }
        assert sorted(plans) == [1, 2, 3]  # draft, Director, Editor (the broken edit was not saved)
        assert plans[1].plan["metadata"]["created_by"] == "rules"
        assert plans[2].plan["metadata"]["created_by"] == "director" and plans[2].source == "director"
        main = plans[3].plan["video_tracks"][0]["clips"]
        assert main[1]["transition_in"]["type"] == "crossfade" and main[1]["keyframes"][1]["value"] == 1.25
        runs = list(
            s.scalars(
                select(AgentRun).where(AgentRun.project_id == uuid.UUID(pid)).order_by(AgentRun.created_at)
            )
        )
        assert [r.agent for r in runs] == ["director", "editor", "motion", "qa"]
        assert runs[0].versions == [2] and runs[1].versions == [3]
        bad = runs[1].tool_calls[0]
        assert (
            bad["tool"] == "update_edit_plan" and bad["ok"] is True
        )  # returned ok=false issues to the model
        assert runs[3].findings[0]["severity"] == "warning" and runs[0].cost_usd > 0

    feedback_to_model = scripted.requests[5][1].messages[-1].content[0].content
    assert '"ok": false' in feedback_to_model and "starts after the asset ends (6 s)" in feedback_to_model

    listed = (await client.get(f"/api/v1/projects/{pid}/agent-runs", headers=auth)).json()
    assert len(listed["items"]) == 4 and listed["total_cost_usd"] > 0
    assert listed["items"][-1]["summary"].startswith("Hook")

    assert run_worker(ai_settings, queues="render") == ["render.final"]
    with Session() as s:
        render = s.scalar(select(Render).where(Render.project_id == uuid.UUID(pid)))
        assert (render.plan_version, render.status) == (3, "done"), render.error
    stages = {
        st["stage"]: st for st in (await client.get(f"/api/v1/projects/{pid}", headers=auth)).json()["stages"]
    }
    assert stages["director"]["status"] == "done" and "v3" in stages["director"]["detail"]


async def test_ai_montaj_needs_a_key(client, auth, settings, media):
    project = await make_project(client, auth)
    r = await client.post(f"/api/v1/projects/{project['id']}/ai-edit", json={"prompt": "x"}, headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_unavailable"
    assert (await client.get("/api/v1/ai/status", headers=auth)).json()["enabled"] is False
