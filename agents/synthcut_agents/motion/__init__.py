"""Motion Graphics Agent (spec §19)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="motion",
    title="Motion Graphics Agent",
    mission=(
        "Add motion graphics that serve the story using only components from the registry; never invent a "
        "new component. Respect safe zones and keep text readable on a phone."
    ),
    model_role=ModelRole.PLANNING,
    tools=frozenset(
        {"get_project_context", "get_edit_plan", "get_transcript", "list_motion_components", "place_graphics"}
    ),
    phase=7,
    max_steps=12,
)
