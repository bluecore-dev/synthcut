"""The agent loop — written by hand, not delegated to a provider SDK, because
every tool call must pass the permission gate and be recorded, and because the
loop must work with any provider behind the Model Router (spec rule 18).

Termination is always bounded: ``max_steps``, ``max_cost_usd``, a refusal or a
truncated response ends the run (spec rule 8 applies the same idea to QA).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from synthcut_model_router import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelRouter,
    StopReason,
    ToolResultBlock,
    Usage,
)

from .agents import AgentSpec
from .tools import ToolCallRecord, ToolContext, ToolRegistry, invoke_tool

RunStatus = Literal["completed", "max_steps", "budget_exceeded", "refused", "truncated"]


@dataclass
class AgentRunResult:
    agent: str
    status: RunStatus
    final_text: str
    steps: int
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    transcript: list[Message] = field(default_factory=list)


StepHook = Callable[[int, CompletionResponse, list[ToolCallRecord]], None]


def run_agent(
    agent: AgentSpec,
    *,
    router: ModelRouter,
    registry: ToolRegistry,
    ctx: ToolContext,
    system: str,
    messages: list[Message],
    on_step: StepHook | None = None,
) -> AgentRunResult:
    tools = registry.definitions_for(agent)
    history = list(messages)
    result = AgentRunResult(agent=agent.name, status="max_steps", final_text="", steps=0, transcript=history)

    for step in range(1, agent.max_steps + 1):
        response = router.complete(
            agent.model_role,
            CompletionRequest(system=system, messages=history, tools=tools, metadata={"agent": agent.name}),
        )
        result.steps = step
        result.usage = result.usage + response.usage
        result.cost_usd = round(result.cost_usd + response.cost_usd, 6)
        history.append(Message(role="assistant", content=response.content))

        if response.stop_reason is StopReason.REFUSAL:
            result.status = "refused"
            break
        if response.stop_reason is StopReason.MAX_TOKENS:
            # A cut-off turn may hold a half-formed tool call; never run it.
            result.status = "truncated"
            break
        calls = response.tool_uses
        if not calls:
            result.status = "completed"
            result.final_text = response.text
            if on_step:
                on_step(step, response, [])
            break
        if result.cost_usd > agent.max_cost_usd:
            result.status = "budget_exceeded"
            break

        records = [invoke_tool(agent, registry, ctx, c.name, c.input) for c in calls]
        result.tool_calls.extend(records)
        # All results of one turn go back in a single user message.
        history.append(
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id=c.id, content=r.as_result_text(), is_error=not r.ok)
                    for c, r in zip(calls, records, strict=True)
                ],
            )
        )
        if on_step:
            on_step(step, response, records)

    return result
