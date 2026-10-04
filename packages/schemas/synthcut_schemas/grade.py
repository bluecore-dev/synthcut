"""Colour and audio decisions (spec §11, §17, §18): what the Color and Audio
agents decide and what the deterministic engines execute.

``grade/1`` keeps the spec's own field names (``input_transform``,
``exposure``, ``temperature``, ``contrast``, ``saturation``,
``creative_profile``). A grade is baked into one 3D LUT per clip by
``synthcut_color`` — the whole pipeline (input transform → working space →
exposure / white balance → creative grade → Rec.709 output) in one lookup.

``mix/1`` follows the spec's audio chain: dialogue → noise reduction → EQ →
compression → de-esser → loudness → music with ducking → SFX → final mix.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

InputTransform = Literal["none", "apple_log", "slog3", "log_generic"]
CreativeProfile = Literal[
    "neutral", "cinematic_clean", "warm_film", "cool_teal", "vivid_social", "bw_classic"
]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class ColorGrade(_Contract):
    schema_version: Literal["grade/1"] = "grade/1"
    input_transform: InputTransform = "none"
    exposure: float = Field(0.0, ge=-3, le=3, description="Stops, applied in linear light")
    temperature: float = Field(0.0, ge=-50, le=50, description="+ warmer, - cooler")
    tint: float = Field(0.0, ge=-50, le=50, description="+ magenta, - green")
    contrast: float = Field(1.0, ge=0.5, le=1.6, description="Around 18% grey")
    saturation: float = Field(1.0, ge=0.0, le=2.0)
    creative_profile: CreativeProfile = "neutral"
    intensity: float = Field(1.0, ge=0.0, le=1.0, description="How much of the creative profile")
    notes: list[str] = Field(default_factory=list, description="Why each correction was made")


class ColorMeasure(_Contract):
    """Measured on sampled frames after the input transform (so Log footage
    is judged as it will look)."""

    luma_mean: float  # Rec.709-encoded 0..1
    luma_p05: float
    luma_p95: float
    cast_red: float  # mean (R - G) of midtones, + = red/warm cast
    cast_blue: float  # mean (B - G) of midtones, + = blue/cool cast
    saturation: float  # mean chroma, 0..1
    frames: int


class EqBand(_Contract):
    freq: float = Field(ge=20, le=20000)
    gain_db: float = Field(ge=-18, le=18)
    q: float = Field(1.0, ge=0.1, le=10)


class Compressor(_Contract):
    threshold_db: float = Field(-20, ge=-60, le=0)
    ratio: float = Field(3.0, ge=1, le=20)
    attack_ms: float = Field(10, ge=0.1, le=500)
    release_ms: float = Field(200, ge=10, le=3000)
    makeup_db: float = Field(2.0, ge=0, le=24)


class Loudness(_Contract):
    target_lufs: float = Field(-14.0, ge=-31, le=-5)
    true_peak_db: float = Field(-1.0, ge=-9, le=0)
    lra: float = Field(11.0, ge=1, le=50)


class Ducking(_Contract):
    amount_db: float = Field(-12, ge=-40, le=0)
    attack_ms: float = Field(150, ge=1, le=2000)
    release_ms: float = Field(500, ge=10, le=5000)


class MusicCue(_Contract):
    library_id: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_./-]{1,120}$")
    asset_id: UUID | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    gain_db: float = Field(-18, ge=-60, le=6)
    fade_in: float = Field(1.0, ge=0, le=10)
    fade_out: float = Field(2.0, ge=0, le=10)

    @model_validator(mode="after")
    def _one_source(self) -> MusicCue:
        if (self.library_id is None) == (self.asset_id is None):
            raise ValueError("music needs exactly one of library_id or asset_id")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class SfxCue(_Contract):
    library_id: str = Field(pattern=r"^sfx/[a-z0-9_-]{1,40}$")
    at: float = Field(ge=0)
    gain_db: float = Field(-8, ge=-40, le=6)


class VoiceChain(_Contract):
    highpass_hz: float | None = Field(80, ge=20, le=400)
    denoise: Literal["off", "light", "medium", "strong"] = "off"
    eq: list[EqBand] = Field(default_factory=list, max_length=8)
    compressor: Compressor | None = Field(default_factory=Compressor)
    deesser: float = Field(0.0, ge=0, le=1, description="De-esser intensity")


class MixPlan(_Contract):
    schema_version: Literal["mix/1"] = "mix/1"
    voice: VoiceChain = Field(default_factory=VoiceChain)
    loudness: Loudness = Field(default_factory=Loudness)
    music: list[MusicCue] = Field(default_factory=list, max_length=20)
    ducking: Ducking | None = Field(default_factory=Ducking)
    sfx: list[SfxCue] = Field(default_factory=list, max_length=200)
    notes: list[str] = Field(default_factory=list)


class AudioMeasure(_Contract):
    integrated_lufs: float | None
    true_peak_db: float | None
    speech_db: float | None  # median RMS of speech, dBFS
    noise_floor_db: float | None  # median RMS between words, dBFS
    snr_db: float | None
    clipped_ratio: float  # share of samples at full scale
    speech_ratio: float
