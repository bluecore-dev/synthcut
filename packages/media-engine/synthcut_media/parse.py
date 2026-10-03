"""Parsers for FFmpeg's log output (scene cuts, loudness)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from itertools import pairwise

from .models import Loudness

_SCD = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)")
_LUFS_I = re.compile(r"^\s*I:\s*(-?[0-9.]+|-inf)\s*LUFS", re.M)
_LRA = re.compile(r"^\s*LRA:\s*([0-9.]+)\s*LU", re.M)
_PEAK = re.compile(r"^\s*Peak:\s*(-?[0-9.]+|-inf)\s*dBFS", re.M)


def parse_scene_cuts(lines: Iterable[str]) -> list[tuple[float, float]]:
    """(time, score) for every scene change scdet reported."""
    cuts = []
    for line in lines:
        m = _SCD.search(line)
        if m:
            cuts.append((float(m.group(2)), float(m.group(1))))
    return sorted(cuts)


def shots_from_cuts(
    cuts: list[tuple[float, float]], duration: float, *, min_shot: float = 0.4
) -> list[dict[str, float]]:
    """Contiguous shots covering [0, duration]; cuts closer than ``min_shot``
    to the previous boundary (flashes, flicker) are ignored."""
    bounds = [0.0]
    for t, _ in cuts:
        if min_shot <= t <= duration - min_shot and t - bounds[-1] >= min_shot:
            bounds.append(round(t, 3))
    bounds.append(round(duration, 3))
    return [
        {"index": i, "start": a, "end": b, "duration": round(b - a, 3)}
        for i, (a, b) in enumerate(pairwise(bounds))
        if b > a
    ]


def _num(m: re.Match[str] | None) -> float | None:
    if not m:
        return None
    value = m.group(1)
    return None if value == "-inf" else float(value)


def parse_loudness(text: str) -> Loudness | None:
    idx = text.rfind("Summary:")
    if idx < 0:
        return None
    summary = text[idx:]
    result = Loudness(
        integrated_lufs=_num(_LUFS_I.search(summary)),
        lra_lu=_num(_LRA.search(summary)),
        true_peak_dbfs=_num(_PEAK.search(summary)),
    )
    if result.integrated_lufs is None and result.true_peak_dbfs is None:
        return None
    return result


def parse_progress_seconds(line: str) -> float | None:
    """``out_time_us=…`` from ``-progress`` output, in seconds."""
    key, _, value = line.strip().partition("=")
    if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit():
        return max(0.0, int(value) / 1_000_000)
    return None
