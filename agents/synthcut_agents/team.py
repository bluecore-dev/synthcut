"""The SynthCut specialist team (spec §1, §46 agents/)."""

from __future__ import annotations

from synthcut_agent_sdk import AgentSpec, ToolRegistry, ToolSpec

from . import (
    audio,
    caption,
    color,
    director,
    editor,
    master,
    memory,
    motion,
    qa,
    reflection,
    render,
    research,
    video_analysis,
)
from .catalog import TOOL_CATALOG

TEAM: dict[str, AgentSpec] = {
    module.SPEC.name: module.SPEC
    for module in (
        master,
        video_analysis,
        director,
        editor,
        color,
        audio,
        motion,
        caption,
        research,
        qa,
        reflection,
        memory,
        render,
    )
}


def build_registry() -> ToolRegistry:
    """Declare every catalog tool. Phases attach handlers as they are built."""
    registry = ToolRegistry()
    for name, (scope, phase, description) in TOOL_CATALOG.items():
        registry.declare(ToolSpec(name=name, description=description, scope=scope, phase=phase))
    return registry
