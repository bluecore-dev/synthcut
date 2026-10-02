"""Video Analysis Agent (spec §12)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="video_analysis",
    title="Video Analysis Agent",
    mission=(
        "Understand every shot: subject, framing, camera motion, focus, exposure, blur, duplicates, bad "
        "takes, silences and what is semantically happening. Score how usable each clip is and store one "
        "analysis record per clip."
    ),
    model_role=ModelRole.VISION,
    tools=frozenset(
        {
            "get_project_context",
            "get_media_metadata",
            "get_shot_list",
            "get_clip_frames",
            "get_transcript",
            "save_clip_analysis",
        }
    ),
    phase=5,
    max_steps=30,
)
