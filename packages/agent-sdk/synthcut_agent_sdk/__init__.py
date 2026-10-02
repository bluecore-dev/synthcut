"""Agent and typed-tool interfaces for the SynthCut team (spec §14-28)."""

from .agents import AgentSpec
from .loop import AgentRunResult, run_agent
from .tools import (
    FORBIDDEN_FIELD_NAMES,
    ToolCallRecord,
    ToolContext,
    ToolRegistry,
    ToolScope,
    ToolSpec,
    UnsafeToolError,
    assert_safe_input_model,
    invoke_tool,
)

__all__ = [
    "FORBIDDEN_FIELD_NAMES",
    "AgentRunResult",
    "AgentSpec",
    "ToolCallRecord",
    "ToolContext",
    "ToolRegistry",
    "ToolScope",
    "ToolSpec",
    "UnsafeToolError",
    "assert_safe_input_model",
    "invoke_tool",
    "run_agent",
]
