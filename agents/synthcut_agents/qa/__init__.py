"""QA / Critic Agent (spec §24)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="qa",
    title="QA / Critic Agent",
    mission=(
        "Check plans before render and renders after: timeline validity, missing assets, overlaps, text "
        "overflow, safe zones, audio clipping, subtitle timing, frame drops, black frames, aspect ratio, "
        "fps, color errors and the export specification. Report every finding precisely."
    ),
    model_role=ModelRole.REASONING,
    tools=frozenset({"get_edit_plan", "validate_plan", "inspect_render", "get_render_logs", "report_issues"}),
    phase=9,
    max_steps=12,
)
