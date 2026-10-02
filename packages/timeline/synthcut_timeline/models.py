"""EditPlan v1 — the typed, versioned timeline (spec §22-23).

The plan is what agents *decide*; media engines only ever *execute* a plan
that passed :func:`synthcut_timeline.validate.validate_plan` (spec rule 6).

Times are seconds (floats, as the spec's examples use) and are validated
against the sequence frame rate — every boundary must land within half a
frame of a frame edge, and :func:`snap_to_frames` can normalise a plan.
Clips reference sources by asset id only; a plan can never name a file path.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from synthcut_schemas.enums import ALLOWED_FPS

SCHEMA_VERSION = "editplan/1"

ItemId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
Seconds = Annotated[float, Field(ge=0, le=4 * 3600)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Crop(_Strict):
    left: float = Field(0, ge=0, le=0.5)
    right: float = Field(0, ge=0, le=0.5)
    top: float = Field(0, ge=0, le=0.5)
    bottom: float = Field(0, ge=0, le=0.5)


class Transform(_Strict):
    """Placement inside the frame. ``x``/``y`` are offsets in frame-size units
    (-1..1), so a plan stays valid when the output resolution changes."""

    scale: float = Field(1.0, ge=0.1, le=10)
    x: float = Field(0.0, ge=-1, le=1)
    y: float = Field(0.0, ge=-1, le=1)
    rotation: float = Field(0.0, ge=-180, le=180)
    opacity: float = Field(1.0, ge=0, le=1)
    crop: Crop | None = None


Easing = Literal["linear", "ease_in", "ease_out", "ease_in_out", "hold"]


class Keyframe(_Strict):
    t: Seconds = Field(description="Seconds from the start of the item")
    property: Literal["scale", "x", "y", "rotation", "opacity", "volume_db"]
    value: float
    easing: Easing = "ease_in_out"


class EffectRef(_Strict):
    type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    params: dict[str, Any] = Field(default_factory=dict)


class Transition(_Strict):
    type: Literal["cut", "crossfade", "dip_to_black", "dip_to_white", "whip", "zoom"] = "cut"
    duration: float = Field(0.0, ge=0, le=3)


class _TimedItem(_Strict):
    id: ItemId
    timeline_start: Seconds
    timeline_end: Seconds

    @property
    def timeline_duration(self) -> float:
        return self.timeline_end - self.timeline_start


class _SourcedItem(_TimedItem):
    source_in: Seconds
    source_out: Seconds
    speed: float = Field(1.0, ge=0.1, le=8, description="Source seconds consumed per timeline second")

    @model_validator(mode="after")
    def _ranges(self) -> _SourcedItem:
        if self.source_out <= self.source_in:
            raise ValueError("source_out must be greater than source_in")
        if self.timeline_end <= self.timeline_start:
            raise ValueError("timeline_end must be greater than timeline_start")
        return self


class VideoClip(_SourcedItem):
    asset_id: UUID
    transform: Transform = Field(default_factory=Transform)
    effects: list[EffectRef] = Field(default_factory=list, max_length=16)
    keyframes: list[Keyframe] = Field(default_factory=list, max_length=200)
    transition_in: Transition | None = None
    mute_source_audio: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class VideoTrack(_Strict):
    track: int = Field(ge=1, le=16)
    role: Literal["main", "broll", "overlay"] = "main"
    clips: list[VideoClip] = Field(default_factory=list, max_length=2000)


class AudioSource(_Strict):
    asset_id: UUID | None = None
    library_id: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_./-]{1,120}$")

    @model_validator(mode="after")
    def _exactly_one(self) -> AudioSource:
        if (self.asset_id is None) == (self.library_id is None):
            raise ValueError("audio source needs exactly one of asset_id or library_id")
        return self


class AudioClip(_SourcedItem):
    source: AudioSource
    gain_db: float = Field(0.0, ge=-60, le=12)
    fade_in: float = Field(0.0, ge=0, le=10)
    fade_out: float = Field(0.0, ge=0, le=10)
    keyframes: list[Keyframe] = Field(default_factory=list, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Ducking(_Strict):
    under: Literal["voice"] = "voice"
    amount_db: float = Field(-12.0, ge=-30, le=0)
    attack: float = Field(0.15, ge=0, le=2)
    release: float = Field(0.4, ge=0, le=4)


class AudioTrack(_Strict):
    track: int = Field(ge=1, le=16)
    role: Literal["voice", "music", "sfx", "ambience"]
    clips: list[AudioClip] = Field(default_factory=list, max_length=2000)
    ducking: Ducking | None = None


class GraphicsItem(_TimedItem):
    component: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{1,40}$")
    layer: int = Field(1, ge=1, le=16)
    props: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _range(self) -> GraphicsItem:
        if self.timeline_end <= self.timeline_start:
            raise ValueError("timeline_end must be greater than timeline_start")
        return self


class CaptionTrack(_Strict):
    enabled: bool = True
    style: Literal["dynamic", "karaoke", "minimal", "bold"] = "dynamic"
    language: str | None = Field(None, pattern=r"^[a-z]{2}$")
    max_words_per_line: int = Field(4, ge=1, le=10)
    position: Literal["bottom", "center", "top"] = "bottom"
    respect_safe_zone: bool = True


class Sequence(_Strict):
    fps: int
    width: int = Field(ge=144, le=7680)
    height: int = Field(ge=144, le=7680)
    duration: float = Field(gt=0, le=4 * 3600)

    @field_validator("fps")
    @classmethod
    def _fps(cls, v: int) -> int:
        if v not in ALLOWED_FPS:
            raise ValueError(f"fps must be one of {ALLOWED_FPS}")
        return v

    @field_validator("width", "height")
    @classmethod
    def _even(cls, v: int) -> int:
        if v % 2:
            raise ValueError("dimensions must be even (yuv420 encoding)")
        return v

    @property
    def frame(self) -> float:
        return 1.0 / self.fps


class EditPlan(_Strict):
    schema_version: Literal["editplan/1"] = SCHEMA_VERSION
    project_id: UUID
    version: int = Field(ge=1)
    sequence: Sequence
    video_tracks: list[VideoTrack] = Field(min_length=1, max_length=16)
    audio_tracks: list[AudioTrack] = Field(default_factory=list, max_length=16)
    graphics: list[GraphicsItem] = Field(default_factory=list, max_length=500)
    captions: CaptionTrack | None = None
    global_effects: list[EffectRef] = Field(default_factory=list, max_length=16)
    notes: str | None = Field(None, max_length=4000, description="Director's rationale, shown to the user")
    metadata: dict[str, Any] = Field(default_factory=dict)
