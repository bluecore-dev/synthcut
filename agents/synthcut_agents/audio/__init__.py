"""Audio Agent (spec §18)."""

from synthcut_agent_sdk import AgentSpec
from synthcut_model_router import ModelRole

SPEC = AgentSpec(
    name="audio",
    title="Audio Agent",
    mission=(
        "Make dialogue clean and dominant: noise reduction, EQ, compression, de-essing and loudness "
        "normalization, then music with automatic ducking under the voice, SFX and the final mix."
    ),
    model_role=ModelRole.PLANNING,
    tools=frozenset(
        {"get_media_metadata", "get_transcript", "get_edit_plan", "analyze_audio", "generate_mix_plan"}
    ),
    phase=8,
    max_steps=12,
)
