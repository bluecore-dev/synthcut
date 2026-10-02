"""Editor Agent (spec §16)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="editor",
    title="Editor Agent",
    mission=(
        "Turn the Director's plan into a precise multi-track timeline: frame-accurate cuts, jump cuts, "
        "trims, transitions, speed ramps, silence removal, B-roll placement and sync. Every change must "
        "leave the plan valid."
    ),
    model_role=ModelRole.PLANNING,
    tools=frozenset(
        {
            "get_project_context",
            "get_edit_plan",
            "get_transcript",
            "get_video_analysis",
            "get_shot_list",
            "update_edit_plan",
            "validate_plan",
        }
    ),
    phase=6,
    max_steps=20,
)
