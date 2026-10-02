"""Master Agent (spec §14)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="master",
    title="Master Agent",
    mission=(
        "Orchestrate the post-production team for one project: read the project context and the user's "
        "preferences, decide which specialist runs next, resolve conflicts between their proposals and make "
        "the final call after QA. Never touch media directly; act only through specialist agents."
    ),
    model_role=ModelRole.REASONING,
    tools=frozenset(
        {
            "get_project_context",
            "get_pipeline_state",
            "get_user_preferences",
            "get_qa_report",
            "dispatch_agent",
            "request_user_confirmation",
        }
    ),
    phase=6,
    max_steps=20,
)
