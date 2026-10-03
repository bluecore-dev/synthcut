"""Speech audio in and silence detection — through our ffmpeg runner (nice,
cancellable), never through an engine's own decoder."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
from synthcut_media import run_ffmpeg
from synthcut_schemas.speech import Silence

SAMPLE_RATE = 16000

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def load_pcm(source: Path, work: Path, *, check: Callable[[], None] | None = None) -> np.ndarray:
    """16 kHz mono float32 in [-1, 1] — what Whisper engines take. Goes via a
    raw file so a 2 h track never sits in a pipe buffer."""
    raw = work / "speech.f32"
    run_ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", str(raw)],
        check=check,
        timeout=1800,
    )  # fmt: skip
    try:
        return np.fromfile(raw, dtype=np.float32)
    finally:
        raw.unlink(missing_ok=True)


def silence_threshold_db(integrated_lufs: float | None) -> float:
    """Sample-peak threshold for ``silencedetect``: ~22 dB under the programme
    loudness (a quiet phone recording is not all "silence"), kept in a sane band."""
    if integrated_lufs is None:
        return -40.0
    return round(max(-55.0, min(-30.0, integrated_lufs - 22.0)), 1)


def silence_args(source: Path, *, noise_db: float, min_duration: float = 0.5) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-i", str(source), "-vn",
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-",
    ]  # fmt: skip


def parse_silences(log: str, duration: float) -> list[Silence]:
    """``silence_start`` / ``silence_end`` pairs; a track that ends silent has
    no closing line, so the last span runs to the end."""
    out: list[Silence] = []
    start: float | None = None
    for line in log.splitlines():
        if (m := _START.search(line)) is not None:
            start = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) is not None and start is not None:
            end = min(duration, float(m.group(1)))
            if end > start:
                out.append(Silence(start=round(start, 3), end=round(end, 3)))
            start = None
    if start is not None and duration - start > 0:
        out.append(Silence(start=round(start, 3), end=round(duration, 3)))
    return out


def detect_silences(
    source: Path,
    duration: float,
    *,
    integrated_lufs: float | None,
    check: Callable[[], None] | None = None,
) -> list[Silence]:
    log = run_ffmpeg(
        silence_args(source, noise_db=silence_threshold_db(integrated_lufs)), check=check, timeout=1800
    )
    return parse_silences(log, duration)
