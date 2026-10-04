"""One piece of the timeline → one FFmpeg run (see ``synthcut_timeline.pieces``).

A piece has a constant set of layers, so its graph is fixed:

* the **main** picture — one source placed in the frame (cover / fit /
  blurred fill as before), optionally **zooming and panning** along keyframes
  (``perspective`` with per-frame expressions: sub-pixel smooth, unlike
  ``zoompan``), optionally **sped up or slowed down** (``setpts`` /
  ``atempo``); or a **transition** between two such sources (``xfade`` for
  the picture, ``acrossfade`` for the sound);
* **overlays** on top in order — B-roll cutaways and picture-in-picture —
  sized relative to covering the frame, positioned (keyframes allowed),
  faded in / out, with or without their own sound;
* exact output: ``round(d·fps)`` frames, ``d·48000`` samples, the same
  near-lossless intermediate as a plain segment, so pieces concat as before.

Keyframe times are piece-local seconds; the caller converts item time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from .final import (
    BASE,
    RATE,
    TAGS_709,
    TO_709,
    SegmentSpec,
    _even,
    colour_filters,
    cover_filters,
    frames_for,
    intermediate_preset,
    video_graph,
)

TRANSITIONS = {
    "crossfade": "fade",
    "dip_to_black": "fadeblack",
    "dip_to_white": "fadewhite",
    "whip": "slideleft",
    "zoom": "zoomin",
}

EASING = {
    "linear": "{p}",
    "ease_in": "{p}*{p}",
    "ease_out": "(1-(1-{p})*(1-{p}))",
    "ease_in_out": "({p}*{p}*(3-2*{p}))",
    "hold": "0",
}


class UnsupportedAnimation(ValueError):
    """An animation this renderer cannot execute; refused, never approximated silently."""


@dataclass(frozen=True, slots=True)
class Key:
    t: float  # piece-local seconds
    value: float
    easing: str = "ease_in_out"  # how the value travels to the next key


def curve(keys: list[Key], var: str, default: float) -> str:
    """A piecewise expression of ``var`` (seconds) through the keyframes:
    held before the first and after the last, eased in between."""
    if not keys:
        return f"{default:g}"
    ks = sorted(keys, key=lambda k: k.t)
    expr = f"{ks[-1].value:g}"
    for a, b in reversed(list(pairwise(ks))):
        span = max(b.t - a.t, 1e-6)
        p = f"(({var}-{a.t:g})/{span:g})"
        eased = EASING.get(a.easing, EASING["ease_in_out"]).format(p=p)
        expr = f"if(lt({var},{b.t:g}),({a.value:g}+({b.value - a.value:g})*{eased}),{expr})"
    return f"if(lt({var},{ks[0].t:g}),{ks[0].value:g},{expr})"


def value_at(keys: list[Key], t: float, default: float) -> float:
    if not keys:
        return default
    ks = sorted(keys, key=lambda k: k.t)
    if t <= ks[0].t:
        return ks[0].value
    for a, b in pairwise(ks):
        if t < b.t:
            p = (t - a.t) / max(b.t - a.t, 1e-6)
            e = {"linear": p, "ease_in": p * p, "ease_out": 1 - (1 - p) ** 2, "hold": 0.0}.get(
                a.easing, p * p * (3 - 2 * p)
            )
            return a.value + (b.value - a.value) * e
    return ks[-1].value


@dataclass(frozen=True, slots=True)
class Layer:
    source: str
    start: float  # source second at the piece's first frame
    src_w: int  # display size of the source
    src_h: int
    speed: float = 1.0
    color_profile: str | None = None
    bit_depth: int | None = None
    lut: Path | None = None
    gamut_in_lut: bool = False
    fill: str = "black"
    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0  # degrees, static
    opacity: float = 1.0
    crop: tuple[float, float, float, float] | None = None  # left, right, top, bottom (fractions)
    keys: dict[str, list[Key]] = field(default_factory=dict)  # scale / x / y / opacity / volume_db
    audio: bool = True
    gain_db: float = 0.0


@dataclass(frozen=True, slots=True)
class PieceSpec:
    duration: float
    main: Layer | None  # None: black
    incoming: Layer | None = None
    transition: str | None = None  # EditPlan transition type
    overlays: tuple[Layer, ...] = ()


def _speed_pre(layer: Layer) -> list[str]:
    pre = []
    if layer.speed != 1.0:
        pre.append(f"setpts=(PTS-STARTPTS)/{layer.speed:g}")
    if layer.crop is not None:
        left, right, top, bottom = layer.crop
        pre.append(f"crop=iw*{1 - left - right:g}:ih*{1 - top - bottom:g}:iw*{left:g}:ih*{top:g}")
    return pre


def _cropped(layer: Layer) -> tuple[int, int]:
    if layer.crop is None:
        return layer.src_w, layer.src_h
    left, right, top, bottom = layer.crop
    return _even(layer.src_w * (1 - left - right)), _even(layer.src_h * (1 - top - bottom))


def _grade_tail(layer: Layer, *, zscale: bool, alpha: bool) -> list[str]:
    tail = colour_filters(
        layer.color_profile, zscale=zscale, gamut_in_lut=layer.gamut_in_lut and layer.lut is not None
    )
    if layer.lut is not None:
        rgb = "gbrp16le" if (layer.bit_depth or 8) > 8 else "gbrp"
        tail += [f"format={rgb}", f"lut3d=file={layer.lut}:interp=tetrahedral"]
    tail += [TO_709, "format=yuva420p" if alpha else "format=yuv420p", "setsar=1"]
    return tail


def _opacity(layer: Layer, duration: float, *, alpha: bool) -> list[str]:
    """Constant opacity times a fade in from 0 and / or out to 0 — the
    animations an editor makes with opacity. Other curves are refused."""
    keys = sorted(layer.keys.get("opacity", []), key=lambda k: k.t)
    out: list[str] = []
    if keys:
        peak = max(k.value for k in keys)
        inner = [k for k in keys if 0 < k.value < peak - 1e-6]
        if inner or len(keys) > 4:
            raise UnsupportedAnimation(
                "Shaffoflik faqat paydo bo'lish / yo'qolish ko'rinishida animatsiya qilinadi"
            )
        if keys[0].value == 0 and len(keys) > 1:
            out.append(
                f"fade=t=in:st={max(0.0, keys[0].t):g}:d={max(1e-3, keys[1].t - keys[0].t):g}:alpha={int(alpha)}"
            )
        if keys[-1].value == 0 and len(keys) > 1:
            out.append(
                f"fade=t=out:st={max(0.0, keys[-2].t):g}:d={max(1e-3, keys[-1].t - keys[-2].t):g}:alpha={int(alpha)}"
            )
        base = peak * layer.opacity
    else:
        base = layer.opacity
    if base < 1.0:
        out.append(
            f"lut=a='val*{base:g}'"
            if alpha
            else f"lutyuv=y='val*{base:g}':u='128+(val-128)*{base:g}':v='128+(val-128)*{base:g}'"
        )
    return out


def main_video(
    layer: Layer, src: str, out: str, *, width: int, height: int, fps: int, zscale: bool, duration: float
) -> str:
    """The frame-filling picture of a piece, ending in exact-length yuv420p."""
    animated = any(layer.keys.get(k) for k in ("scale", "x", "y"))
    tail_fx = _opacity(layer, duration, alpha=False)
    if not animated and layer.rotation == 0:
        spec = SegmentSpec(
            source=layer.source, start=layer.start, duration=duration, src_w=_cropped(layer)[0],
            src_h=_cropped(layer)[1], color_profile=layer.color_profile, bit_depth=layer.bit_depth,
            scale=layer.scale, x=layer.x, y=layer.y, lut=layer.lut, fill=layer.fill, gamut_in_lut=layer.gamut_in_lut,
        )  # fmt: skip
        raw = f"[{out.strip('[]')}raw]"
        graph = video_graph(
            spec,
            width=width,
            height=height,
            fps=fps,
            zscale=zscale,
            src=src,
            out=raw,
            pre=tuple(_speed_pre(layer)),
        )
        return graph + f";{raw}{','.join(['null', *tail_fx])}{out}"
    ew, eh = _cropped(layer)
    cover = max(width / ew, height / eh)
    t = f"(on/{fps})"
    scale = curve(layer.keys.get("scale", []), t, layer.scale)
    if any(k.value < 1.0 for k in layer.keys.get("scale", [])) or layer.scale < 1.0:
        raise UnsupportedAnimation(
            "Kadr ichidagi zoom 100% dan kichik bo'lolmaydi (chegaralar paydo bo'ladi)"
        )
    xs = curve(layer.keys.get("x", []), t, layer.x)
    ys = curve(layer.keys.get("y", []), t, layer.y)
    s = f"({cover:.6f}*({scale}))"
    win_w, win_h = f"({width}/{s})", f"({height}/{s})"
    cx = f"clip(({ew}-{win_w})/2-({xs})*{width}/{s},0,{ew}-{win_w})"
    cy = f"clip(({eh}-{win_h})/2-({ys})*{height}/{s},0,{eh}-{win_h})"
    corners = {
        "x0": cx, "y0": cy, "x1": f"{cx}+{win_w}", "y1": cy,
        "x2": cx, "y2": f"{cy}+{win_h}", "x3": f"{cx}+{win_w}", "y3": f"{cy}+{win_h}",
    }  # fmt: skip
    persp = (
        "perspective="
        + ":".join(f"{k}='{v}'" for k, v in corners.items())
        + ":interpolation=linear:sense=source:eval=frame"
    )
    chain = [*_speed_pre(layer), f"fps={fps}", persp, f"scale={width}:{height}:flags=lanczos"]
    if layer.rotation:
        chain.append(f"rotate={layer.rotation:g}*PI/180:fillcolor=black")
    chain += _grade_tail(layer, zscale=zscale, alpha=False)
    chain += [*tail_fx, "tpad=stop_mode=clone:stop_duration=1"]
    return f"{src}{','.join(chain)}{out}"


def overlay_video(
    layer: Layer, src: str, out: str, *, width: int, height: int, fps: int, zscale: bool, duration: float
) -> tuple[str, str, str]:
    """(graph, x expression, y expression) of a layer drawn over the picture.
    ``scale`` is relative to covering the frame (1 = a full-frame cutaway)."""
    if layer.keys.get("scale"):
        raise UnsupportedAnimation(
            "Ustki qatlam o'lchami hozircha animatsiya qilinmaydi — joyi va shaffofligi qilinadi"
        )
    ew, eh = _cropped(layer)
    cover = max(width / ew, height / eh) * layer.scale
    ow, oh = _even(ew * cover), _even(eh * cover)
    chain = [*_speed_pre(layer), f"fps={fps}", f"scale={ow}:{oh}:flags=lanczos"]
    chain += _grade_tail(layer, zscale=zscale, alpha=True)
    if layer.rotation:  # after the grade: the corners it uncovers stay transparent
        a = f"{layer.rotation:g}*PI/180"
        chain.append(f"rotate={a}:ow=rotw({a}):oh=roth({a}):fillcolor=none")
    chain += [*_opacity(layer, duration, alpha=True), "tpad=stop_mode=clone:stop_duration=1"]
    xs, ys = curve(layer.keys.get("x", []), "t", layer.x), curve(layer.keys.get("y", []), "t", layer.y)
    return f"{src}{','.join(chain)}{out}", f"(W-w)/2+({xs})*W", f"(H-h)/2+({ys})*H"


def _atempo(speed: float) -> list[str]:
    out: list[str] = []
    s = speed
    while s > 2.0:
        out.append("atempo=2")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        out.append(f"atempo={s:.6f}")
    return out


def _layer_audio(layer: Layer, src: str, out: str, samples: int) -> str:
    chain = [
        "asetpts=PTS-STARTPTS",
        *_atempo(layer.speed),
        f"aresample={RATE}",
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
    ]
    if layer.gain_db:
        chain.append(f"volume={layer.gain_db:g}dB")
    if layer.keys.get("volume_db"):
        chain.append(f"volume='pow(10,({curve(layer.keys['volume_db'], 't', 0.0)})/20)':eval=frame")
    chain.append(f"apad=whole_len={samples},atrim=end_sample={samples}")
    return f"{src}{','.join(chain)}{out}"


def piece_command(
    spec: PieceSpec, out: Path, *, width: int, height: int, fps: int, zscale: bool, threads: int = 2
) -> list[str]:
    n = frames_for(spec.duration, fps)
    exact = n / fps
    samples = round(exact * RATE)
    args = [*BASE, "-loglevel", "error", "-threads", str(threads)]
    graph: list[str] = []
    audio: list[str] = []
    index = 0

    def add_input(layer: Layer) -> int:
        nonlocal index
        read = exact * layer.speed + 2 / fps + 0.1
        args.extend(["-ss", f"{layer.start:.6f}", "-t", f"{read:.6f}", "-i", layer.source])
        index += 1
        return index - 1

    kw = {"width": width, "height": height, "fps": fps, "zscale": zscale, "duration": exact}
    if spec.main is None:
        args += ["-f", "lavfi", "-t", f"{exact + 1:.6f}", "-i", f"color=c=black:s={width}x{height}:r={fps}"]
        graph.append(f"[{index}:v]format=yuv420p,setsar=1[base]")
        index += 1
    else:
        a = add_input(spec.main)
        if spec.incoming is not None:
            b = add_input(spec.incoming)
            graph.append(main_video(spec.main, f"[{a}:v:0]", "[va]", **kw))
            graph.append(main_video(spec.incoming, f"[{b}:v:0]", "[vb]", **kw))
            kind = TRANSITIONS.get(spec.transition or "crossfade", "fade")
            graph.append(f"[va][vb]xfade=transition={kind}:duration={exact:.6f}:offset=0[base]")
            if spec.main.audio and spec.incoming.audio:
                graph.append(_layer_audio(spec.main, f"[{a}:a:0]", "[aa]", samples))
                graph.append(_layer_audio(spec.incoming, f"[{b}:a:0]", "[ab]", samples))
                graph.append(f"[aa][ab]acrossfade=d={exact:.6f}:c1=tri:c2=tri[amain]")
                audio.append("[amain]")
            else:
                for idx, layer, label in ((a, spec.main, "[aa]"), (b, spec.incoming, "[ab]")):
                    if layer.audio:
                        graph.append(_layer_audio(layer, f"[{idx}:a:0]", label, samples))
                        audio.append(label)
        else:
            graph.append(main_video(spec.main, f"[{a}:v:0]", "[base]", **kw))
            if spec.main.audio:
                graph.append(_layer_audio(spec.main, f"[{a}:a:0]", "[amain]", samples))
                audio.append("[amain]")

    base = "[base]"
    for i, layer in enumerate(spec.overlays):
        k = add_input(layer)
        chain, x, y = overlay_video(layer, f"[{k}:v:0]", f"[ov{i}]", **kw)
        graph.append(chain)
        graph.append(
            f"{base}[ov{i}]overlay=x='{x}':y='{y}':eval=frame:format=yuv420:eof_action=pass[base{i}]"
        )
        base = f"[base{i}]"
        if layer.audio:
            graph.append(_layer_audio(layer, f"[{k}:a:0]", f"[ao{i}]", samples))
            audio.append(f"[ao{i}]")
    graph.append(f"{base}format=yuv420p,setsar=1,tpad=stop_mode=clone:stop_duration=1[v]")

    if not audio:
        args += ["-f", "lavfi", "-t", f"{exact:.6f}", "-i", f"anullsrc=r={RATE}:cl=stereo"]
        graph.append(
            f"[{index}:a]aformat=sample_fmts=s16:channel_layouts=stereo,apad=whole_len={samples},atrim=end_sample={samples}[a]"
        )
    elif len(audio) == 1:
        graph.append(f"{audio[0]}aformat=sample_fmts=s16:channel_layouts=stereo[a]")
    else:
        graph.append(
            f"{''.join(audio)}amix=inputs={len(audio)}:normalize=0:duration=first,aformat=sample_fmts=s16:channel_layouts=stereo[a]"
        )

    args += [
        "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
        "-frames:v", str(n),
        "-c:v", "libx264", "-preset", intermediate_preset(width, height), "-crf", "12", "-pix_fmt", "yuv420p",
        "-g", str(fps), "-threads", str(threads), *TAGS_709,
        "-c:a", "pcm_s16le", "-ar", str(RATE),
        "-progress", "pipe:1", "-nostats", "-f", "matroska", str(out),
    ]  # fmt: skip
    return args


__all__ = [
    "TRANSITIONS",
    "Key",
    "Layer",
    "PieceSpec",
    "UnsupportedAnimation",
    "cover_filters",
    "curve",
    "piece_command",
    "value_at",
]
