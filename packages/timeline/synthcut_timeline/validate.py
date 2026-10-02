"""Semantic validation of an EditPlan (spec §24, rule 6).

Pydantic enforces shape and per-field ranges; this module checks what only
the whole plan can tell: overlaps, gaps that would render black frames,
duration consistency, references to assets that do not exist, sources read
past their end, unknown motion components. Every problem is reported at once
with a path, so the reflection loop (spec §25) can patch them in one pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from pydantic import BaseModel, ValidationError

from .models import AudioClip, EditPlan, Keyframe, VideoClip, VideoTrack
from .registry import GRAPHICS_REGISTRY, ComponentSpec


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Issue(BaseModel):
    code: str
    severity: Severity
    path: str
    message: str


class ValidationReport(BaseModel):
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}


class PlanValidationError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        summary = "; ".join(f"{i.code} at {i.path}" for i in report.errors[:5])
        super().__init__(f"EditPlan invalid: {summary}")


@dataclass(frozen=True, slots=True)
class AssetFacts:
    kind: str  # "video" | "audio" | "image" | "other"
    duration: float | None
    has_audio: bool = True


class _Collector:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code=code, severity=Severity.ERROR, path=path, message=message))

    def warn(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code=code, severity=Severity.WARNING, path=path, message=message))


def _main_track(plan: EditPlan) -> tuple[int, VideoTrack] | None:
    mains = [(i, t) for i, t in enumerate(plan.video_tracks) if t.role == "main"]
    return min(mains, key=lambda it: it[1].track) if mains else None


def _check_keyframes(c: _Collector, path: str, keyframes: Iterable[Keyframe], duration: float, tol: float):
    for k, kf in enumerate(keyframes):
        if kf.t > duration + tol:
            c.error("E_KEYFRAME_RANGE", f"{path}.keyframes[{k}]", f"keyframe at {kf.t}s is past the item end")


def _check_sourced(c: _Collector, path: str, item: VideoClip | AudioClip, frame: float) -> None:
    expected = (item.source_out - item.source_in) / item.speed
    if abs(expected - item.timeline_duration) > frame + 1e-9:
        c.error(
            "E_DURATION_MISMATCH",
            path,
            f"source range / speed = {expected:.3f}s but timeline range = {item.timeline_duration:.3f}s",
        )


def _check_alignment(c: _Collector, path: str, fps: int, *times: float) -> None:
    for t in times:
        frames = t * fps
        if abs(frames - round(frames)) > 0.05:
            c.warn("W_FRAME_ALIGNMENT", path, f"{t}s is not on a frame boundary at {fps} fps")
            return


def _check_asset(
    c: _Collector,
    path: str,
    asset_id: UUID,
    source_out: float,
    assets: Mapping[UUID, AssetFacts],
    *,
    want: set[str],
    tol: float,
) -> None:
    facts = assets.get(asset_id)
    if facts is None:
        c.error("E_UNKNOWN_ASSET", path, f"asset {asset_id} is not in this project")
        return
    if facts.kind not in want:
        c.error("E_ASSET_KIND", path, f"asset {asset_id} is {facts.kind}, expected one of {sorted(want)}")
        return
    if facts.duration is not None and source_out > facts.duration + tol:
        c.error(
            "E_SOURCE_RANGE",
            path,
            f"source_out {source_out:.3f}s is past the media end ({facts.duration:.3f}s)",
        )


def validate_plan(
    plan: EditPlan,
    *,
    assets: Mapping[UUID, AssetFacts] | None = None,
    registry: Mapping[str, ComponentSpec] = GRAPHICS_REGISTRY,
) -> ValidationReport:
    c = _Collector()
    seq = plan.sequence
    frame = seq.frame
    tol = frame / 2

    # Unique ids and track numbers -------------------------------------------------
    seen: dict[str, str] = {}

    def claim_id(item_id: str, path: str) -> None:
        if item_id in seen:
            c.error("E_DUPLICATE_ID", path, f"id {item_id!r} already used at {seen[item_id]}")
        else:
            seen[item_id] = path

    for kind, tracks in (("video_tracks", plan.video_tracks), ("audio_tracks", plan.audio_tracks)):
        numbers = [t.track for t in tracks]
        for n in {n for n in numbers if numbers.count(n) > 1}:
            c.error("E_DUPLICATE_TRACK", kind, f"track number {n} is used more than once")

    main = _main_track(plan)
    if main is None:
        c.error("E_NO_MAIN_TRACK", "video_tracks", "a video track with role 'main' is required")

    # Video tracks ------------------------------------------------------------------
    for ti, track in enumerate(plan.video_tracks):
        tpath = f"video_tracks[{ti}]"
        ordered = sorted(enumerate(track.clips), key=lambda ic: ic[1].timeline_start)
        is_main = main is not None and main[0] == ti
        for ci, clip in enumerate(track.clips):
            path = f"{tpath}.clips[{ci}]"
            claim_id(clip.id, path)
            _check_sourced(c, path, clip, frame)
            _check_alignment(c, path, seq.fps, clip.timeline_start, clip.timeline_end)
            _check_keyframes(c, path, clip.keyframes, clip.timeline_duration, tol)
            if clip.timeline_end > seq.duration + tol:
                c.error(
                    "E_OUT_OF_SEQUENCE", path, f"ends at {clip.timeline_end}s, sequence is {seq.duration}s"
                )
            if clip.transition_in and clip.transition_in.duration > clip.timeline_duration / 2 + 1e-9:
                c.error("E_TRANSITION_TOO_LONG", path, "transition is longer than half the clip")
            if assets is not None:
                _check_asset(
                    c, path, clip.asset_id, clip.source_out, assets, want={"video", "image"}, tol=tol
                )
        for (ai, a), (bi, b) in pairwise(ordered):
            allowed = 0.0
            if b.transition_in and b.transition_in.type != "cut":
                allowed = b.transition_in.duration
            overlap = a.timeline_end - b.timeline_start
            if overlap > allowed + tol:
                c.error(
                    "E_OVERLAP",
                    f"{tpath}.clips[{bi}]",
                    f"overlaps clips[{ai}] by {overlap:.3f}s (transition allows {allowed:.3f}s)",
                )
            elif is_main and -overlap > tol:
                c.error(
                    "E_MAIN_GAP",
                    f"{tpath}.clips[{bi}]",
                    f"{-overlap:.3f}s gap after clips[{ai}] would render black frames",
                )
        if is_main:
            if not track.clips:
                c.error("E_MAIN_EMPTY", tpath, "the main track has no clips")
            else:
                first = ordered[0][1]
                last_end = max(cl.timeline_end for cl in track.clips)
                if first.timeline_start > tol:
                    c.error("E_MAIN_COVERAGE", tpath, f"main track starts at {first.timeline_start}s, not 0")
                if last_end < seq.duration - tol:
                    c.error(
                        "E_MAIN_COVERAGE",
                        tpath,
                        f"main track ends at {last_end}s, sequence is {seq.duration}s",
                    )

    # Audio tracks ------------------------------------------------------------------
    for ti, track in enumerate(plan.audio_tracks):
        tpath = f"audio_tracks[{ti}]"
        for ci, clip in enumerate(track.clips):
            path = f"{tpath}.clips[{ci}]"
            claim_id(clip.id, path)
            _check_sourced(c, path, clip, frame)
            _check_keyframes(c, path, clip.keyframes, clip.timeline_duration, tol)
            if clip.timeline_end > seq.duration + tol:
                c.error(
                    "E_OUT_OF_SEQUENCE", path, f"ends at {clip.timeline_end}s, sequence is {seq.duration}s"
                )
            if clip.fade_in + clip.fade_out > clip.timeline_duration + 1e-9:
                c.error("E_FADE_RANGE", path, "fade in + fade out is longer than the clip")
            if assets is not None and clip.source.asset_id is not None:
                facts = assets.get(clip.source.asset_id)
                if facts is not None and facts.kind == "video" and not facts.has_audio:
                    c.error("E_ASSET_KIND", path, "video asset has no audio stream")
                else:
                    _check_asset(
                        c,
                        path,
                        clip.source.asset_id,
                        clip.source_out,
                        assets,
                        want={"audio", "video"},
                        tol=tol,
                    )
        ordered = sorted(track.clips, key=lambda cl: cl.timeline_start)
        for a, b in pairwise(ordered):
            if a.timeline_end - b.timeline_start > tol:
                c.warn("W_AUDIO_OVERLAP", tpath, f"{a.id} and {b.id} overlap on the same track")

    # Graphics ----------------------------------------------------------------------
    for gi, item in enumerate(plan.graphics):
        path = f"graphics[{gi}]"
        claim_id(item.id, path)
        if item.timeline_end > seq.duration + tol:
            c.error("E_OUT_OF_SEQUENCE", path, f"ends at {item.timeline_end}s, sequence is {seq.duration}s")
        spec = registry.get(item.component)
        if spec is None:
            c.error("E_UNKNOWN_COMPONENT", path, f"{item.component} is not in the motion registry")
        elif spec.props_model is not None:
            try:
                spec.props_model.model_validate(item.props)
            except ValidationError as exc:
                c.error("E_COMPONENT_PROPS", f"{path}.props", exc.errors(include_url=False).__repr__()[:500])

    return ValidationReport(issues=c.issues)


def ensure_valid(plan: EditPlan, **kwargs) -> EditPlan:
    report = validate_plan(plan, **kwargs)
    if not report.ok:
        raise PlanValidationError(report)
    return plan


def snap_to_frames(plan: EditPlan) -> EditPlan:
    """Return a copy with every timeline boundary moved to the nearest frame."""
    fps = plan.sequence.fps

    def snap(t: float) -> float:
        return round(round(t * fps) / fps, 6)

    data = plan.model_dump()
    for track in data["video_tracks"] + data["audio_tracks"]:
        for clip in track["clips"]:
            clip["timeline_start"] = snap(clip["timeline_start"])
            clip["timeline_end"] = snap(clip["timeline_end"])
    for item in data["graphics"]:
        item["timeline_start"] = snap(item["timeline_start"])
        item["timeline_end"] = snap(item["timeline_end"])
    return EditPlan.model_validate(data)
