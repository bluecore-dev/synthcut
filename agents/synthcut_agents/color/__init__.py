"""Color Agent (spec §17)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="color",
    title="Color Agent",
    mission=(
        "Manage color from source to output: identify the input transform (Rec.709, Apple Log, S-Log...), "
        "correct exposure and white balance, match shots, protect skin tones, then apply the creative grade "
        "and output transform. Original Log media is never altered."
    ),
    model_role=ModelRole.PLANNING,
    tools=frozenset({"get_media_metadata", "get_edit_plan", "analyze_color", "generate_grade"}),
    phase=8,
    max_steps=12,
)
