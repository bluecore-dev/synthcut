"""Memory Agent (spec §26)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="memory",
    title="Memory Agent",
    mission=(
        "Turn user corrections into structured, reusable preferences (for example: fewer transitions, "
        "warmer skin tones) so the next project starts from them."
    ),
    model_role=ModelRole.FAST,
    tools=frozenset({"get_user_preferences", "record_feedback", "update_preference"}),
    phase=10,
    max_steps=6,
)
