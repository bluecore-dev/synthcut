"""Director Agent (spec §15)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="director",
    title="Director Agent",
    mission=(
        "Decide how the video tells its story: the hook, narrative, pacing, shot selection, cut points, "
        "B-roll moments, emotional rhythm and call to action, within the target platform and duration. "
        "Express the decision as an EditPlan."
    ),
    model_role=ModelRole.REASONING,
    tools=frozenset(
        {
            "get_project_context",
            "get_transcript",
            "get_video_analysis",
            "get_user_preferences",
            "search_knowledge",
            "create_edit_plan",
        }
    ),
    phase=6,
    max_steps=15,
)
