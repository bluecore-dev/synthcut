"""Measured colour → an automatic grade (spec §11 "EXPOSURE / WB",
"SHOT MATCHING"). The Color agent (Phase 6+) starts from these numbers and
may override them; without a model this is the whole decision.

Measurements are taken *after* the input transform, so Log footage is judged
as it will look, not as its flat encoding. Corrections are damped and
clamped — an automatic grade should fix what is clearly off and leave intent
(a dark night scene, a warm sunset) mostly alone.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from pathlib import Path

import numpy as np
from synthcut_media import run_ffmpeg
from synthcut_schemas.grade import ColorGrade, ColorMeasure

from .grade import apply_grade
from .spaces import luma

TARGET_LUMA = 0.45  # display-encoded mean a well-exposed shot sits near


def input_transform_for(color_profile: str | None, *, from_proxy: bool) -> str:
    """The proxy is already Rec.709 for HDR / wide-gamut sources (tone-mapped
    at ingest); only Log stays flat there. From the original, HDR goes
    through zscale at render time (Phase 11), so the grade sees Rec.709."""
    if color_profile == "apple_log":
        return "apple_log"
    if color_profile == "log_suspected":
        return "log_generic"
    return "none"


def sample_rgb(
    source: str | Path,
    work: Path,
    *,
    duration: float,
    width: int = 256,
    height: int = 144,
    max_frames: int = 48,
    check: Callable[[], None] | None = None,
) -> np.ndarray:
    """Up to ``max_frames`` RGB frames spread over the clip, small (colour
    statistics need no resolution). Returns (n, h, w, 3) floats 0..1."""
    rate = max(0.05, min(2.0, max_frames / max(duration, 0.1)))
    raw = work / "colour.rgb"
    run_ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source), "-an", "-sn",
         "-vf", f"fps={rate:.4f},scale={width}:{height}:flags=area,format=rgb24",
         "-frames:v", str(max_frames), "-f", "rawvideo", str(raw)],
        check=check,
        timeout=300 + duration,
    )  # fmt: skip
    data = np.fromfile(raw, dtype=np.uint8)
    raw.unlink(missing_ok=True)
    n = data.size // (width * height * 3)
    return data[: n * width * height * 3].reshape(n, height, width, 3).astype(np.float64) / 255.0


def measure(frames: np.ndarray, transform: str = "none") -> ColorMeasure:
    if len(frames) == 0:
        return ColorMeasure(
            luma_mean=0, luma_p05=0, luma_p95=0, cast_red=0, cast_blue=0, saturation=0, frames=0
        )
    shaped = apply_grade(frames.reshape(-1, 3), ColorGrade(input_transform=transform))
    y = luma(shaped)
    chroma = shaped.max(axis=1) - shaped.min(axis=1)
    # A cast shows on surfaces that should be neutral (a white shirt, a grey
    # wall). Averaging every midtone ("grey world") would also "correct" a
    # genuinely orange brick wall, so near-neutral pixels decide when there
    # are enough of them; otherwise all midtones, at half weight.
    mid = (y > 0.2) & (y < 0.9)
    neutral = mid & (chroma < 0.12)
    if neutral.sum() >= max(100, 0.02 * len(y)):
        sample, weight = shaped[neutral], 1.0
    elif mid.sum() > 100:
        sample, weight = shaped[mid], 0.5
    else:
        sample, weight = shaped, 0.5
    return ColorMeasure(
        luma_mean=round(float(y.mean()), 4),
        luma_p05=round(float(np.percentile(y, 5)), 4),
        luma_p95=round(float(np.percentile(y, 95)), 4),
        cast_red=round(float((sample[:, 0] - sample[:, 1]).mean()) * weight, 4),
        cast_blue=round(float((sample[:, 2] - sample[:, 1]).mean()) * weight, 4),
        saturation=round(float(chroma.mean()), 4),
        frames=len(frames),
    )


def auto_grade(
    m: ColorMeasure,
    *,
    transform: str = "none",
    profile: str = "neutral",
    intensity: float = 0.8,
    target_luma: float = TARGET_LUMA,
) -> ColorGrade:
    notes: list[str] = []
    if transform != "none":
        label = {
            "apple_log": "Apple Log → Rec.709",
            "slog3": "S-Log3 → Rec.709",
            "log_generic": "Log (taxminiy) → Rec.709",
        }[transform]
        notes.append(f"Kirish transformatsiyasi: {label}")

    exposure = 0.0
    if m.luma_mean > 0.04:  # black frames say nothing about exposure
        stops = math.log2((target_luma / m.luma_mean) ** 2.4) * 0.7
        exposure = round(max(-1.5, min(1.5, stops)), 2)
        if abs(exposure) < 0.1:
            exposure = 0.0
        else:
            word = "qorong'i" if exposure > 0 else "juda yorug'"
            notes.append(
                f"Ekspozitsiya {exposure:+.2f} EV: kadr {word} (o'rtacha yorqinlik {m.luma_mean:.2f})"
            )

    temperature = round(max(-25.0, min(25.0, (m.cast_blue - m.cast_red) * 150)), 1)
    if abs(temperature) < 2:
        temperature = 0.0
    else:
        notes.append(
            f"Oq balans: {'iliqroq' if temperature > 0 else 'sovuqroq'} ({temperature:+.0f}) — {'ko‘k' if temperature > 0 else 'sariq/qizil'} og‘ish bor edi"
        )
    tint = round(max(-20.0, min(20.0, -(m.cast_red + m.cast_blue) / 2 * 300)), 1)
    if abs(tint) < 2:
        tint = 0.0
    else:
        notes.append(f"Tint {tint:+.0f}: {'yashil' if tint > 0 else 'binafsha'} og‘ish to‘g‘rilandi")

    spread = m.luma_p95 - m.luma_p05
    if spread < 0.55:
        contrast = round(min(1.2, 1 + (0.55 - spread) * 0.6), 2)
        notes.append(f"Kontrast {contrast:.2f}: tasvir xira (diapazon {spread:.2f})")
    elif spread > 0.9:
        contrast = 0.95
    else:
        contrast = 1.03

    if m.saturation < 0.12:
        saturation = 1.15
        notes.append("To'yinganlik +15%: ranglar so'nik")
    elif m.saturation > 0.35:
        saturation = 0.92
        notes.append("To'yinganlik −8%: ranglar haddan tashqari")
    else:
        saturation = 1.05
    return ColorGrade(
        input_transform=transform,  # type: ignore[arg-type]
        exposure=exposure,
        temperature=temperature,
        tint=tint,
        contrast=contrast,
        saturation=saturation,
        creative_profile=profile,  # type: ignore[arg-type]
        intensity=intensity,
        notes=notes,
    )


def matched_grades(
    measures: list[ColorMeasure], *, transform: str = "none", profile: str = "neutral", intensity: float = 0.8
) -> list[ColorGrade]:
    """Shot matching: every shot of a scene is pulled to one shared exposure
    target — the scene's own median, kept inside a sane band — and to neutral
    white balance, so cuts between them do not jump."""
    usable = [m.luma_mean for m in measures if m.luma_mean > 0.04]
    target = max(0.38, min(0.52, statistics.median(usable))) if usable else TARGET_LUMA
    return [
        auto_grade(m, transform=transform, profile=profile, intensity=intensity, target_luma=target)
        for m in measures
    ]
