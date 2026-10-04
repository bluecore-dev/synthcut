"""Rule-based editing (Phase 6 without a model): material + measurements →
a validated ``EditPlan`` — what the Editor agent will later do with judgement.

The rules are an editor's first pass on talking footage:

* keep speech, cut pauses longer than ``min_pause`` (jump cuts), with a
  little air (``pad``) around every phrase;
* never use shots measured as black or frozen, or flashes under 0.4 s;
* footage without speech contributes its usable shots, a few seconds each;
* reframe to the output aspect by covering the frame and keeping the
  person — the face position from shot analysis — in view; a picture far
  narrower than the frame (vertical phone video for 16:9) is fitted over a
  blurred copy of itself instead of being cropped to a strip;
* every clip carries its automatic grade (``grade/1``) as an effect, the plan
  carries the automatic mix (``mix/1``) in ``metadata``;
* stop at the target duration on a phrase boundary.

Everything is explained in ``notes`` (Uzbek) for the owner.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from uuid import UUID

from synthcut_schemas.analysis import ClipAnalysis, Face
from synthcut_schemas.grade import ColorGrade, MixPlan
from synthcut_schemas.speech import Transcript

from .models import (
    CaptionTrack,
    EditPlan,
    EffectRef,
    GraphicsItem,
    Sequence,
    Transform,
    VideoClip,
    VideoTrack,
)

BAD_FLAGS = frozenset({"black", "frozen"})
BROLL_SKIP = BAD_FLAGS | {"duplicate"}
# A frame this many times wider than the picture would crop it to a strip.
FIT_LIMIT = 2.0
HEADROOM = 0.4  # where a face's centre sits, from the top, when cropping vertically


@dataclass(frozen=True)
class Source:
    """One video asset with everything measured about it."""

    asset_id: UUID
    name: str
    duration: float
    width: int  # display size (rotation applied)
    height: int
    transcript: Transcript | None = None
    clips: list[ClipAnalysis] = field(default_factory=list)
    grade: ColorGrade | None = None
    has_audio: bool = True


@dataclass(frozen=True)
class Options:
    width: int
    height: int
    fps: int
    target_duration: float | None = None
    remove_pauses: bool = True
    min_pause: float = 0.6
    pad: float = 0.12
    min_piece: float = 0.4
    broll_seconds: float = 3.0
    min_usable: float = 0.35
    captions: CaptionTrack | None = None
    title: str | None = None
    cta: str | None = None


@dataclass(frozen=True)
class Piece:
    source: Source
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def _merge(ranges: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(ranges):
        if out and a - out[-1][1] < gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _subtract(
    ranges: list[tuple[float, float]], holes: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    out = ranges
    for h0, h1 in holes:
        nxt: list[tuple[float, float]] = []
        for a, b in out:
            if h1 <= a or h0 >= b:
                nxt.append((a, b))
                continue
            if a < h0:
                nxt.append((a, h0))
            if h1 < b:
                nxt.append((h1, b))
        out = nxt
    return out


def speech_ranges(src: Source, opts: Options) -> list[tuple[float, float]]:
    words = src.transcript.words if src.transcript else []
    if not words:
        return []
    raw = [(w.start, w.end) for w in words if w.end > w.start]
    joined = _merge(raw, opts.min_pause if opts.remove_pauses else math.inf)
    padded = [(max(0.0, a - opts.pad), min(src.duration, b + opts.pad)) for a, b in joined]
    return _merge(padded, 0.0)


def broll_ranges(src: Source, opts: Options) -> list[tuple[float, float]]:
    """Usable shots of footage without speech: the middle ``broll_seconds``."""
    out: list[tuple[float, float]] = []
    for c in src.clips:
        if c.usable_score < opts.min_usable or BROLL_SKIP & set(c.flags) or c.duration < 1.0:
            continue
        length = min(opts.broll_seconds, c.duration)
        mid = (c.start + c.end) / 2
        out.append((mid - length / 2, mid + length / 2))
    return out


def pieces_for(src: Source, opts: Options) -> tuple[list[Piece], dict[str, float]]:
    stats = {"pauses_cut": 0.0, "bad_removed": 0.0}
    ranges = speech_ranges(src, opts)
    if not ranges:
        ranges = broll_ranges(src, opts) if src.clips else [(0.0, src.duration)]
    elif opts.remove_pauses:
        stats["pauses_cut"] = max(0.0, src.duration - sum(b - a for a, b in ranges))
    holes = [(c.start, c.end) for c in src.clips if BAD_FLAGS & set(c.flags)]
    kept = _subtract(ranges, holes)
    stats["bad_removed"] = sum(b - a for a, b in ranges) - sum(b - a for a, b in kept)
    return [Piece(src, a, b) for a, b in kept if b - a >= opts.min_piece], stats


def face_at(src: Source, at: float) -> Face | None:
    """The largest face in the shot that contains ``at``."""
    for c in src.clips:
        if c.start <= at < c.end and c.faces:
            return max(c.faces, key=lambda f: f.height)
    return None


def reframe(src: Source, opts: Options, at: float) -> tuple[Transform, list[EffectRef]]:
    """Placement in the output frame. ``scale`` 1 = cover; ``x`` / ``y`` move
    the picture's centre in output widths / heights (clamped by the renderer
    so no border shows)."""
    w, h, out_w, out_h = src.width, src.height, opts.width, opts.height
    cover = max(out_w / w, out_h / h)
    if (out_w / out_h) / (w / h) > FIT_LIMIT:
        fit = min(out_w / w, out_h / h)
        return Transform(scale=round(fit / cover, 4)), [EffectRef(type="background", params={"fill": "blur"})]
    face = face_at(src, at)
    if face is None:
        return Transform(), []
    sw, sh = w * cover, h * cover
    x = y = 0.0
    if sw > out_w + 1:
        slack = (sw - out_w) / 2 / out_w
        x = max(-slack, min(slack, -(face.x - 0.5) * sw / out_w))
    if sh > out_h + 1:
        slack = (sh - out_h) / 2 / out_h
        y = max(-slack, min(slack, ((sh - out_h) / 2 - face.y * sh + HEADROOM * out_h) / out_h))
    return Transform(x=round(x, 4), y=round(y, 4)), []


def _snap(t: float, fps: int) -> float:
    return round(round(t * fps) / fps, 6)


def placements(
    src: Source, opts: Options, start: float, end: float
) -> list[tuple[float, float, Transform, list[EffectRef]]]:
    """A phrase that runs across a cut in the source (the interview cuts to the
    audience while the voice goes on) is placed shot by shot: split at shot
    starts where the placement changes. The pieces play back to back from
    the same source, so the split itself is invisible."""
    cuts = [_snap(c.start, opts.fps) for c in src.clips if start + 0.5 < c.start < end - 0.5]
    bounds = [start, *sorted(set(cuts)), end]
    out: list[tuple[float, float, Transform, list[EffectRef]]] = []
    for a, b in pairwise(bounds):
        transform, effects = reframe(src, opts, (a + b) / 2)
        if out and (out[-1][2], out[-1][3]) == (transform, effects):
            out[-1] = (out[-1][0], b, transform, effects)  # same placement: one clip
        else:
            out.append((a, b, transform, effects))
    return out


def build_plan(
    *,
    project_id: UUID,
    version: int,
    sources: list[Source],
    opts: Options,
    mix: MixPlan | None = None,
    noise_floor_db: float | None = None,
) -> EditPlan:
    pieces: list[Piece] = []
    pauses = bad = 0.0
    for src in sources:
        got, stats = pieces_for(src, opts)
        pieces.extend(got)
        pauses += stats["pauses_cut"]
        bad += stats["bad_removed"]
    if not pieces:
        raise ValueError("Montaj uchun yaroqli bo'lak topilmadi")

    clips: list[VideoClip] = []
    t = 0.0
    trimmed = False
    for n, p in enumerate(pieces):
        start, end = _snap(p.start, opts.fps), _snap(p.end, opts.fps)
        length = end - start
        if length < 1 / opts.fps:
            continue
        if opts.target_duration and t + length > opts.target_duration + 1e-6:
            if t >= opts.target_duration * 0.6:  # stop on a phrase boundary
                trimmed = True
                break
            end = _snap(start + (opts.target_duration - t), opts.fps)
            length = end - start
            trimmed = True
        for k, (a, b, transform, effects) in enumerate(placements(p.source, opts, start, end)):
            if p.source.grade:
                effects = [*effects, EffectRef(type="grade", params=p.source.grade.model_dump(mode="json"))]
            clips.append(
                VideoClip(
                    id=f"c{n + 1:03d}" + (f"-{k + 1}" if k else ""),
                    asset_id=p.source.asset_id,
                    source_in=a,
                    source_out=b,
                    timeline_start=round(t + a - start, 6),
                    timeline_end=round(t + b - start, 6),
                    transform=transform,
                    effects=effects,
                    mute_source_audio=not p.source.has_audio,
                )
            )
        t = round(t + length, 6)
        if trimmed:
            break
    duration = t
    graphics: list[GraphicsItem] = []
    if opts.title and duration >= 3:
        graphics.append(
            GraphicsItem(
                id="title",
                component="TitleCard",
                timeline_start=0,
                timeline_end=_snap(min(3.0, duration / 3), opts.fps),
                props={"title": opts.title[:60], "variant": "lower_third"},
            )
        )
    if opts.cta and duration >= 6:
        graphics.append(
            GraphicsItem(
                id="cta",
                component="CTA",
                timeline_start=_snap(duration - 3.0, opts.fps),
                timeline_end=duration,
                layer=2,
                props={"text": opts.cta[:40], "action": "subscribe"},
            )
        )
    notes = [f"{len({c.asset_id for c in clips})} ta fayldan {len(clips)} ta bo'lak, jami {duration:.1f} s"]
    if pauses >= 0.5:
        notes.append(f"Pauzalar kesildi: {pauses:.1f} s")
    if bad >= 0.1:
        notes.append(f"Yaroqsiz kadrlar (qora / qotgan) olib tashlandi: {bad:.1f} s")
    if any(c.transform.x or c.transform.y for c in clips):
        notes.append(f"{opts.width}×{opts.height} formatga yuz kadrda qoladigan qilib kesildi")
    if any(e.type == "background" for c in clips for e in c.effects):
        notes.append("Tik video gorizontal kadrga xiralashtirilgan fon ustida joylandi")
    if trimmed and opts.target_duration:
        notes.append(f"Maqsadli davomiylik {opts.target_duration:.0f} s — qolgan qism kiritilmadi")
    return EditPlan(
        project_id=project_id,
        version=version,
        sequence=Sequence(fps=opts.fps, width=opts.width, height=opts.height, duration=duration),
        video_tracks=[VideoTrack(track=1, role="main", clips=clips)],
        graphics=graphics,
        captions=opts.captions,
        notes="\n".join(notes),
        metadata={
            "created_by": "rules",
            "mix": mix.model_dump(mode="json") if mix else None,
            "noise_floor_db": noise_floor_db,
        },
    )
