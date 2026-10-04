"""Timeline → pieces: the render order of a validated EditPlan.

The timeline is cut at every point where what is on screen changes — a clip
starts or ends, a transition begins or ends, an overlay comes in or out. In
each resulting piece the set of layers is constant:

* the **main** picture: one main-track clip, or a **transition** between the
  outgoing and the incoming clip (the window where they overlap);
* zero or more **overlays** (B-roll cutaways, picture-in-picture) on top, in
  track order.

Every piece knows, for each layer, which source second plays at the piece's
first frame and how far into its item that is (for keyframes), so a piece can
be rendered on its own — memory stays flat and pieces join with the concat
demuxer exactly as single clips did.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from .models import EditPlan, Transition, VideoClip

EPS = 1e-6


@dataclass(frozen=True, slots=True)
class Slice:
    """One clip as it plays inside one piece."""

    clip: VideoClip
    source_start: float  # source second at the piece's first frame
    offset: float  # seconds into the item (keyframe time) at the piece's first frame


@dataclass(frozen=True, slots=True)
class Piece:
    start: float
    end: float
    main: Slice | None  # None: nothing on the main track here (black)
    incoming: Slice | None = None  # the clip a transition leads into
    transition: Transition | None = None
    overlays: tuple[Slice, ...] = ()

    @property
    def duration(self) -> float:
        return self.end - self.start

def _slice(clip: VideoClip, t: float) -> Slice:
    offset = t - clip.timeline_start
    return Slice(clip=clip, source_start=round(clip.source_in + offset * clip.speed, 6), offset=round(offset, 6))


def _snap(t: float, fps: int) -> float:
    return round(round(t * fps) / fps, 6)


def plan_pieces(plan: EditPlan) -> list[Piece]:
    fps = plan.sequence.fps
    duration = plan.sequence.duration
    main_track = min((t for t in plan.video_tracks if t.role == "main"), key=lambda t: t.track)
    mains = sorted(main_track.clips, key=lambda c: c.timeline_start)
    layers = sorted((t for t in plan.video_tracks if t is not main_track), key=lambda t: t.track)
    overlays = [c for t in layers for c in sorted(t.clips, key=lambda c: c.timeline_start)]

    cuts = {0.0, _snap(duration, fps)}
    for c in [*mains, *overlays]:
        cuts.update({_snap(c.timeline_start, fps), _snap(c.timeline_end, fps)})
    points = sorted(t for t in cuts if -EPS <= t <= duration + EPS)

    pieces: list[Piece] = []
    for a, b in pairwise(points):
        if b - a < 0.5 / fps:
            continue
        mid = (a + b) / 2
        active = [c for c in mains if c.timeline_start - EPS <= mid < c.timeline_end + EPS]
        main = incoming = transition = None
        if len(active) >= 2:
            out_clip, in_clip = active[0], active[1]
            main, incoming = _slice(out_clip, a), _slice(in_clip, a)
            transition = in_clip.transition_in
        elif active:
            main = _slice(active[0], a)
        tops = tuple(_slice(c, a) for c in overlays if c.timeline_start - EPS <= mid < c.timeline_end + EPS)
        pieces.append(Piece(start=a, end=b, main=main, incoming=incoming, transition=transition, overlays=tops))
    return _merge_plain(pieces)


def _merge_plain(pieces: list[Piece]) -> list[Piece]:
    """Neighbouring pieces of the same clip with nothing else changing are
    one piece (fewer FFmpeg runs, identical output)."""
    out: list[Piece] = []
    for p in pieces:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.incoming is None
            and p.incoming is None
            and prev.main is not None
            and p.main is not None
            and prev.main.clip.id == p.main.clip.id
            and [s.clip.id for s in prev.overlays] == [s.clip.id for s in p.overlays]
        ):
            out[-1] = Piece(start=prev.start, end=p.end, main=prev.main, overlays=prev.overlays)
        else:
            out.append(p)
    return out
