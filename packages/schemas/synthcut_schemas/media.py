"""Normalized media description (stored as ``assets.media_info``).

FFprobe output differs between versions and containers; everything downstream
(the UI, the Director, the Color agent) reads this stable, versioned shape
instead of raw ffprobe JSON. Produced by ``synthcut_media.normalize``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MediaKind = Literal["video", "audio", "image", "other"]
ColorProfileId = Literal[
    "rec709",
    "rec2020_sdr",
    "display_p3",
    "hlg",
    "pq",
    "apple_log",
    "log_suspected",
    "srgb",
    "unknown",
]


class ColorInfo(BaseModel):
    """Source color detection (spec §11 SOURCE DETECTION). Phase 8 builds the
    full transform chain on top of this; ingestion only needs to know enough
    to make a viewable proxy and to flag Log/HDR material."""

    profile: ColorProfileId
    label: str
    confidence: Literal["high", "medium", "low"]
    hdr: bool = False
    log: bool = False
    dolby_vision: bool = False
    reasons: list[str] = Field(default_factory=list)


class VideoStream(BaseModel):
    codec: str | None = None
    profile: str | None = None
    width: int
    height: int
    display_width: int
    display_height: int
    rotation: int = 0
    fps: float | None = None
    vfr: bool = False
    pix_fmt: str | None = None
    bit_depth: int | None = None
    chroma: str | None = None
    bitrate: int | None = None
    frames: int | None = None
    color_range: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_space: str | None = None

    @property
    def orientation(self) -> Literal["landscape", "portrait", "square"]:
        if self.display_width == self.display_height:
            return "square"
        return "landscape" if self.display_width > self.display_height else "portrait"


class AudioStream(BaseModel):
    codec: str | None = None
    profile: str | None = None
    channels: int | None = None
    channel_layout: str | None = None
    sample_rate: int | None = None
    bitrate: int | None = None
    bit_depth: int | None = None


class Loudness(BaseModel):
    integrated_lufs: float | None = None
    lra_lu: float | None = None
    true_peak_dbfs: float | None = None


class MediaInfo(BaseModel):
    schema_version: Literal["mediainfo/1"] = "mediainfo/1"
    kind: MediaKind
    container: str | None = None
    duration: float | None = None
    size_bytes: int
    bitrate: int | None = None
    video: VideoStream | None = None
    audio: AudioStream | None = None
    audio_streams: int = 0
    color: ColorInfo | None = None
    camera: dict[str, str] = Field(default_factory=dict)
    # GPS coordinates are deliberately not kept, only whether the file has them.
    has_location: bool = False
    loudness: Loudness | None = None
