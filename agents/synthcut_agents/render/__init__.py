"""Render Agent (spec §28)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="render",
    title="Render Agent",
    mission=(
        "Sequence deterministic renders of a validated plan: motion layers first, then the FFmpeg "
        "composite. It never changes the plan; a plan that does not validate is not rendered."
    ),
    model_role=ModelRole.FAST,
    tools=frozenset({"validate_plan", "render_remotion", "render_ffmpeg", "get_render_logs"}),
    phase=11,
    max_steps=6,
)
