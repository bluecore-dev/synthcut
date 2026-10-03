"""Measurements → ``ClipAnalysis``: camera motion class, quality scores,
flags and a usability score.

The scores are heuristics over measured numbers, written down here so they
can be argued with: usable = mostly sharp, steady and well exposed; flags name
what is wrong in words an editor uses. The vision agent (Phase 5b) refines
``usable_score`` with content (bad take, wrong subject) — it never needs to
re-measure.
"""

from __future__ import annotations

from dataclasses import dataclass

from synthcut_schemas.analysis import ClipAnalysis, Exposure, Face, Motion, Span

from .faces import position, shot_type
from .measure import ShotMeasure

STATIC_SPEED = 0.02  # frame widths / s
STATIC_SHAKE = 0.04  # residual jitter of a tripod shot (compression, noise)
SHAKY = 0.08
TRAVEL = 0.15  # net travel (frame widths) that makes a pan / tilt


def camera_motion(m: ShotMeasure) -> str:
    if m.speed < STATIC_SPEED and m.shake < STATIC_SHAKE:
        return "static"
    if m.shake > max(STATIC_SHAKE, m.speed * 0.8):
        return "handheld"  # jitter dominates any travel
    if abs(m.dx) >= abs(m.dy) and abs(m.dx) > TRAVEL:
        return "pan_right" if m.dx > 0 else "pan_left"
    if abs(m.dy) > TRAVEL:
        return "tilt_down" if m.dy > 0 else "tilt_up"
    return "moving"


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def lighting_quality(m: ShotMeasure) -> float:
    under = _clamp((0.25 - m.luma) / 0.2)
    over = _clamp((m.luma - 0.75) / 0.2)
    crushed = _clamp((m.dark - 0.10) / 0.40)
    clipped = _clamp((m.bright - 0.02) / 0.15)
    return round(_clamp(1.0 - max(under, over) - 0.5 * crushed - 0.5 * clipped), 3)


def camera_quality(m: ShotMeasure) -> float:
    steadiness = 1.0 - 0.6 * _clamp(m.shake / 0.15)
    return round(_clamp(m.sharpness * steadiness), 3)


@dataclass(frozen=True, slots=True)
class ClipContext:
    asset_prefix: str
    resolution: str | None
    fps: float | None
    color_profile: str | None
    audio_present: bool


def is_blurry(m: ShotMeasure, reference_var: float | None) -> bool:
    """Absolutely soft, or much softer than the rest of the same footage —
    texture differs per scene (a brick wall measures sharper than a sky), so
    the clip's own median is the better yardstick for a focus miss."""
    if m.sharpness < 0.25:
        return True
    return bool(reference_var) and m.sharpness_var < 0.3 * reference_var and m.sharpness < 0.6


def subject_for(face_count: int) -> str | None:
    if face_count <= 0:
        return None
    return "person" if face_count == 1 else "people" if face_count <= 4 else "crowd"


def _flags(m: ShotMeasure, duration: float, duplicate: bool, reference_var: float | None) -> list[str]:
    flags: list[str] = []
    if m.black:
        flags.append("black")
    if not m.black and is_blurry(m, reference_var):
        flags.append("blurry")
    if not m.black and (m.luma < 0.15 or m.dark > 0.40):
        flags.append("underexposed")
    if m.luma > 0.85 or m.bright > 0.15:
        flags.append("overexposed")
    if m.shake > SHAKY:
        flags.append("shaky")
    if m.frozen and not m.black:
        flags.append("frozen")
    if duration < 0.6:
        flags.append("too_short")
    if duplicate:
        flags.append("duplicate")
    return flags


def usable_score(camera: float, lighting: float, flags: list[str]) -> float:
    if "black" in flags:
        return 0.0
    score = 0.1 + 0.5 * camera + 0.4 * lighting
    if "too_short" in flags:
        score *= 0.5
    if "frozen" in flags:
        score *= 0.5
    return round(_clamp(score), 3)


def speech_in(spans: list[Span], start: float, end: float) -> tuple[float, list[Span]]:
    """Share of the shot with speech, and the silent gaps (≥ 0.7 s) inside it."""
    duration = max(end - start, 1e-6)
    inside = [
        Span(start=max(s.start, start), end=min(s.end, end)) for s in spans if s.end > start and s.start < end
    ]
    spoken = sum(s.end - s.start for s in inside)
    gaps: list[Span] = []
    cursor = start
    for s in inside:
        if s.start - cursor >= 0.7:
            gaps.append(Span(start=round(cursor, 3), end=round(s.start, 3)))
        cursor = max(cursor, s.end)
    if end - cursor >= 0.7:
        gaps.append(Span(start=round(cursor, 3), end=round(end, 3)))
    return round(min(1.0, spoken / duration), 3), gaps


def build_clip(
    ctx: ClipContext,
    *,
    index: int,
    start: float,
    end: float,
    measure: ShotMeasure,
    faces: list[Face],
    face_count: int,
    speech: list[Span] | None,
    duplicate_of: str | None,
    sample_fps: float,
    reference_var: float | None = None,
) -> ClipAnalysis:
    duration = round(end - start, 3)
    flags = _flags(measure, duration, duplicate_of is not None, reference_var)
    camera = camera_quality(measure)
    lighting = lighting_quality(measure)
    ratio, gaps = speech_in(speech, start, end) if speech is not None and ctx.audio_present else (0.0, [])
    best = None if measure.best_frame is None else round(measure.best_frame / sample_fps, 3)
    return ClipAnalysis(
        clip_id=f"{ctx.asset_prefix}-s{index:03d}",
        index=index,
        start=round(start, 3),
        end=round(end, 3),
        duration=duration,
        resolution=ctx.resolution,
        fps=ctx.fps,
        color_profile=ctx.color_profile,
        shot_type=shot_type(faces),
        subject=subject_for(face_count),
        face_detected=bool(faces),
        face_count=face_count,
        faces=faces[:5],
        person_position=position(faces),
        camera_motion=camera_motion(measure),
        sharpness=round(measure.sharpness, 3),
        exposure=Exposure(
            mean=round(measure.luma, 3), dark=round(measure.dark, 3), bright=round(measure.bright, 3)
        ),
        motion=Motion(
            speed=round(measure.speed, 4),
            shake=round(measure.shake, 4),
            dx=round(measure.dx, 3),
            dy=round(measure.dy, 3),
        ),
        camera_quality=camera,
        lighting_quality=lighting,
        audio_present=ctx.audio_present,
        speech_present=ratio >= 0.15,
        speech_ratio=ratio,
        silence_segments=gaps,
        usable_score=usable_score(camera, lighting, flags),
        flags=flags,
        duplicate_of=duplicate_of,
        best_frame=best,
    )
