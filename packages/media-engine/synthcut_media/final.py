"""Final render (spec §27-29, Phase 11): FFmpeg commands that execute a
validated EditPlan from the *originals* — never from proxies.

The render is done in two steps, so memory stays flat however long the
timeline is and every step reports progress:

1. **Segments** — one FFmpeg run per clip: seek into the original, convert
   its colour to Rec.709 (tone-map HDR, map wide gamut), cover-scale and crop
   to the output frame where the plan placed it, apply the clip's grade as a
   3D LUT, conform the frame rate, and cut exactly ``round(d × fps)`` frames
   and ``d × 48000`` samples. Intermediates are near-lossless (x264 CRF 12,
   PCM), so the final encode is the only real generation.
2. **Master** — the concat demuxer joins the segments; one graph lays the
   motion layer (Remotion PNG frames) over the picture, runs the voice chain,
   mixes the sound effects, normalises loudness (second ``loudnorm`` pass) and
   encodes the delivery file for the preset.

Every command is an argument list; URLs and paths never reach a shell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .commands import TONEMAP_PROFILES

RATE = 48000
BASE = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
TO_709 = "scale=out_color_matrix=bt709:out_range=tv"
TAGS_709 = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def _even(x: float) -> int:
    return max(2, round(x / 2) * 2)


def _clamp(v: float, lo: float, hi: float) -> int:
    return int(max(lo, min(hi, round(v))))


def cover_filters(
    src_w: int, src_h: int, out_w: int, out_h: int, *, scale: float = 1.0, x: float = 0.0, y: float = 0.0
) -> list[str]:
    """Scale so the source covers the output frame (``scale`` > 1 zooms in,
    < 1 leaves borders), then crop the output window. ``x`` / ``y`` move the
    picture's centre by that many output widths / heights, clamped so the
    frame is never left empty where the source could fill it."""
    s = max(out_w / src_w, out_h / src_h) * scale
    sw, sh = _even(src_w * s), _even(src_h * s)
    if scale >= 1.0:
        sw, sh = max(sw, out_w), max(sh, out_h)
    filters = [f"scale={sw}:{sh}:flags=lanczos"]
    cw, ch = min(sw, out_w), min(sh, out_h)
    cx = _clamp((sw - cw) / 2 - x * out_w, 0, sw - cw)
    cy = _clamp((sh - ch) / 2 - y * out_h, 0, sh - ch)
    if (cw, ch) != (sw, sh):
        filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
    if (cw, ch) != (out_w, out_h):
        px = _clamp((out_w - cw) / 2 + x * out_w, 0, out_w - cw)
        py = _clamp((out_h - ch) / 2 + y * out_h, 0, out_h - ch)
        filters.append(f"pad={out_w}:{out_h}:{px}:{py}:black")
    return filters


def colour_filters(profile: str | None, *, zscale: bool, gamut_in_lut: bool = False) -> list[str]:
    """Source colour → Rec.709, the same decisions ingestion made for the
    proxy (so a grade measured on the proxy fits the original). Log stays
    flat here: its transform is part of the clip's grade LUT — and so is the
    wide-gamut SDR matrix when ``gamut_in_lut`` (a float zscale pass per
    frame costs more than the whole LUT)."""
    if not zscale or (gamut_in_lut and profile in ("display_p3", "rec2020_sdr")):
        return []
    if profile in TONEMAP_PROFILES:
        return [
            "zscale=t=linear:npl=100",
            "format=gbrpf32le",
            "zscale=p=bt709",
            "tonemap=tonemap=hable:desat=0",
            "zscale=t=bt709:m=bt709:r=tv",
        ]
    if profile in ("display_p3", "rec2020_sdr"):
        return ["zscale=p=bt709:t=bt709:m=bt709:r=tv"]
    return []


@dataclass(frozen=True, slots=True)
class SegmentSpec:
    source: str  # internal URL of the original
    start: float  # seconds into the source
    duration: float  # timeline seconds (frame-aligned)
    src_w: int  # display size (rotation applied by FFmpeg's autorotate)
    src_h: int
    color_profile: str | None = None
    bit_depth: int | None = None
    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0
    lut: Path | None = None
    audio: bool = True  # False: silence (no audio stream, or the plan mutes it)
    fill: str = "black"  # what shows around a picture smaller than the frame: "black" | "blur"
    gamut_in_lut: bool = False  # the LUT converts wide-gamut SDR to Rec.709 itself


def frames_for(duration: float, fps: int) -> int:
    return max(1, round(duration * fps))


def video_graph(spec: SegmentSpec, *, width: int, height: int, fps: int, zscale: bool) -> str:
    """``[0:v:0]`` → ``[v]``: placement, colour, grade, exact frames."""
    tail = colour_filters(
        spec.color_profile, zscale=zscale, gamut_in_lut=spec.gamut_in_lut and spec.lut is not None
    )
    if spec.lut is not None:
        rgb = "gbrp16le" if (spec.bit_depth or 8) > 8 else "gbrp"
        tail += [f"format={rgb}", f"lut3d=file={spec.lut}:interp=tetrahedral"]
    # Clone the last frame if the source ends early: the segment must be exact.
    tail += [TO_709, "format=yuv420p", "setsar=1", "tpad=stop_mode=clone:stop_duration=1"]
    place = cover_filters(spec.src_w, spec.src_h, width, height, scale=spec.scale, x=spec.x, y=spec.y)
    if spec.fill == "blur" and spec.scale < 1.0:
        # The picture fitted over a blurred, slightly darker copy of itself
        # (blurred at 1/8 size: the same look for a fraction of the work).
        small_w, small_h = _even(width / 8), _even(height / 8)
        background = cover_filters(spec.src_w, spec.src_h, small_w, small_h)
        background += [
            "boxblur=6:2",
            "eq=brightness=-0.06:saturation=0.85",
            f"scale={width}:{height}:flags=bicubic",
        ]
        picture = place[:-1] if place[-1].startswith("pad=") else place
        return (
            f"[0:v:0]fps={fps},split=2[bgsrc][fgsrc];"
            f"[bgsrc]{','.join(background)}[bg];"
            f"[fgsrc]{','.join(picture)}[fg];"
            f"[bg][fg]overlay=x='(W-w)/2+({spec.x:g})*W':y='(H-h)/2+({spec.y:g})*H',{','.join(tail)}[v]"
        )
    return f"[0:v:0]{','.join([f'fps={fps}', *place, *tail])}[v]"


def segment_command(
    spec: SegmentSpec, out: Path, *, width: int, height: int, fps: int, zscale: bool, threads: int = 2
) -> list[str]:
    n = frames_for(spec.duration, fps)
    exact = n / fps
    samples = round(exact * RATE)
    # A little more than needed is read, so the last frame is never short.
    read = f"{exact + 2 / fps:.6f}"
    args = [*BASE, "-loglevel", "error", "-threads", str(threads)]
    args += ["-ss", f"{spec.start:.6f}", "-t", read, "-i", spec.source]
    if not spec.audio:
        args += ["-f", "lavfi", "-t", f"{exact:.6f}", "-i", f"anullsrc=r={RATE}:cl=stereo"]
    audio_in = "1:a" if not spec.audio else "0:a:0"
    graph = (
        video_graph(spec, width=width, height=height, fps=fps, zscale=zscale) + ";"
        f"[{audio_in}]aresample={RATE},aformat=sample_fmts=s16:channel_layouts=stereo,"
        f"apad=whole_len={samples},atrim=end_sample={samples}[a]"
    )
    args += [
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-frames:v", str(n),
        "-c:v", "libx264", "-preset", intermediate_preset(width, height), "-crf", "12", "-pix_fmt", "yuv420p",
        "-g", str(fps), "-threads", str(threads), *TAGS_709,
        "-c:a", "pcm_s16le", "-ar", str(RATE),
        "-progress", "pipe:1", "-nostats", "-f", "matroska", str(out),
    ]  # fmt: skip
    return args


def concat_list(segments: list[tuple[Path, float]], out: Path, fps: int) -> Path:
    """Concat demuxer script with each segment's exact length, so timestamps
    stay on the frame grid however many cuts there are."""
    lines = ["ffconcat version 1.0"]
    for path, duration in segments:
        lines.append(f"file '{path.as_posix()}'")
        lines.append(f"duration {frames_for(duration, fps) / fps:.6f}")
    out.write_text("\n".join(lines) + "\n")
    return out


@dataclass(frozen=True, slots=True)
class SfxInput:
    path: Path
    at: float  # timeline seconds
    gain_db: float = -8.0


def audio_graph(voice: list[str], sfx: list[SfxInput], *, first_sfx_input: int, tail: str) -> str:
    """``[0:a]`` through the voice chain, sound effects mixed in at their
    times, then ``tail`` (the loudnorm measuring or applying filter) → ``[a]``."""
    chain = ",".join(voice) if voice else "anull"
    parts = [f"[0:a]{chain}[voice]"]
    labels = ["[voice]"]
    for i, cue in enumerate(sfx):
        delay = max(0, round(cue.at * 1000))
        parts.append(
            f"[{first_sfx_input + i}:a]aresample={RATE},aformat=channel_layouts=stereo,"
            f"volume={cue.gain_db:g}dB,adelay={delay}:all=1[s{i}]"
        )
        labels.append(f"[s{i}]")
    if sfx:
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first[pre]")
        parts.append(f"[pre]{tail},aresample={RATE}[a]")
    else:
        parts[0] = f"[0:a]{chain},{tail},aresample={RATE}[a]"
    return ";".join(parts)


def sfx_inputs(sfx: list[SfxInput]) -> list[str]:
    args: list[str] = []
    for cue in sfx:
        args += ["-i", str(cue.path)]
    return args


def loudness_pass(concat: Path, sfx: list[SfxInput], voice: list[str], measure: str) -> list[str]:
    graph = audio_graph(voice, sfx, first_sfx_input=1, tail=measure)
    return [
        *BASE, "-nostats", "-f", "concat", "-safe", "0", "-i", str(concat), *sfx_inputs(sfx),
        "-filter_complex", graph, "-map", "[a]", "-vn", "-f", "null", "-",
    ]  # fmt: skip


@dataclass(frozen=True, slots=True)
class Encoding:
    x264_preset: str
    crf: int
    audio_bitrate: str = "192k"


HD = 1920 * 1080 * 1.1


def encoding_for(width: int, height: int) -> Encoding:
    """Measured on the VPS (20 s of 1080p, two cores): x264 ``fast`` CRF 19
    70 s, ``veryfast`` CRF 18 25 s for a file of the same size class (13 vs
    15 MB). Platforms re-encode uploads; minutes matter more than the last
    few percent of bitrate efficiency."""
    if width * height > HD:
        return Encoding("veryfast", 20)
    return Encoding("veryfast", 18)


def intermediate_preset(width: int, height: int) -> str:
    """Segments are near-lossless and short-lived: ``ultrafast`` CRF 12 took
    15 s for 20 s of 1080p where ``veryfast`` took 38 s, at ~3× the size
    (~6 MB/s). 4K keeps ``veryfast`` so a long timeline fits the scratch disk."""
    return "veryfast" if width * height > HD else "ultrafast"


def intermediate_bytes(duration: float, width: int, height: int, fps: int) -> int:
    """Expected size of all segments (measured: ~0.8 bit/pixel ultrafast,
    ~0.25 veryfast at CRF 12), plus PCM sound."""
    bits_per_pixel = 0.25 if width * height > HD else 0.8
    return int(duration * (width * height * fps * bits_per_pixel / 8 + RATE * 4))


@dataclass(frozen=True, slots=True)
class OverlayLayer:
    pattern: Path  # image2 pattern of RGBA PNGs numbered from 0
    fps: int
    width: int
    height: int


TELEGRAM_LIMIT = 50 * 1000 * 1000  # Bot API upload limit (sendVideo)


@dataclass(frozen=True, slots=True)
class ChatCopy:
    """A copy that fits the bot upload limit, for watching in the chat; the
    full-quality file stays downloadable from the Mini App."""

    width: int
    height: int
    video_bps: int
    audio_bps: int = 128_000


def chat_copy_plan(duration: float, width: int, height: int) -> ChatCopy:
    budget_bits = TELEGRAM_LIMIT * 0.92 * 8
    audio = 128_000
    video = max(250_000, int(budget_bits / max(duration, 1.0) - audio))
    short = min(width, height)
    target_short = 1080 if video >= 4_000_000 else 720 if video >= 1_500_000 else 540
    f = min(1.0, target_short / short)
    return ChatCopy(_even(width * f), _even(height * f), video, audio)


def likely_over_limit(duration: float, width: int, height: int, fps: int) -> bool:
    """Whether the master will probably be too big for the chat, so the copy is
    made in the same pass. ~0.1 bit per pixel is what CRF 19 gives talking
    footage; a wrong guess only costs the separate copy pass afterwards."""
    return duration * width * height * fps * 0.1 / 8 > TELEGRAM_LIMIT * 0.8


def _chat_output(copy: ChatCopy, out: Path, length: str) -> list[str]:
    v = copy.video_bps
    return [
        "-map", "[vchat]", "-map", "[achat]",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(v),
        "-maxrate", str(int(v * 1.3)), "-bufsize", str(int(v * 2)),
        "-pix_fmt", "yuv420p", *TAGS_709,
        "-c:a", "aac", "-b:a", str(copy.audio_bps), "-ar", str(RATE), "-ac", "2",
        "-t", length, "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def master_command(
    concat: Path,
    out: Path,
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    overlay: OverlayLayer | None,
    voice: list[str],
    loudness: str,
    sfx: list[SfxInput],
    threads: int = 2,
    chat: tuple[ChatCopy, Path] | None = None,
) -> list[str]:
    """The delivery file — and, with ``chat``, the chat-sized copy from the
    same decode and composite (one pass instead of decoding the master again)."""
    enc = encoding_for(width, height)
    args = [
        *BASE,
        "-progress",
        "pipe:1",
        "-nostats",
        "-threads",
        str(threads),
        "-filter_threads",
        str(threads),
    ]
    args += ["-f", "concat", "-safe", "0", "-i", str(concat)]
    first_sfx = 1
    if overlay is not None:
        args += ["-framerate", str(overlay.fps), "-start_number", "0", "-i", str(overlay.pattern)]
        first_sfx = 2
        size = (
            ""
            if (overlay.width, overlay.height) == (width, height)
            else f"scale={width}:{height}:flags=lanczos,"
        )
        video = (
            f"[1:v]{size}{TO_709},format=yuva420p[ov];"
            f"[0:v][ov]overlay=0:0:format=yuv420:eof_action=pass,format=yuv420p[vout]"
        )
    else:
        video = "[0:v]null[vout]"
    args += sfx_inputs(sfx)
    audio = audio_graph(voice, sfx, first_sfx_input=first_sfx, tail=loudness)
    if chat is None:
        graph = f"{video};[vout]null[v];{audio}"
    else:
        copy, _ = chat
        audio = audio.removesuffix("[a]") + "[aout]"
        graph = (
            f"{video};[vout]split=2[v][vc];[vc]scale={copy.width}:{copy.height}:flags=lanczos[vchat];"
            f"{audio};[aout]asplit=2[a][achat]"
        )
    length = f"{frames_for(duration, fps) / fps:.6f}"
    gop = fps * 2
    args += [
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", enc.x264_preset, "-crf", str(enc.crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", str(gop), "-r", str(fps),
        *TAGS_709,
        "-c:a", "aac", "-b:a", enc.audio_bitrate, "-ar", str(RATE), "-ac", "2",
        "-t", length, "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    if chat is not None:
        args += _chat_output(chat[0], chat[1], length)
    return args


def telegram_copy_command(source: Path, out: Path, *, duration: float, width: int, height: int) -> list[str]:
    """The chat copy from a finished master (when the in-pass guess said the
    master would fit but it did not)."""
    copy = chat_copy_plan(duration, width, height)
    size = (
        ""
        if (copy.width, copy.height) == (width, height)
        else f"scale={copy.width}:{copy.height}:flags=lanczos,"
    )
    v = copy.video_bps
    return [
        *BASE, "-i", str(source),
        "-vf", f"{size}format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(v),
        "-maxrate", str(int(v * 1.3)), "-bufsize", str(int(v * 2)),
        "-pix_fmt", "yuv420p", *TAGS_709,
        "-c:a", "aac", "-b:a", "128k", "-ar", str(RATE),
        "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out),
    ]  # fmt: skip


def poster_command(source: Path, out: Path, *, at: float, longest: int = 720) -> list[str]:
    return [
        *BASE, "-loglevel", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(source),
        "-frames:v", "1", "-vf", f"scale='if(gt(iw,ih),{longest},-2)':'if(gt(iw,ih),-2,{longest})'",
        "-q:v", "3", str(out),
    ]  # fmt: skip


def overlay_size(width: int, height: int, *, longest: int = 1920) -> tuple[int, int]:
    """Motion graphics are drawn at most 1920 on the long side (a headless
    browser screenshot per frame) and scaled up for 4K."""
    if max(width, height) <= longest:
        return width, height
    f = longest / max(width, height)
    return _even(width * f), _even(height * f)


def overlay_fps(fps: int) -> int:
    """Captions and widgets gain nothing above 30 fps; 50 / 60 fps output takes
    every second frame of the layer (matched by timestamp in the overlay)."""
    return fps if fps <= 30 else fps // 2


def is_frame_aligned(t: float, fps: int) -> bool:
    return math.isclose(t * fps, round(t * fps), abs_tol=1e-3)
