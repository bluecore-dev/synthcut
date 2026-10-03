"""Per-frame measurements on the grayscale sample stream, then per-shot
aggregates: exposure, sharpness, camera motion, frozen and black frames.

Everything is plain numbers from the pixels — no model — so it is fast,
repeatable and testable with synthetic frames.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Video-range luma (the proxy is limited range): 16 = black, 235 = white.
Y_BLACK, Y_WHITE = 16.0, 235.0
CRUSHED, CLIPPED = 20, 232
MIN_RESPONSE = 0.05  # phase-correlation peak below this: no reliable shift (cut, flat frame)


@dataclass(frozen=True, slots=True)
class FrameStats:
    luma: np.ndarray  # mean, 0..1
    dark: np.ndarray  # share of crushed pixels
    bright: np.ndarray  # share of clipped pixels
    sharpness: np.ndarray  # Laplacian variance
    shift: np.ndarray  # (n, 2) content shift from the previous frame, pixels; row 0 is 0
    reliable: np.ndarray  # whether ``shift`` is trustworthy
    diff: np.ndarray  # mean absolute difference to the previous frame, luma levels
    width: int
    height: int


def frame_stats(frames: np.ndarray) -> FrameStats:
    n = len(frames)
    h, w = (frames.shape[1], frames.shape[2]) if n else (0, 0)
    luma = np.zeros(n)
    dark = np.zeros(n)
    bright = np.zeros(n)
    sharp = np.zeros(n)
    shift = np.zeros((n, 2))
    reliable = np.zeros(n, dtype=bool)
    diff = np.zeros(n)
    window = cv2.createHanningWindow((w, h), cv2.CV_32F) if n else None
    prev: np.ndarray | None = None
    for i in range(n):
        f = np.asarray(frames[i])
        luma[i] = (float(f.mean()) - Y_BLACK) / (Y_WHITE - Y_BLACK)
        dark[i] = float((f <= CRUSHED).mean())
        bright[i] = float((f >= CLIPPED).mean())
        sharp[i] = float(cv2.Laplacian(f, cv2.CV_64F).var())
        cur = f.astype(np.float32)
        if prev is not None:
            diff[i] = float(np.abs(cur - prev).mean())
            # phaseCorrelate windows its inputs in place: hand it copies, or the
            # next frame's difference is measured against a windowed image.
            (dx, dy), response = cv2.phaseCorrelate(prev.copy(), cur.copy(), window)
            shift[i] = (dx, dy)
            reliable[i] = response >= MIN_RESPONSE
        prev = cur
    return FrameStats(np.clip(luma, 0, 1), dark, bright, sharp, shift, reliable, diff, w, h)


@dataclass(frozen=True, slots=True)
class ShotMeasure:
    frames: np.ndarray  # indices of sample frames inside the shot
    luma: float
    dark: float
    bright: float
    sharpness_var: float
    sharpness: float  # 0..1
    speed: float  # frame widths / s
    shake: float  # frame widths / s
    dx: float  # camera travel, frame widths (+ right)
    dy: float  # camera travel, frame heights (+ down)
    frozen: bool
    black: bool
    best_frame: int | None  # sharpest sample near the middle


def sharpness_score(laplacian_var: float) -> float:
    """Laplacian variance at 320 px → 0..1 on a log scale. Measured on a real
    1080p phone clip: sharp shots 950–3900; the same blurred σ=1.5 ≈ ½, σ=3
    ≈ 350, σ=6 ≈ 80–120. So 100 → 0 and 2500 → 1."""
    return float(np.clip((np.log10(laplacian_var + 1.0) - 2.0) / 1.4, 0.0, 1.0))


def _longest_run(mask: np.ndarray) -> int:
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def measure_shot(stats: FrameStats, fps: float, start: float, end: float) -> ShotMeasure:
    n = len(stats.luma)
    idx = np.arange(int(np.ceil(start * fps)), int(np.ceil(end * fps)))
    idx = idx[(idx >= 0) & (idx < n)]
    if len(idx) == 0 and n:
        idx = np.array([min(n - 1, max(0, round((start + end) / 2 * fps)))])
    if len(idx) == 0:
        zero = ShotMeasure(idx, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, False, None)
        return zero

    luma = float(np.median(stats.luma[idx]))
    sharp_var = float(np.median(stats.sharpness[idx]))
    # Motion uses frame pairs that both lie inside the shot (never across a cut).
    pairs = idx[1:] if len(idx) > 1 else np.array([], dtype=int)
    pairs = pairs[stats.reliable[pairs]] if len(pairs) else pairs
    w, h = max(stats.width, 1), max(stats.height, 1)
    if len(pairs):
        moves = stats.shift[pairs]
        speed = float(np.median(np.hypot(moves[:, 0] / w, moves[:, 1] / w)) * fps)
        jitter = np.diff(moves, axis=0) if len(moves) > 1 else np.zeros((1, 2))
        shake = float(np.median(np.hypot(jitter[:, 0] / w, jitter[:, 1] / w)) * fps)
        dx = float(-moves[:, 0].sum() / w)  # content moves left when the camera pans right
        dy = float(-moves[:, 1].sum() / h)
    else:
        speed = shake = dx = dy = 0.0
    still_pairs = stats.diff[idx[1:]] < 0.3 if len(idx) > 1 else np.array([], dtype=bool)
    frozen = _longest_run(still_pairs) + 1 >= 1.5 * fps if len(still_pairs) else False
    black = luma < 0.04 and float(np.median(stats.bright[idx])) < 0.001
    middle = idx[len(idx) // 4 : max(len(idx) // 4 + 1, 3 * len(idx) // 4)]
    best = int(middle[np.argmax(stats.sharpness[middle])]) if len(middle) else int(idx[0])
    return ShotMeasure(
        frames=idx,
        luma=luma,
        dark=float(np.median(stats.dark[idx])),
        bright=float(np.median(stats.bright[idx])),
        sharpness_var=sharp_var,
        sharpness=sharpness_score(sharp_var),
        speed=speed,
        shake=shake,
        dx=dx,
        dy=dy,
        frozen=bool(frozen),
        black=bool(black),
        best_frame=best,
    )


def dhash(frame: np.ndarray) -> str:
    """64-bit difference hash of a frame (same framing → small Hamming distance)."""
    small = cv2.resize(np.asarray(frame), (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()
