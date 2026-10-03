"""One asset end to end, without storage or database: proxy (+ speech spans)
→ per-shot ``ClipAnalysis``, a dHash per shot and a JPEG sheet per shot
(three stills: early, middle, late) for people and the vision agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from synthcut_schemas.analysis import ClipAnalysis, Span

from .clips import ClipContext, build_clip
from .faces import FaceDetector
from .frames import sample_gray, sample_rate, still
from .measure import dhash, frame_stats, hamming, measure_shot

SHEET_TILE = 384
DUPLICATE_DISTANCE = 6  # of 64 bits


@dataclass
class AssetAnalysis:
    clips: list[ClipAnalysis]
    hashes: dict[int, str]  # shot index -> dHash
    sheets: dict[int, bytes] = field(default_factory=dict)  # shot index -> JPEG
    sample_fps: float = 0.0


def _sheet(images: list[np.ndarray]) -> bytes:
    tiles = []
    for img in images:
        h, w = img.shape[:2]
        tiles.append(
            cv2.resize(img, (SHEET_TILE, max(2, round(SHEET_TILE * h / w))), interpolation=cv2.INTER_AREA)
        )
    height = min(t.shape[0] for t in tiles)
    ok, buf = cv2.imencode(".jpg", cv2.hconcat([t[:height] for t in tiles]), [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise RuntimeError("could not encode shot sheet")
    return buf.tobytes()


def _sample_times(start: float, end: float) -> list[float]:
    d = end - start
    if d < 1.0:
        return [start + d / 2]
    return [start + 0.15 * d, start + 0.5 * d, end - 0.15 * d]


def analyze(
    proxy: Path,
    work: Path,
    *,
    ctx: ClipContext,
    width: int,
    height: int,
    duration: float,
    shots: list[tuple[float, float]],
    speech: list[Span] | None,
    known_hashes: dict[str, str] | None = None,  # clip_id -> dHash of earlier clips in the project
    check: Callable[[], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> AssetAnalysis:
    fps = sample_rate(duration)
    frames = sample_gray(proxy, work, width=width, height=height, fps=fps, duration=duration, check=check)
    if on_progress:
        on_progress(0.3)
    stats = frame_stats(frames)
    if on_progress:
        on_progress(0.5)
    detector = FaceDetector()
    earlier = dict(known_hashes or {})
    result = AssetAnalysis(clips=[], hashes={}, sample_fps=fps)
    spans = shots or [(0.0, duration)]
    measures = [measure_shot(stats, fps, start, end) for start, end in spans]
    usable = [m.sharpness_var for m in measures if not m.black and len(m.frames)]
    reference_var = float(np.median(usable)) if usable else None
    for index, ((start, end), m) in enumerate(zip(spans, measures, strict=True)):
        if check:
            check()
        stills = []
        best_faces: list = []
        face_count = 0
        for n, t in enumerate(_sample_times(start, end)):
            path = still(
                proxy, min(t, max(0.0, duration - 0.05)), work / f"still_{index}_{n}.jpg", check=check
            )
            img = cv2.imread(str(path))
            path.unlink(missing_ok=True)
            if img is None:
                continue
            stills.append(img)
            faces = detector.detect(img)
            face_count = max(face_count, len(faces))
            if faces and (not best_faces or faces[0].height > best_faces[0].height):
                best_faces = faces
        hash_frame = m.best_frame if m.best_frame is not None else None
        digest = dhash(frames[hash_frame]) if hash_frame is not None and len(frames) else None
        duplicate_of = None
        if digest is not None and not m.black:
            for clip_id, other in earlier.items():
                if hamming(digest, other) <= DUPLICATE_DISTANCE:
                    duplicate_of = clip_id
                    break
        clip = build_clip(
            ctx,
            index=index,
            start=start,
            end=end,
            measure=m,
            faces=best_faces,
            face_count=face_count,
            speech=speech,
            duplicate_of=duplicate_of,
            sample_fps=fps,
            reference_var=reference_var,
        )
        result.clips.append(clip)
        if digest is not None:
            result.hashes[index] = digest
            earlier[clip.clip_id] = digest
        if stills:
            result.sheets[index] = _sheet(stills)
        if on_progress:
            on_progress(0.5 + 0.5 * (index + 1) / len(spans))
    del frames
    (work / "frames.gray").unlink(missing_ok=True)
    return result
