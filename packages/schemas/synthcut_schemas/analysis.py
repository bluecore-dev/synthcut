"""Per-clip analysis contract (spec §12), stored in ``clip_analyses`` and as
``analysis/<asset>/clips.json``.

A *clip* is one shot of an asset (Phase 3's shot list). The measured fields
come from deterministic analysis of the proxy and the speech track; the
semantic ones (``subject``, ``semantic_description``, objects) are filled by
the Video Analysis agent when a vision model is configured. ``source`` says
which of the two produced the record, so the Director knows how far to trust it.

Times are seconds on the source clip's timeline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShotType = Literal["close_up", "medium", "wide", "unknown"]
CameraMotion = Literal["static", "pan_left", "pan_right", "tilt_up", "tilt_down", "handheld", "moving"]
PersonPosition = Literal["left", "center", "right"]
ClipFlag = Literal[
    "black",
    "blurry",
    "underexposed",
    "overexposed",
    "shaky",
    "frozen",
    "too_short",
    "duplicate",
]


class _Analysis(BaseModel):
    # Responses always carry every field (generated TS types mark them present).
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Span(_Analysis):
    start: float
    end: float


class Exposure(_Analysis):
    mean: float  # luma 0..1 (video range normalised)
    dark: float  # share of crushed pixels
    bright: float  # share of clipped pixels


class Motion(_Analysis):
    speed: float  # median camera movement, frame widths per second
    shake: float  # frame-to-frame jitter, frame widths per second
    dx: float  # net horizontal travel over the clip, frame widths (+ = camera pans right)
    dy: float  # net vertical travel, frame heights (+ = camera tilts down)


class Face(_Analysis):
    x: float  # centre, 0..1 of the frame
    y: float
    height: float  # face box height / frame height
    score: float


class ClipAnalysis(_Analysis):
    schema_version: Literal["clipanalysis/1"] = "clipanalysis/1"
    clip_id: str  # "<asset id prefix>-s<index>", stable across re-runs
    index: int
    start: float
    end: float
    duration: float
    resolution: str | None = None
    fps: float | None = None
    color_profile: str | None = None

    shot_type: ShotType = "unknown"
    subject: str | None = None
    face_detected: bool = False
    face_count: int = 0
    faces: list[Face] = Field(default_factory=list)
    person_position: PersonPosition | None = None
    camera_motion: CameraMotion = "static"

    sharpness: float  # 0..1
    exposure: Exposure
    motion: Motion
    camera_quality: float  # 0..1
    lighting_quality: float  # 0..1

    audio_present: bool = False
    speech_present: bool = False
    speech_ratio: float = 0.0
    silence_segments: list[Span] = Field(default_factory=list)

    semantic_description: str | None = None
    usable_score: float  # 0..1
    flags: list[ClipFlag] = Field(default_factory=list)
    duplicate_of: str | None = None
    best_frame: float | None = None  # sharpest sampled moment near the middle (source time)
    source: Literal["metrics", "metrics+vision"] = "metrics"
