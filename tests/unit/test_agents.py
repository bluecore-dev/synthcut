import pathlib
import uuid

import pytest
from pydantic import BaseModel, ConfigDict
from synthcut_agent_sdk import (
    AgentSpec,
    ToolContext,
    ToolRegistry,
    ToolScope,
    ToolSpec,
    UnsafeToolError,
    invoke_tool,
    run_agent,
)
from synthcut_agents import TEAM, TOOL_CATALOG, build_registry
from synthcut_model_router import (
    CompletionResponse,
    ModelRole,
    ModelRouter,
    RouteTable,
    ScriptedProvider,
    StopReason,
    TextBlock,
    ToolUseBlock,
    Usage,
)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- team manifests


def test_team_matches_spec_roster():
    assert set(TEAM) == {
        "master",
        "video_analysis",
        "director",
        "editor",
        "color",
        "audio",
        "motion",
        "caption",
        "research",
        "qa",
        "reflection",
        "memory",
        "render",
    }


def test_every_granted_tool_is_in_the_catalog():
    for agent in TEAM.values():
        assert agent.tools <= set(TOOL_CATALOG), (agent.name, agent.tools - set(TOOL_CATALOG))


def test_spec_28_tool_sets():
    assert {"get_project_context", "get_transcript", "get_video_analysis", "create_edit_plan"} <= TEAM[
        "director"
    ].tools
    assert {"get_media_metadata", "analyze_color", "generate_grade"} <= TEAM["color"].tools
    assert {"validate_plan", "render_remotion", "render_ffmpeg", "get_render_logs"} <= TEAM["render"].tools


def test_only_research_leaves_the_system():
    external = {n for n, (scope, _, _) in TOOL_CATALOG.items() if scope is ToolScope.EXTERNAL}
    for agent in TEAM.values():
        if agent.name != "research":
            assert not agent.tools & external, agent.name


def test_only_render_agent_renders():
    for agent in TEAM.values():
        if agent.name != "render":
            assert not agent.tools & {"render_remotion", "render_ffmpeg"}, agent.name


def test_director_cannot_touch_media_jobs():
    compute = {n for n, (scope, _, _) in TOOL_CATALOG.items() if scope is ToolScope.MEDIA}
    assert not TEAM["director"].tools & compute


# --------------------------------------------------------------------------- tool safety


def test_registry_refuses_path_and_command_inputs():
    class WithPath(_In):
        clip: str
        output_path: str

    class WithCommand(_In):
        command: str

    class Nested(_In):
        target: pathlib.Path

    class Outer(_In):
        inner: list[Nested]

    class Loose(BaseModel):
        asset_id: uuid.UUID

    for model in (WithPath, WithCommand, Outer, Loose):
        with pytest.raises(UnsafeToolError):
            ToolRegistry().declare(ToolSpec("bad_tool", "x", ToolScope.READ, 1, input_model=model))


def test_catalog_declares_cleanly():
    registry = build_registry()
    assert registry.names() == set(TOOL_CATALOG)
    assert all(not spec.implemented for spec in registry.all())  # handlers arrive with their phases


class EchoIn(_In):
    asset_id: uuid.UUID


class EchoOut(BaseModel):
    seen: str


def _registry_with_echo(calls):
    registry = ToolRegistry()

    def handler(ctx, args):
        calls.append((ctx.project_id, args.asset_id))
        return EchoOut(seen=str(args.asset_id))

    registry.declare(ToolSpec("echo_asset", "echo", ToolScope.READ, 0, EchoIn, EchoOut, handler))
    registry.declare(ToolSpec("secret_tool", "x", ToolScope.PLAN, 0, EchoIn, EchoOut, handler))
    return registry


AGENT = AgentSpec("tester", "Tester", "test", ModelRole.FAST, frozenset({"echo_asset"}), phase=0, max_steps=4)


def test_permission_gate_and_validation():
    calls = []
    registry = _registry_with_echo(calls)
    ctx = ToolContext(project_id=uuid.uuid4())
    aid = uuid.uuid4()
    ok = invoke_tool(AGENT, registry, ctx, "echo_asset", {"asset_id": str(aid)})
    assert ok.ok and ok.output == {"seen": str(aid)}
    denied = invoke_tool(AGENT, registry, ctx, "secret_tool", {"asset_id": str(aid)})
    assert not denied.ok and denied.error_code == "permission_denied"
    bad = invoke_tool(AGENT, registry, ctx, "echo_asset", {"asset_id": "nope", "path": "/etc/passwd"})
    assert not bad.ok and bad.error_code == "invalid_input"
    assert len(calls) == 1


# --------------------------------------------------------------------------- agent loop


def resp(*blocks, stop=StopReason.END_TURN, out=10):
    return CompletionResponse(
        provider="x",
        model="y",
        content=list(blocks),
        stop_reason=stop,
        usage=Usage(input_tokens=100, output_tokens=out),
    )


def _router(provider):
    return ModelRouter(
        RouteTable({role: ("anthropic:claude-opus-5",) for role in ModelRole}), {"anthropic": provider}
    )


def test_loop_runs_tools_then_finishes():
    calls = []
    aid = uuid.uuid4()
    provider = ScriptedProvider(
        "anthropic",
        [
            resp(
                ToolUseBlock(id="t1", name="echo_asset", input={"asset_id": str(aid)}),
                ToolUseBlock(id="t2", name="secret_tool", input={"asset_id": str(aid)}),
                stop=StopReason.TOOL_USE,
            ),
            resp(TextBlock(text="done")),
        ],
    )
    result = run_agent(
        AGENT,
        router=_router(provider),
        registry=_registry_with_echo(calls),
        ctx=ToolContext(project_id=uuid.uuid4()),
        system="sys",
        messages=[],
    )
    assert result.status == "completed" and result.final_text == "done" and result.steps == 2
    assert [c.ok for c in result.tool_calls] == [True, False]
    # both results returned to the model in ONE user message
    second_request = provider.requests[1][1]
    assert second_request.messages[-1].role == "user" and len(second_request.messages[-1].content) == 2
    assert result.cost_usd == pytest.approx(2 * (100 * 5 + 10 * 25) / 1_000_000)


def test_loop_never_runs_tools_from_a_truncated_turn():
    calls = []
    provider = ScriptedProvider(
        "anthropic",
        [
            resp(
                ToolUseBlock(id="t1", name="echo_asset", input={"asset_id": str(uuid.uuid4())}),
                stop=StopReason.MAX_TOKENS,
            )
        ],
    )
    result = run_agent(
        AGENT,
        router=_router(provider),
        registry=_registry_with_echo(calls),
        ctx=ToolContext(project_id=uuid.uuid4()),
        system="s",
        messages=[],
    )
    assert result.status == "truncated" and calls == []


def test_loop_is_bounded_by_steps_and_budget():
    calls = []
    looping = [
        resp(
            ToolUseBlock(id=f"t{i}", name="echo_asset", input={"asset_id": str(uuid.uuid4())}),
            stop=StopReason.TOOL_USE,
        )
        for i in range(10)
    ]
    result = run_agent(
        AGENT,
        router=_router(ScriptedProvider("anthropic", looping)),
        registry=_registry_with_echo(calls),
        ctx=ToolContext(project_id=uuid.uuid4()),
        system="s",
        messages=[],
    )
    assert result.status == "max_steps" and result.steps == AGENT.max_steps

    cheap = AgentSpec(
        "cheap", "Cheap", "m", ModelRole.FAST, frozenset({"echo_asset"}), phase=0, max_cost_usd=0.0001
    )
    expensive = [
        resp(
            ToolUseBlock(id="t", name="echo_asset", input={"asset_id": str(uuid.uuid4())}),
            stop=StopReason.TOOL_USE,
            out=10_000,
        )
    ]
    result = run_agent(
        cheap,
        router=_router(ScriptedProvider("anthropic", expensive)),
        registry=_registry_with_echo(calls),
        ctx=ToolContext(project_id=uuid.uuid4()),
        system="s",
        messages=[],
    )
    assert result.status == "budget_exceeded"


def test_refusal_stops_the_run():
    result = run_agent(
        AGENT,
        router=_router(ScriptedProvider("anthropic", [resp(stop=StopReason.REFUSAL)])),
        registry=_registry_with_echo([]),
        ctx=ToolContext(project_id=uuid.uuid4()),
        system="s",
        messages=[],
    )
    assert result.status == "refused"
