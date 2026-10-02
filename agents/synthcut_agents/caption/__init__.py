"""Caption Agent (spec §4, §50)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="caption",
    title="Caption Agent",
    mission=(
        "Build captions from the word-level transcript: line breaks at natural phrase boundaries, emphasis "
        "on key words, timing that follows the edit, placement inside the platform safe zone."
    ),
    model_role=ModelRole.FAST,
    tools=frozenset({"get_transcript", "get_edit_plan", "generate_captions"}),
    phase=7,
    max_steps=8,
)
