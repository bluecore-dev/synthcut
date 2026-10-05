"""Agent edits → a valid EditPlan (pure: no database, no model).

An agent does not write timeline seconds for the main track. It lists the
story in order — which source range of which asset, how fast, how each cut
arrives (cut / crossfade / dip / whip / zoom), placement and keyframes — and
this module lays it out on the frame grid: every clip starts where the
previous one ends (minus the transition overlap), source ranges are trimmed
to whole frames, the sequence ends with the last clip. Overlays (cutaways,
picture-in-picture), graphics and captions are placed at timeline seconds
the agent chooses. Colour and placement the agent does not mention are
inherited from the base plan, so a re-ordered clip keeps its grade and its
face-centred framing.

The result still goes through ``validate_plan`` before it is saved; the
issues go back to the agent, which fixes them.
"""

from __future__ import annotations

import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from synthcut_timeline import (
    AudioTrack,
    CaptionTrack,
    EditPlan,
    EffectRef,
    GraphicsItem,
    Keyframe,
    Transform,
    Transition,
    VideoClip,
    VideoTrack,
)
from synthcut_timeline.autoedit import Music, Options, music_track

TransitionType = Literal["cut", "crossfade", "dip_to_black", "dip_to_white", "whip", "zoom"]
Easing = Literal["linear", "ease_in", "ease_out", "ease_in_out", "hold"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransitionIn(_In):
    type: TransitionType = "crossfade"
    duration: float = Field(0.4, ge=0.1, le=2.0)


class PlacementIn(_In):
    """``scale`` 1 = the picture covers the frame; ``x`` / ``y`` move its centre
    in frame widths / heights (+x right, +y down)."""

    scale: float = Field(1.0, ge=0.1, le=4.0)
    x: float = Field(0.0, ge=-2.0, le=2.0)
    y: float = Field(0.0, ge=-2.0, le=2.0)
    rotation: float = Field(0.0, ge=-45, le=45)


class KeyframeIn(_In):
    t: float = Field(ge=0, description="Seconds from the clip's own start on the timeline")
    property: Literal["scale", "x", "y", "opacity"]
    value: float
    easing: Easing = "ease_in_out"


class MainClipIn(_In):
    asset_id: UUID
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    speed: float = Field(1.0, ge=0.25, le=4.0)
    transition: TransitionIn | None = Field(None, description="How this clip arrives; none = a cut")
    placement: PlacementIn | None = Field(
        None, description="None = keep the base plan's framing of this asset"
    )
    keyframes: list[KeyframeIn] = Field(default_factory=list, max_length=24)
    mute: bool = False
    why: str | None = Field(None, max_length=200)


class OverlayIn(_In):
    asset_id: UUID
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    at: float = Field(ge=0, description="Timeline second where it appears")
    kind: Literal["cutaway", "pip"] = "cutaway"
    placement: PlacementIn | None = None
    keyframes: list[KeyframeIn] = Field(default_factory=list, max_length=24)
    fade_in: float = Field(0.15, ge=0, le=2)
    fade_out: float = Field(0.15, ge=0, le=2)
    speed: float = Field(1.0, ge=0.25, le=4.0)
    mute: bool = True
    why: str | None = Field(None, max_length=200)


class GraphicIn(_In):
    component: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{1,40}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    layer: int = Field(1, ge=1, le=8)
    props: dict = Field(default_factory=dict)


class CaptionsIn(_In):
    enabled: bool = True
    style: Literal["dynamic", "karaoke", "minimal", "bold"] = "dynamic"
    position: Literal["bottom", "center", "top"] = "bottom"
    max_words_per_line: int = Field(3, ge=1, le=8)


class PlanEdit(_In):
    """What an agent changes. A section left out (None) is kept from the base
    plan; an empty list clears it."""

    base_version: int | None = Field(None, description="Plan version to start from; latest if omitted")
    main: list[MainClipIn] | None = Field(None, min_length=1, max_length=400)
    overlays: list[OverlayIn] | None = Field(None, max_length=200)
    graphics: list[GraphicIn] | None = Field(None, max_length=100)
    captions: CaptionsIn | None = None
    notes: str = Field(min_length=3, max_length=2000, description="Why — shown to the owner (Uzbek)")


DEFAULT_PIP = PlacementIn(scale=0.35, x=0.28, y=-0.26)


def _snap(t: float, fps: int) -> float:
    return round(round(t * fps) / fps, 6)


def _inherited(base: EditPlan, asset_id: UUID, source_in: float) -> tuple[Transform, list[EffectRef]]:
    """Framing and colour of the base clip of this asset nearest in the source."""
    candidates = [c for t in base.video_tracks if t.role == "main" for c in t.clips if c.asset_id == asset_id]
    if not candidates:
        return Transform(), []
    nearest = min(
        candidates,
        key=lambda c: 0 if c.source_in <= source_in < c.source_out else abs(c.source_in - source_in),
    )
    return nearest.transform, [e for e in nearest.effects if e.type in ("grade", "background")]


def _grade_of(base: EditPlan, asset_id: UUID) -> list[EffectRef]:
    for t in base.video_tracks:
        for c in t.clips:
            if c.asset_id == asset_id:
                return [e for e in c.effects if e.type == "grade"]
    return []


def _transform(p: PlacementIn) -> Transform:
    return Transform(scale=p.scale, x=p.x, y=p.y, rotation=p.rotation)


def _keyframes(items: list[KeyframeIn], length: float) -> list[Keyframe]:
    return [Keyframe(t=min(k.t, length), property=k.property, value=k.value, easing=k.easing) for k in items]


def layout_main(
    base: EditPlan, clips: list[MainClipIn], fps: int, durations: dict[UUID, float]
) -> list[VideoClip]:
    out: list[VideoClip] = []
    t = 0.0
    for n, c in enumerate(clips):
        limit = durations.get(c.asset_id, math.inf)
        if c.source_in >= limit - 1 / fps:
            raise ValueError(
                f"main[{n}]: source_in {c.source_in:g} s starts after the asset ends ({limit:g} s)"
            )
        src_out = min(c.source_out, limit)
        length = _snap((src_out - c.source_in) / c.speed, fps)
        if length < 1 / fps:
            raise ValueError(f"main[{n}]: source range is shorter than a frame")
        trans = c.transition if c.transition and c.transition.type != "cut" and out else None
        overlap = 0.0
        if trans is not None:
            overlap = min(
                _snap(trans.duration, fps), _snap(length / 2, fps), _snap(out[-1].timeline_duration / 2, fps)
            )
        start = _snap(t - overlap, fps)
        transform, effects = _inherited(base, c.asset_id, c.source_in)
        if c.placement is not None:
            transform = _transform(c.placement)
            effects = [e for e in effects if e.type == "grade"] + (
                [EffectRef(type="background", params={"fill": "blur"})] if c.placement.scale < 1 else []
            )
        out.append(
            VideoClip(
                id=f"m{n + 1:03d}",
                asset_id=c.asset_id,
                source_in=round(c.source_in, 6),
                source_out=round(c.source_in + length * c.speed, 6),
                speed=c.speed,
                timeline_start=start,
                timeline_end=round(start + length, 6),
                transform=transform,
                effects=effects,
                keyframes=_keyframes(c.keyframes, length),
                transition_in=Transition(type=trans.type, duration=overlap) if trans is not None else None,
                mute_source_audio=c.mute,
                metadata={"why": c.why} if c.why else {},
            )
        )
        t = out[-1].timeline_end
    return out


def layout_overlays(base: EditPlan, items: list[OverlayIn], fps: int) -> list[VideoClip]:
    out: list[VideoClip] = []
    for n, o in enumerate(items):
        length = _snap((o.source_out - o.source_in) / o.speed, fps)
        if length < 1 / fps:
            raise ValueError(f"overlays[{n}]: source range is shorter than a frame")
        start = _snap(o.at, fps)
        placement = o.placement or (DEFAULT_PIP if o.kind == "pip" else PlacementIn())
        keys = _keyframes(o.keyframes, length)
        if not any(k.property == "opacity" for k in keys) and (o.fade_in or o.fade_out):
            fi, fo = min(o.fade_in, length / 2), min(o.fade_out, length / 2)
            keys += [
                Keyframe(t=0.0, property="opacity", value=0.0 if fi else 1.0, easing="linear"),
                Keyframe(t=round(fi, 6), property="opacity", value=1.0, easing="hold"),
                Keyframe(t=round(length - fo, 6), property="opacity", value=1.0, easing="linear"),
                Keyframe(t=round(length, 6), property="opacity", value=0.0 if fo else 1.0),
            ]
        out.append(
            VideoClip(
                id=f"o{n + 1:03d}",
                asset_id=o.asset_id,
                source_in=round(o.source_in, 6),
                source_out=round(o.source_in + length * o.speed, 6),
                speed=o.speed,
                timeline_start=start,
                timeline_end=round(start + length, 6),
                transform=_transform(placement),
                effects=_grade_of(base, o.asset_id),
                keyframes=keys,
                mute_source_audio=o.mute,
                metadata={"why": o.why, "kind": o.kind} if o.why else {"kind": o.kind},
            )
        )
    return out


def apply_edit(
    base: EditPlan,
    edit: PlanEdit,
    *,
    version: int,
    durations: dict[UUID, float],
    names: dict[UUID, str] | None = None,
    agent: str,
) -> EditPlan:
    """The new plan version: base + the agent's changes, laid out on the
    frame grid. ``durations`` caps source ranges at each asset's length."""
    fps = base.sequence.fps
    main_track = next(t for t in base.video_tracks if t.role == "main")
    mains = layout_main(base, edit.main, fps, durations) if edit.main is not None else list(main_track.clips)
    duration = max(c.timeline_end for c in mains)

    if edit.overlays is not None:
        tops = layout_overlays(base, edit.overlays, fps)
    else:
        tops = [
            c for t in base.video_tracks if t.role != "main" for c in t.clips if c.timeline_start < duration
        ]
    tracks = [VideoTrack(track=1, role="main", clips=mains)]
    if tops:
        tracks.append(VideoTrack(track=2, role="broll", clips=tops))

    if edit.graphics is not None:
        graphics = [
            GraphicsItem(
                id=f"g{n + 1:02d}",
                component=g.component,
                timeline_start=_snap(g.start, fps),
                timeline_end=_snap(min(g.end, duration), fps),
                layer=g.layer,
                props=g.props,
            )
            for n, g in enumerate(edit.graphics)
            if g.start < duration
        ]
    else:
        graphics = [g for g in base.graphics if g.timeline_start < duration]
        graphics = [g.model_copy(update={"timeline_end": min(g.timeline_end, duration)}) for g in graphics]

    captions = base.captions
    if edit.captions is not None:
        captions = (
            CaptionTrack(
                enabled=True,
                style=edit.captions.style,
                position=edit.captions.position,
                max_words_per_line=edit.captions.max_words_per_line,
                language=base.captions.language if base.captions else None,
            )
            if edit.captions.enabled
            else None
        )

    audio_tracks: list[AudioTrack] = []
    for track in base.audio_tracks:
        if track.role == "music" and track.clips:
            first = track.clips[0]
            asset = first.source.asset_id
            if asset is not None:
                music = Music(
                    asset_id=asset,
                    name=(names or {}).get(asset, "music"),
                    duration=durations.get(asset, first.source_out),
                )
                opts = Options(
                    width=base.sequence.width,
                    height=base.sequence.height,
                    fps=fps,
                    music_gain_db=first.gain_db,
                )
                rebuilt = music_track(music, duration, opts)
                if rebuilt is not None:
                    audio_tracks.append(rebuilt.model_copy(update={"ducking": track.ducking}))
        else:
            kept = [c for c in track.clips if c.timeline_end <= duration + 1e-6]
            if kept:
                audio_tracks.append(track.model_copy(update={"clips": kept}))

    return EditPlan(
        project_id=base.project_id,
        version=version,
        sequence=base.sequence.model_copy(update={"duration": duration}),
        video_tracks=tracks,
        audio_tracks=audio_tracks,
        graphics=graphics,
        captions=captions,
        global_effects=base.global_effects,
        notes=edit.notes,
        metadata={**base.metadata, "created_by": agent, "base_version": base.version},
    )


def summary(plan: EditPlan) -> str:
    main = next(t for t in plan.video_tracks if t.role == "main").clips
    tops = [c for t in plan.video_tracks if t.role != "main" for c in t.clips]
    transitions = [c.transition_in.type for c in main if c.transition_in and c.transition_in.type != "cut"]
    animated = sum(1 for c in main if c.keyframes)
    speed = sum(1 for c in main if c.speed != 1)
    return (
        f"v{plan.version}: {plan.sequence.duration:.1f} s, {len(main)} bo'lak, {len(tops)} ustki qatlam, "
        f"{len(transitions)} o'tish, {animated} animatsiyali, {speed} tezlik o'zgargan, {len(plan.graphics)} grafika"
    )
