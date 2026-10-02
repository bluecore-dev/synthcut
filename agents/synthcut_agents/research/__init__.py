"""Research Agent (spec §27)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="research",
    title="Research Agent",
    mission=(
        "Find editing, cinematography, color, audio, motion and platform knowledge. Search, extract, verify "
        "and store with sources. Research informs other agents; it is never a production decision by itself."
    ),
    model_role=ModelRole.PLANNING,
    tools=frozenset({"search_knowledge", "web_search", "save_research_note"}),
    phase=10,
    max_steps=10,
)
