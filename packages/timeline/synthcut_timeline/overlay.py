"""EditPlan → what the Remotion overlay renders (spec §20, rule 19).

Remotion draws only the motion layer — graphics and captions on a transparent
background, frame-addressed. FFmpeg composites that layer over the picture.
This module turns a validated plan (seconds, asset ids) into ``overlay/1``
(frames, normalised props, caption lines on the *output* timeline), so the
React side never interprets the plan itself.

Captions come from ``transcript/1`` words mapped through the main track: a
word spoken at source time *s* inside a clip ``[source_in, source_out)`` lands
at ``timeline_start + (s - source_in) / speed``. Words cut out of the edit
disappear from the captions by construction.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from synthcut_schemas.speech import Transcript

from .models import CaptionTrack, EditPlan
from .registry import GRAPHICS_REGISTRY

SCHEMA_VERSION = "overlay/1"
SENTENCE_END = (".", "?", "!", "…")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class SafeZone(_Out):
    """Insets (fractions of the frame) that platform UI covers: on 9:16 the
    caption must clear the like/comment column and the description."""

    top: float
    bottom: float
    left: float
    right: float


class Theme(_Out):
    primary: str = "#1A4F8A"
    accent: str = "#00C4FF"
    text: str = "#FFFFFF"
    highlight: str = "#FFD60A"
    font: Literal["Inter", "Montserrat"] = "Montserrat"


class OverlayWord(_Out):
    text: str
    start: float  # seconds on the output timeline
    end: float


class CaptionLine(_Out):
    start: float
    end: float
    words: list[OverlayWord]


class CaptionsOverlay(_Out):
    style: Literal["dynamic", "karaoke", "minimal", "bold"]
    position: Literal["bottom", "center", "top"]
    lines: list[CaptionLine]


class OverlayItem(_Out):
    id: str
    component: str
    from_frame: int
    duration_frames: int
    layer: int
    props: dict[str, Any]


class OverlayProps(_Out):
    schema_version: Literal["overlay/1"] = SCHEMA_VERSION
    width: int
    height: int
    fps: int
    duration_in_frames: int
    safe_zone: SafeZone
    theme: Theme = Field(default_factory=Theme)
    items: list[OverlayItem] = Field(default_factory=list)
    captions: CaptionsOverlay | None = None
    # asset id -> short-lived image URL, filled by the render job for widgets
    # that show an asset (DocumentCard, LogoReveal, PhoneMockup).
    assets: dict[str, str] = Field(default_factory=dict)


def safe_zone(width: int, height: int) -> SafeZone:
    ratio = width / height
    if ratio < 0.7:  # 9:16 — Reels / TikTok / Shorts UI
        return SafeZone(top=0.10, bottom=0.22, left=0.06, right=0.14)
    if ratio < 1.1:  # 1:1, 4:5 — feed posts
        return SafeZone(top=0.06, bottom=0.12, left=0.06, right=0.06)
    return SafeZone(top=0.06, bottom=0.08, left=0.06, right=0.06)  # 16:9


def timeline_words(plan: EditPlan, transcripts: dict[UUID, Transcript]) -> list[tuple[int, OverlayWord]]:
    """(clip number, word) on the output timeline, in order."""
    main = next((t for t in plan.video_tracks if t.role == "main"), None)
    if main is None:
        return []
    out: list[tuple[int, OverlayWord]] = []
    for n, clip in enumerate(sorted(main.clips, key=lambda c: c.timeline_start)):
        transcript = transcripts.get(clip.asset_id)
        if transcript is None:
            continue
        for w in transcript.words:
            mid = (w.start + w.end) / 2
            if not clip.source_in <= mid < clip.source_out:
                continue  # a word belongs to the clip that shows most of it
            s = max(w.start, clip.source_in)
            e = min(w.end, clip.source_out)
            t0 = clip.timeline_start + (s - clip.source_in) / clip.speed
            t1 = clip.timeline_start + (e - clip.source_in) / clip.speed
            out.append((n, OverlayWord(text=w.word, start=round(t0, 3), end=round(max(t1, t0), 3))))
    return out


def caption_lines(
    plan: EditPlan,
    transcripts: dict[UUID, Transcript],
    settings: CaptionTrack,
    *,
    max_line_seconds: float = 3.0,
    pause: float = 0.6,
    min_seconds: float = 0.6,
) -> list[CaptionLine]:
    """Short lines for social video: at most ``max_words_per_line`` words,
    broken at sentence ends, pauses and cuts, so a line never spans a cut."""
    lines: list[list[OverlayWord]] = []
    current: list[OverlayWord] = []
    current_clip: int | None = None
    for clip_no, w in timeline_words(plan, transcripts):
        if current:
            last = current[-1]
            if (
                len(current) >= settings.max_words_per_line
                or clip_no != current_clip
                or w.start - last.end >= pause
                or w.end - current[0].start > max_line_seconds
                or last.text.endswith(SENTENCE_END)
            ):
                lines.append(current)
                current = []
        current.append(w)
        current_clip = clip_no
    if current:
        lines.append(current)

    out: list[CaptionLine] = []
    for i, words in enumerate(lines):
        start, end = words[0].start, words[-1].end
        if end - start < min_seconds:  # hold a short line long enough to read, never over the next
            limit = lines[i + 1][0].start - 0.02 if i + 1 < len(lines) else plan.sequence.duration
            end = max(end, min(start + min_seconds, limit))
        out.append(
            CaptionLine(start=round(start, 3), end=round(min(end, plan.sequence.duration), 3), words=words)
        )
    return out


def build_overlay(
    plan: EditPlan, transcripts: dict[UUID, Transcript] | None = None, *, theme: Theme | None = None
) -> OverlayProps:
    """``plan`` must already have passed ``validate_plan`` (props are re-parsed
    here only to fill in defaults, so the React side needs none)."""
    fps = plan.sequence.fps
    items: list[OverlayItem] = []
    for g in sorted(plan.graphics, key=lambda g: (g.layer, g.timeline_start)):
        spec = GRAPHICS_REGISTRY[g.component]
        props = (
            spec.props_model.model_validate(g.props).model_dump(mode="json") if spec.props_model else g.props
        )
        start = round(g.timeline_start * fps)
        items.append(
            OverlayItem(
                id=g.id,
                component=g.component,
                from_frame=start,
                duration_frames=max(1, round(g.timeline_end * fps) - start),
                layer=g.layer,
                props=props,
            )
        )
    captions = None
    if plan.captions is not None and plan.captions.enabled and transcripts:
        captions = CaptionsOverlay(
            style=plan.captions.style,
            position=plan.captions.position,
            lines=caption_lines(plan, transcripts, plan.captions),
        )
    return OverlayProps(
        width=plan.sequence.width,
        height=plan.sequence.height,
        fps=fps,
        duration_in_frames=max(1, round(plan.sequence.duration * fps)),
        safe_zone=safe_zone(plan.sequence.width, plan.sequence.height),
        theme=theme or Theme(),
        items=items,
        captions=captions,
    )


def sfx_cues(plan: EditPlan) -> list[tuple[float, str]]:
    """(timeline second, library id) for every component that enters with a
    sound — becomes the plan's sfx track unless the plan already has one."""
    cues: list[tuple[float, str]] = []
    for g in plan.graphics:
        spec = GRAPHICS_REGISTRY.get(g.component)
        if spec is None or spec.sfx is None or g.props.get("enter") == "none":
            continue
        cues.append((round(g.timeline_start, 3), spec.sfx))
    return sorted(cues)
