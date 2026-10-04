"""The piece renderer on real FFmpeg: transitions, speed, keyframed zoom,
picture-in-picture, fades, black pieces — each checked on the pixels and
samples it produces, and the pieces of a plan from the timeline compiler."""

import shutil
import subprocess
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from synthcut_media import run_ffmpeg
from synthcut_media.compose import Key, Layer, PieceSpec, UnsupportedAnimation, curve, piece_command, value_at
from synthcut_timeline import EditPlan
from synthcut_timeline.pieces import plan_pieces

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
W, H, FPS, RATE = 320, 180, 25, 48000


def colour_clip(tmp: Path, name: str, colour: str, *, tone: int | None = 440, seconds: int = 4) -> Path:
    out = tmp / name
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={colour}:s={W}x{H}:r={FPS}:d={seconds}",
    ]
    if tone:
        args += [
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='0.3*sin(2*PI*{tone}*t)':s={RATE}:d={seconds}",
            "-c:a",
            "aac",
            "-shortest",
        ]
    args += ["-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "10", str(out)]
    subprocess.run(args, check=True)
    return out


def layer(src: Path, **kw) -> Layer:
    return Layer(source=str(src), start=kw.pop("start", 0.0), src_w=W, src_h=H, **kw)


def render(tmp: Path, spec: PieceSpec, name="piece.mkv") -> Path:
    out = tmp / name
    run_ffmpeg(piece_command(spec, out, width=W, height=H, fps=FPS, zscale=False))
    return out


def frame(path: Path, at: float) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(float)


def samples(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-f", "f32le", "-"], capture_output=True
    ).stdout
    return np.frombuffer(raw, np.float32)


def count_frames(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return int(out.strip())


def tone_level(pcm: np.ndarray, a: float, b: float, freq: float) -> float:
    part = pcm[int(a * RATE) : int(b * RATE)]
    t = np.arange(part.size) / RATE
    return float(
        np.hypot((part * np.sin(2 * np.pi * freq * t)).mean(), (part * np.cos(2 * np.pi * freq * t)).mean())
        * 2
    )


def test_keyframe_curves_ease_and_hold():
    keys = [Key(0.0, 1.0, "linear"), Key(2.0, 2.0, "ease_in_out"), Key(4.0, 1.0)]
    assert value_at(keys, -1, 0) == 1.0 and value_at(keys, 1.0, 0) == pytest.approx(1.5)
    assert value_at(keys, 3.0, 0) == pytest.approx(1.5) and value_at(keys, 9, 0) == 1.0
    expr = curve(keys, "T", 1.0)
    for t in (0.0, 0.5, 1.0, 2.5, 3.9, 5.0):  # the FFmpeg expression is the same curve
        py = expr.replace("T", f"({t})").replace("if(", "_if(").replace("lt(", "_lt(")
        assert eval(py, {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b}) == pytest.approx(  # noqa: S307
            value_at(keys, t, 1.0)
        )


@needs_ffmpeg
def test_crossfade_blends_picture_and_sound(tmp_path):
    red, blue = (
        colour_clip(tmp_path, "r.mp4", "red", tone=300),
        colour_clip(tmp_path, "b.mp4", "blue", tone=600),
    )
    out = render(
        tmp_path, PieceSpec(duration=1.0, main=layer(red), incoming=layer(blue), transition="crossfade")
    )
    assert count_frames(out) == 25
    first, mid, last = frame(out, 0.0), frame(out, 0.5), frame(out, 0.96)
    assert first[..., 0].mean() > 200 and first[..., 2].mean() < 40
    assert last[..., 2].mean() > 200 and last[..., 0].mean() < 40
    assert 80 < mid[..., 0].mean() < 180 and 80 < mid[..., 2].mean() < 180
    pcm = samples(out)
    assert pcm.size == RATE
    assert tone_level(pcm, 0.0, 0.15, 300) > 2 * tone_level(pcm, 0.0, 0.15, 600)
    assert tone_level(pcm, 0.85, 1.0, 600) > 2 * tone_level(pcm, 0.85, 1.0, 300)


@needs_ffmpeg
def test_dip_to_black_goes_through_black(tmp_path):
    white, grey = (
        colour_clip(tmp_path, "w.mp4", "white", tone=None),
        colour_clip(tmp_path, "g.mp4", "gray", tone=None),
    )
    out = render(
        tmp_path,
        PieceSpec(
            duration=1.0,
            main=layer(white, audio=False),
            incoming=layer(grey, audio=False),
            transition="dip_to_black",
        ),
    )
    assert frame(out, 0.5).mean() < 40 and frame(out, 0.0).mean() > 200


@needs_ffmpeg
def test_double_speed_reads_twice_the_source(tmp_path):
    red, blue = (
        colour_clip(tmp_path, "r.mp4", "red", tone=None, seconds=3),
        colour_clip(tmp_path, "b.mp4", "blue", tone=None, seconds=3),
    )
    joined = tmp_path / "rb.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(red), "-i", str(blue), "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
                    "-map", "[v]", "-c:v", "libx264", "-crf", "10", str(joined)], check=True)  # fmt: skip
    tone = tmp_path / "tone.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(joined), "-f", "lavfi", "-i", f"aevalsrc='0.3*sin(2*PI*400*t)':s={RATE}:d=6",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(tone)], check=True)  # fmt: skip
    out = render(tmp_path, PieceSpec(duration=2.0, main=layer(tone, speed=2.0)))
    assert count_frames(out) == 50
    assert frame(out, 1.2)[..., 0].mean() > 200  # source 2.4 s: red
    assert frame(out, 1.8)[..., 2].mean() > 200  # source 3.6 s: blue
    pcm = samples(out)
    assert (
        pcm.size == 2 * RATE and tone_level(pcm, 0.5, 1.5, 400) > 0.1
    )  # tempo changes, pitch stays (atempo)
    slow = render(tmp_path, PieceSpec(duration=2.0, main=layer(tone, speed=0.5)), "slow.mkv")
    assert count_frames(slow) == 50 and samples(slow).size == 2 * RATE


@needs_ffmpeg
def test_keyframed_zoom_grows_the_subject(tmp_path):
    card = tmp_path / "card.mp4"  # a white 40×40 square in the middle of black
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d=3",
                    "-vf", "drawbox=x=140:y=70:w=40:h=40:color=white:t=fill,format=yuv420p", "-c:v", "libx264", "-crf", "5", str(card)],
                   check=True)  # fmt: skip
    zoom = layer(card, audio=False, keys={"scale": [Key(0.0, 1.0, "linear"), Key(2.0, 2.0)]})
    out = render(tmp_path, PieceSpec(duration=2.0, main=zoom))
    start, end = (frame(out, 0.0) > 128).sum(), (frame(out, 1.96) > 128).sum()
    assert end == pytest.approx(start * 4, rel=0.15)  # 2× zoom: four times the area
    assert frame(out, 1.96)[H // 2, W // 2].mean() > 200  # still centred


@needs_ffmpeg
def test_picture_in_picture_sits_where_the_plan_says(tmp_path):
    black, red = (
        colour_clip(tmp_path, "k.mp4", "black", tone=300),
        colour_clip(tmp_path, "r.mp4", "red", tone=600),
    )
    pip = layer(red, scale=0.3, x=0.3, y=-0.3, audio=False)
    out = render(tmp_path, PieceSpec(duration=1.0, main=layer(black), overlays=(pip,)))
    f = frame(out, 0.5)
    cx, cy = int(W / 2 + 0.3 * W), int(H / 2 - 0.3 * H)
    assert f[cy, cx, 0] > 200 and f[cy, cx, 1] < 60  # red in the top right
    assert f[H // 2, W // 2].mean() < 30  # the main picture elsewhere
    assert tone_level(samples(out), 0.2, 0.8, 300) > 0.1  # main sound kept, the muted overlay adds none
    assert tone_level(samples(out), 0.2, 0.8, 600) < 0.02


@needs_ffmpeg
def test_overlay_fades_in_and_main_less_pieces_are_black(tmp_path):
    black, red = (
        colour_clip(tmp_path, "k.mp4", "black", tone=None),
        colour_clip(tmp_path, "r.mp4", "red", tone=None),
    )
    cut = layer(red, audio=False, keys={"opacity": [Key(0.0, 0.0, "linear"), Key(1.0, 1.0)]})
    out = render(tmp_path, PieceSpec(duration=1.5, main=layer(black, audio=False), overlays=(cut,)))
    assert frame(out, 0.04)[..., 0].mean() < 40 and frame(out, 1.2)[..., 0].mean() > 200
    assert 60 < frame(out, 0.5)[..., 0].mean() < 190
    empty = render(tmp_path, PieceSpec(duration=0.8, main=None), "empty.mkv")
    assert (
        count_frames(empty) == 20 and frame(empty, 0.4).mean() < 5 and samples(empty).size == int(0.8 * RATE)
    )
    with pytest.raises(UnsupportedAnimation):
        piece_command(
            PieceSpec(duration=1, main=layer(black), overlays=(layer(red, keys={"opacity": [Key(0, 0.2), Key(0.5, 0.6), Key(1, 1)]}),)),
            tmp_path / "x.mkv", width=W, height=H, fps=FPS, zscale=False,
        )  # fmt: skip


def _plan(**over) -> EditPlan:
    a, b = UUID(int=1), UUID(int=2)
    data = {
        "project_id": str(UUID(int=9)), "version": 1,
        "sequence": {"fps": 25, "width": 320, "height": 180, "duration": 6.0},
        "video_tracks": [
            {"track": 1, "role": "main", "clips": [
                {"id": "a", "asset_id": str(a), "source_in": 0, "source_out": 3.6, "timeline_start": 0, "timeline_end": 3.6},
                {"id": "b", "asset_id": str(b), "source_in": 1, "source_out": 4.0, "timeline_start": 3.0, "timeline_end": 6.0,
                 "transition_in": {"type": "crossfade", "duration": 0.6}},
            ]},
            {"track": 2, "role": "broll", "clips": [
                {"id": "c", "asset_id": str(b), "source_in": 0, "source_out": 1.0, "timeline_start": 1.0, "timeline_end": 2.0},
            ]},
        ],
    }  # fmt: skip
    data.update(over)
    return EditPlan.model_validate(data)


def test_the_timeline_compiler_cuts_where_layers_change():
    pieces = plan_pieces(_plan())
    assert [(p.start, p.end) for p in pieces] == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 3.6), (3.6, 6.0)]
    assert [s.clip.id for s in pieces[1].overlays] == ["c"]
    t = pieces[3]
    assert (t.main.clip.id, t.incoming.clip.id, t.transition.type) == ("a", "b", "crossfade")
    assert (t.main.source_start, t.incoming.source_start) == (3.0, 1.0)
    assert (
        pieces[4].main.clip.id == "b" and pieces[4].main.source_start == 1.6 and pieces[4].main.offset == 0.6
    )
    assert sum(p.duration for p in pieces) == pytest.approx(6.0)
