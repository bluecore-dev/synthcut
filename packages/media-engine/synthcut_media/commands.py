"""FFmpeg argument lists. Pure functions: every command is a list (never a
shell string), so file names and URLs can never be interpreted as options or
shell syntax, and each command is unit-testable."""

from __future__ import annotations

import functools
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import ColorInfo, MediaInfo

BASE = ["-hide_banner", "-nostdin", "-nostats", "-y"]
TONEMAP_PROFILES = {"hlg", "pq"}


@functools.cache
def has_filter(name: str, binary: str = "ffmpeg") -> bool:
    try:
        out = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.split()[1:2] == [name] for line in out.stdout.splitlines() if line.strip())


def _floor_even(x: float) -> int:
    return max(2, int(x) // 2 * 2)


def proxy_size(display_width: int, display_height: int, short_side: int = 720) -> tuple[int, int]:
    """Short side ``short_side`` (never upscaled), aspect kept, even dimensions
    (yuv420 needs them) and never larger than the source in either direction."""
    if display_width <= 0 or display_height <= 0:
        raise ValueError("unknown display size")
    if display_width >= display_height:
        h = _floor_even(min(short_side, display_height))
        w = min(max(2, round(h * display_width / display_height / 2) * 2), _floor_even(display_width))
        return w, h
    w = _floor_even(min(short_side, display_width))
    h = min(max(2, round(w * display_height / display_width / 2) * 2), _floor_even(display_height))
    return w, h


@dataclass(frozen=True, slots=True)
class ProxyPlan:
    width: int
    height: int
    tonemap: bool
    color_note: str  # what the proxy shows, for the UI and later agents
    gamut_to_709: bool = False


def plan_proxy(info: MediaInfo, *, short_side: int = 720, zscale: bool | None = None) -> ProxyPlan:
    assert info.video is not None
    w, h = proxy_size(info.video.display_width, info.video.display_height, short_side)
    color: ColorInfo | None = info.color
    zscale = has_filter("zscale") if zscale is None else zscale
    if color and color.profile in TONEMAP_PROFILES:
        if zscale:
            return ProxyPlan(w, h, True, f"{color.label} → SDR Rec.709 (tone-mapped)")
        return ProxyPlan(w, h, False, f"{color.label}, tone-mapping unavailable (zscale missing)")
    if color and color.log:
        return ProxyPlan(
            w, h, False, f"{color.label} — flat Log image, no transform (Phase 8 colour pipeline)"
        )
    if color and color.profile in ("display_p3", "rec2020_sdr") and zscale:
        return ProxyPlan(w, h, False, f"{color.label} → Rec.709 (gamut)", gamut_to_709=True)
    return ProxyPlan(w, h, False, color.label if color else "Rec.709")


def video_filter(plan: ProxyPlan) -> str:
    chain = [f"scale={plan.width}:{plan.height}:flags=bicubic"]
    if plan.tonemap:
        # Scale first: tone-mapping in float RGB at 720p instead of 4K.
        chain += [
            "zscale=t=linear:npl=100",
            "format=gbrpf32le",
            "zscale=p=bt709",
            "tonemap=tonemap=hable:desat=0",
            "zscale=t=bt709:m=bt709:r=tv",
        ]
    elif plan.gamut_to_709:
        # Measured on the VPS (20 s 1080p → 720p proxy): zscale +33% time.
        # colorspace fast=1 skips the primaries entirely (PSNR equal to no
        # conversion); colorspace without it and lut3d (RGB round-trip) are slower.
        chain += ["zscale=p=bt709:t=bt709:m=bt709:r=tv"]
    chain += ["setsar=1", "format=yuv420p"]
    return ",".join(chain)


LOUDNESS_FILTER = "ebur128=peak=true:framelog=quiet"


def video_main_pass(
    source: str,
    *,
    plan: ProxyPlan,
    proxy: Path,
    speech: Path | None,
    threads: int = 2,
    scene_threshold: float = 12.0,
    binary: str = "ffmpeg",
) -> list[str]:
    """One decode of the original feeds the proxy encoder and scene detection
    (a split of the scaled frames), and the audio into the proxy, the Whisper
    track and the loudness meter. Decoding is the expensive part.

    The filmstrip is deliberately *not* part of this graph: an output that gets
    its first frame only at the very end (tile of 12 frames) makes ffmpeg 7.1
    queue every proxy packet meanwhile — a 162 s phone clip grew past 3 GB and
    was OOM-killed. It is made from the proxy's keyframes afterwards."""
    graph = f"[0:v:0]{video_filter(plan)},split=2[proxy][cuts];[cuts]scale=320:-2,scdet=threshold={scene_threshold},nullsink"
    args = [binary, *BASE, "-loglevel", "info", "-progress", "pipe:1", "-threads", str(threads), "-i", source]
    args += [
        "-filter_complex", graph,
        "-map", "[proxy]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-threads", str(threads),
        "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-fpsmax", "60",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
    ]  # fmt: skip
    if speech is not None:
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000"]
    else:
        args += ["-an"]
    args += ["-sn", "-dn", "-movflags", "+faststart", str(proxy)]
    if speech is not None:
        args += speech_outputs(speech)
    return args


def speech_outputs(speech: Path) -> list[str]:
    return [
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(speech),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-af", LOUDNESS_FILTER, "-f", "null", "-",
    ]  # fmt: skip


def audio_main_pass(
    source: str, *, proxy: Path, speech: Path, threads: int = 2, binary: str = "ffmpeg"
) -> list[str]:
    args = [binary, *BASE, "-loglevel", "info", "-progress", "pipe:1", "-threads", str(threads), "-i", source]
    args += ["-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", str(proxy)]
    return args + speech_outputs(speech)


def image_preview(source: str, out: Path, *, longest: int, binary: str = "ffmpeg") -> list[str]:
    scale = f"scale='if(gte(iw,ih),min({longest},iw),-2)':'if(gte(iw,ih),-2,min({longest},ih))'"
    return [
        binary,
        *BASE,
        "-loglevel",
        "error",
        "-i",
        source,
        "-frames:v",
        "1",
        "-vf",
        scale,
        "-q:v",
        "3",
        str(out),
    ]


def poster(proxy: Path, out: Path, *, at: float, longest: int = 640, binary: str = "ffmpeg") -> list[str]:
    scale = f"scale='if(gte(iw,ih),{longest},-2)':'if(gte(iw,ih),-2,{longest})'"
    return [
        binary, *BASE, "-loglevel", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(proxy),
        "-frames:v", "1", "-vf", scale, "-q:v", "3", str(out),
    ]  # fmt: skip


KEYFRAME_INTERVAL = 2.0  # the proxy encoder forces a keyframe every 2 s


@dataclass(frozen=True, slots=True)
class SpritePlan:
    step: int  # use every step-th keyframe
    tiles: int
    interval: float  # seconds between tiles


def plan_sprite(duration: float, *, max_tiles: int = 12) -> SpritePlan:
    keyframes = max(1, math.ceil(duration / KEYFRAME_INTERVAL))
    step = math.ceil(keyframes / max_tiles)
    tiles = math.ceil(keyframes / step)
    return SpritePlan(step=step, tiles=tiles, interval=step * KEYFRAME_INTERVAL)


def sprite(
    proxy: Path, out: Path, *, plan: SpritePlan, tile_height: int = 120, binary: str = "ffmpeg"
) -> list[str]:
    """Filmstrip from the proxy's keyframes only: a handful of frames are
    decoded instead of the whole proxy, and every tile is a real frame (an fps
    filter would need a following frame and yields nothing for 1-keyframe clips)."""
    select = f"select='not(mod(n,{plan.step}))',scale=-2:{tile_height},tile={plan.tiles}x1"
    return [
        binary, *BASE, "-loglevel", "error", "-skip_frame", "nokey", "-i", str(proxy), "-an",
        "-vf", select, "-frames:v", "1", "-q:v", "4", str(out),
    ]  # fmt: skip


def scene_detect(proxy: Path, *, threshold: float = 12.0, binary: str = "ffmpeg") -> list[str]:
    return [
        binary, *BASE, "-loglevel", "info", "-i", str(proxy), "-an",
        "-vf", f"scale=320:-2,scdet=threshold={threshold}", "-f", "null", "-",
    ]  # fmt: skip


def composite_overlay(
    background: str | Path, overlay: Path, out: Path, *, threads: int = 2, crf: int = 21
) -> list[str]:
    """The motion layer (transparent ProRes 4444 from Remotion) over the
    picture (spec rule 19: Remotion draws, FFmpeg composites). Frames are
    matched by timestamp, so a 30 fps layer sits correctly on 29.97 fps footage."""
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-threads", str(threads),
        "-i", str(background),
        "-i", str(overlay),
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:eof_action=pass,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", str(out),
    ]  # fmt: skip
