"""Deterministic media engine (spec §21): FFprobe normalisation, colour
detection, FFmpeg command plans and a cancellable runner. Agents never call it
directly — workers run it for jobs (rule 20)."""

from .color import classify_color
from .commands import (
    ProxyPlan,
    SpritePlan,
    audio_main_pass,
    has_filter,
    image_preview,
    plan_proxy,
    plan_sprite,
    poster,
    proxy_size,
    scene_detect,
    sprite,
    video_filter,
    video_main_pass,
)
from .errors import MediaError
from .models import AudioStream, ColorInfo, Loudness, MediaInfo, VideoStream
from .parse import parse_loudness, parse_progress_seconds, parse_scene_cuts, shots_from_cuts
from .probe import normalize, run_ffprobe
from .runner import run_ffmpeg

__all__ = [
    "AudioStream",
    "ColorInfo",
    "Loudness",
    "MediaError",
    "MediaInfo",
    "ProxyPlan",
    "SpritePlan",
    "VideoStream",
    "audio_main_pass",
    "classify_color",
    "has_filter",
    "image_preview",
    "normalize",
    "parse_loudness",
    "parse_progress_seconds",
    "parse_scene_cuts",
    "plan_proxy",
    "plan_sprite",
    "poster",
    "proxy_size",
    "run_ffmpeg",
    "run_ffprobe",
    "scene_detect",
    "shots_from_cuts",
    "sprite",
    "video_filter",
    "video_main_pass",
]
