"""Frames out of the 720p proxy (never the original): a small grayscale stream
for measurements and a few colour stills per shot for faces and the sheets
the vision agent looks at."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from synthcut_media import run_ffmpeg

GRAY_WIDTH = 320
STILL_WIDTH = 640


def gray_size(width: int, height: int, target: int = GRAY_WIDTH) -> tuple[int, int]:
    """Even dimensions at ``target`` width, aspect kept (portrait stays portrait)."""
    if width <= 0 or height <= 0:
        raise ValueError("frame size must be positive")
    h = max(2, round(target * height / width / 2) * 2)
    return target, h


def sample_rate(duration: float) -> float:
    """Measurement frames per second: dense for short clips, bounded for long ones."""
    if duration <= 600:
        return 4.0
    if duration <= 3600:
        return 2.0
    return 1.0


def sample_gray(
    proxy: Path,
    work: Path,
    *,
    width: int,
    height: int,
    fps: float,
    duration: float,
    check: Callable[[], None] | None = None,
) -> np.ndarray:
    """``(n, h, w)`` uint8 luma at ``fps``, memory-mapped from scratch so an
    hour of footage never sits in RAM. Frame ``i`` is at ``i / fps`` seconds."""
    w, h = gray_size(width, height)
    raw = work / "frames.gray"
    run_ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(proxy), "-an", "-sn",
         "-vf", f"fps={fps},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", str(raw)],
        check=check,
        timeout=600 + duration * 2,
    )  # fmt: skip
    n = raw.stat().st_size // (w * h)
    if n == 0:
        return np.zeros((0, h, w), dtype=np.uint8)
    return np.memmap(raw, dtype=np.uint8, mode="r", shape=(n, h, w))


def still(proxy: Path, at: float, out: Path, *, check: Callable[[], None] | None = None) -> Path:
    """One colour frame (fast seek: the proxy has a keyframe every 2 s)."""
    run_ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{max(0.0, at):.3f}", "-i", str(proxy),
         "-frames:v", "1", "-an", "-vf", f"scale={STILL_WIDTH}:-2", "-q:v", "3", str(out)],
        check=check,
        timeout=60,
    )  # fmt: skip
    return out
