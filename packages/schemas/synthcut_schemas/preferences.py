"""Remembered choices (spec §26 Memory, Phase 10): what a user's next Tez
montaj starts from, and the quick corrections they can give a finished video.

Each feedback code is a fixed, explainable rule on one or two preferences —
the Memory agent will later add judgement on free text, writing to the same
preferences.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Captions = Literal["off", "dynamic", "karaoke", "minimal", "bold"]
Profile = Literal["neutral", "cinematic_clean", "warm_film", "cool_teal", "vivid_social", "bw_classic"]
Loudness = Literal["social", "youtube", "podcast", "broadcast"]
Denoise = Literal["auto", "off", "light", "medium", "strong"]


class EditDefaults(BaseModel):
    """The part of a Tez montaj request that carries over to the next one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    remove_pauses: bool = True
    min_pause: float = Field(0.6, ge=0.3, le=2.0, description="Pauses longer than this are cut (seconds)")
    captions: Captions = "dynamic"
    caption_position: Literal["bottom", "center", "top"] = "bottom"
    profile: Profile = "cinematic_clean"
    intensity: float = Field(0.8, ge=0, le=1)
    loudness: Loudness = "social"
    denoise: Denoise = "auto"
    deliver: bool = True


EDIT_KEYS: tuple[str, ...] = tuple(EditDefaults.model_fields)

FeedbackCode = Literal[
    "cut_too_much",
    "cut_too_little",
    "no_captions",
    "want_captions",
    "colour_too_strong",
    "colour_too_weak",
    "voice_robotic",
    "noise_left",
    "too_quiet",
    "too_loud",
]

PreferenceSource = Literal["choice", "feedback", "agent"]
