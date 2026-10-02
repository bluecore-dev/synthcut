"""Reflection Agent (spec §25)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="reflection",
    title="Reflection Agent",
    mission=(
        "When QA fails and no deterministic fix exists, diagnose the cause and propose the smallest patch "
        "that fixes it. The patch is validated before any re-render; after three automatic attempts the "
        "user decides."
    ),
    model_role=ModelRole.REASONING,
    tools=frozenset({"get_qa_report", "get_edit_plan", "validate_plan", "propose_patch"}),
    phase=9,
    max_steps=8,
)
