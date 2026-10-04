"""``grade/1`` → a function on RGB, baked into a 3D LUT (spec §11).

Order (each step in the space where it is physically meaningful):

1. **input transform** — source code values → linear light in Rec.709
   primaries (Apple Log / S-Log3 decode + gamut matrix; Rec.709 sources via
   the BT.1886 display curve);
2. **exposure** — multiply linear light by 2^stops;
3. **white balance** — per-channel gains in linear light, luminance kept;
4. **output transform** — Log sources through a filmic tone curve (highlights
   roll off instead of clipping), then Rec.709 display encoding;
5. **contrast / saturation** — on the display-encoded image around 18 % grey;
6. **creative profile** — a named look, blended by ``intensity``.

The LUT is evaluated on a 33³ grid and written as ``.cube`` for FFmpeg's
``lut3d`` (tetrahedral). No third-party LUTs: every look is a formula here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from synthcut_schemas.grade import ColorGrade

from .spaces import (
    REC2020,
    SGAMUT3_CINE,
    apple_log_decode,
    display_decode,
    display_encode,
    filmic,
    gamut_matrix,
    luma,
    slog3_decode,
)

LUT_SIZE = 33
GREY = 0.18 ** (1 / 2.4)  # 18 % grey on the Rec.709 display curve (~0.49)

_TO_709_FROM_2020 = gamut_matrix(REC2020)
_TO_709_FROM_SGAMUT3C = gamut_matrix(SGAMUT3_CINE)


def to_linear(rgb: np.ndarray, transform: str) -> tuple[np.ndarray, bool]:
    """(linear Rec.709 RGB, whether it is scene-referred and needs tone mapping)."""
    if transform == "apple_log":
        return apple_log_decode(rgb) @ _TO_709_FROM_2020.T, True
    if transform == "slog3":
        return slog3_decode(rgb) @ _TO_709_FROM_SGAMUT3C.T, True
    if transform == "log_generic":
        # Unknown camera log: a generic log-to-linear (Cineon-like) — an
        # approximation, flagged as such in the grade's notes.
        return np.clip(np.power(10.0, (rgb - 0.6) * 2.4) * 0.18 - 0.002, 0.0, None), True
    return display_decode(rgb), False


def wb_gains(temperature: float, tint: float) -> np.ndarray:
    """Warm = more red, less blue; tint + = magenta (less green). Normalised so
    that luminance is unchanged."""
    gains = np.array([1.0 + 0.0045 * temperature, 1.0 - 0.003 * tint, 1.0 - 0.0045 * temperature])
    return gains / float(luma(gains))


def contrast_curve(v: np.ndarray, amount: float) -> np.ndarray:
    """An S-curve pivoting on 18 % grey: slope ``amount`` at the pivot, black
    stays black and white stays white, so a boost never clips highlights flat."""
    if abs(amount - 1.0) < 1e-6:
        return v
    v = np.clip(v, 0.0, 1.0)
    below = GREY * np.power(v / GREY, amount)
    above = 1.0 - (1.0 - GREY) * np.power((1.0 - v) / (1.0 - GREY), amount)
    return np.where(v < GREY, below, above)


def saturate(v: np.ndarray, amount: float) -> np.ndarray:
    y = luma(v)[..., None]
    return y + (v - y) * amount


def _split_tone(
    v: np.ndarray, shadows: tuple[float, float, float], highlights: tuple[float, float, float]
) -> np.ndarray:
    y = luma(v)[..., None]
    return v + (1 - y) ** 2 * np.array(shadows) + y**2 * np.array(highlights)


PROFILES: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "neutral": lambda v: v,
    # Teal shadows, warm skin-friendly highlights, gentle contrast — the "clean cinema" look.
    "cinematic_clean": lambda v: saturate(
        contrast_curve(_split_tone(v, (-0.025, 0.006, 0.03), (0.03, 0.008, -0.02)), 1.06), 0.94
    ),
    # Lifted blacks, warm cast, softer saturation.
    "warm_film": lambda v: saturate(
        0.035 + 0.95 * _split_tone(v, (0.012, 0.004, -0.01), (0.035, 0.012, -0.03)), 0.88
    ),
    "cool_teal": lambda v: contrast_curve(_split_tone(v, (-0.02, 0.01, 0.035), (-0.015, 0.005, 0.02)), 1.08),
    # Punchy for phone screens: more contrast, vibrance favouring muted colours.
    "vivid_social": lambda v: contrast_curve(_vibrance(v, 0.35), 1.1),
    "bw_classic": lambda v: np.repeat(contrast_curve(luma(v)[..., None], 1.15), 3, axis=-1),
}


def _vibrance(v: np.ndarray, amount: float) -> np.ndarray:
    y = luma(v)[..., None]
    chroma = np.max(v, axis=-1, keepdims=True) - np.min(v, axis=-1, keepdims=True)
    return y + (v - y) * (1 + amount * (1 - np.clip(chroma * 2, 0, 1)))


def apply_grade(rgb: np.ndarray, grade: ColorGrade) -> np.ndarray:
    """Encoded source RGB (0..1) → graded Rec.709 RGB (0..1)."""
    lin, scene = to_linear(np.asarray(rgb, dtype=np.float64), grade.input_transform)
    lin = lin * (2.0**grade.exposure)
    lin = lin * wb_gains(grade.temperature, grade.tint)
    display = filmic(lin) if scene else np.clip(lin, 0.0, 1.0)
    v = display_encode(display)
    v = contrast_curve(v, grade.contrast)
    v = saturate(v, grade.saturation)
    v = np.clip(v, 0.0, 1.0)
    looked = np.clip(PROFILES[grade.creative_profile](v), 0.0, 1.0)
    return np.clip(v + (looked - v) * grade.intensity, 0.0, 1.0)


def bake(grade: ColorGrade, size: int = LUT_SIZE) -> np.ndarray:
    """(size, size, size, 3) indexed [b, g, r] — the order .cube files list entries."""
    axis = np.linspace(0.0, 1.0, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], axis=-1)
    return apply_grade(grid.reshape(-1, 3), grade).reshape(size, size, size, 3)


def write_cube(lut: np.ndarray, path: Path, *, title: str = "SynthCut grade") -> Path:
    size = lut.shape[0]
    rows = lut.reshape(-1, 3)
    with path.open("w") as f:
        f.write(f'TITLE "{title}"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        np.savetxt(f, rows, fmt="%.6f")
    return path


def is_identity(grade: ColorGrade) -> bool:
    return (
        grade.input_transform == "none"
        and grade.exposure == 0
        and grade.temperature == 0
        and grade.tint == 0
        and grade.contrast == 1
        and grade.saturation == 1
        and (grade.creative_profile == "neutral" or grade.intensity == 0)
    )
