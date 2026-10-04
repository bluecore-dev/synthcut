"""Transfer curves and gamuts from their published definitions. Every
function is vectorised (NumPy arrays in, arrays out).

* Apple Log — "Apple Log Profile" white paper (2023): Rec.2020 primaries.
* S-Log3 / S-Gamut3.Cine — Sony technical summary (2014).
* Rec.709 display — BT.1886 with a pure 2.4 gamma (reference display, Lb = 0).
"""

from __future__ import annotations

import numpy as np

# Apple Log constants
_AL_R0 = -0.05641088
_AL_RT = 0.01
_AL_C = 47.28711236
_AL_B = 0.00964052
_AL_G = 0.08550479
_AL_BETA = 0.69336945
_AL_PT = _AL_C * (_AL_RT - _AL_R0) ** 2


def apple_log_encode(linear: np.ndarray) -> np.ndarray:
    x = np.asarray(linear, dtype=np.float64)
    out = np.where(
        x >= _AL_RT, _AL_G * np.log2(np.maximum(x, _AL_RT) + _AL_B) + _AL_BETA, _AL_C * (x - _AL_R0) ** 2
    )
    return np.where(x < _AL_R0, 0.0, out)


def apple_log_decode(code: np.ndarray) -> np.ndarray:
    p = np.asarray(code, dtype=np.float64)
    low = np.sqrt(np.maximum(p, 0.0) / _AL_C) + _AL_R0
    high = np.power(2.0, (p - _AL_BETA) / _AL_G) - _AL_B
    return np.where(p < _AL_PT, low, high)


def slog3_decode(code: np.ndarray) -> np.ndarray:
    """S-Log3 code value (0..1 full range) → scene-linear reflectance."""
    cv = np.asarray(code, dtype=np.float64) * 1023.0
    high = np.power(10.0, (cv - 420.0) / 261.5) * (0.18 + 0.01) - 0.01
    low = (cv - 95.0) * 0.01125000 / (171.2102946929 - 95.0)
    return np.where(cv >= 171.2102946929, high, low)


def slog3_encode(linear: np.ndarray) -> np.ndarray:
    x = np.asarray(linear, dtype=np.float64)
    high = (420.0 + np.log10((np.maximum(x, 0.01125000) + 0.01) / (0.18 + 0.01)) * 261.5) / 1023.0
    low = (x * (171.2102946929 - 95.0) / 0.01125000 + 95.0) / 1023.0
    return np.where(x >= 0.01125000, high, low)


GAMMA = 2.4


def display_decode(code: np.ndarray) -> np.ndarray:
    """Rec.709 video signal → display-linear light (BT.1886, Lb = 0)."""
    return np.power(np.clip(code, 0.0, 1.0), GAMMA)


def display_encode(linear: np.ndarray) -> np.ndarray:
    return np.power(np.clip(linear, 0.0, 1.0), 1.0 / GAMMA)


def _rgb_to_xyz(primaries: tuple[tuple[float, float], ...], white=(0.3127, 0.3290)) -> np.ndarray:
    cols = np.array([[x / y, 1.0, (1 - x - y) / y] for x, y in primaries]).T
    w = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    return cols * np.linalg.solve(cols, w)


REC709 = ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060))
REC2020 = ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046))
SGAMUT3_CINE = ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087))


def gamut_matrix(
    src: tuple[tuple[float, float], ...], dst: tuple[tuple[float, float], ...] = REC709
) -> np.ndarray:
    """Linear RGB in ``src`` primaries → linear RGB in ``dst`` (both D65)."""
    return np.linalg.inv(_rgb_to_xyz(dst)) @ _rgb_to_xyz(src)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec.709 luma weights (works on encoded or linear values)."""
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def filmic(x: np.ndarray) -> np.ndarray:
    """Scene-linear → display-linear tone curve for Log sources (Narkowicz's
    ACES fit): a toe, a shoulder that rolls highlights off instead of
    clipping them, and 18 % grey landing near display middle grey."""
    x = np.maximum(np.asarray(x, dtype=np.float64), 0.0) * 0.6
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0)
