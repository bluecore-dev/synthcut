"""Final render (Phase 11) and QA (Phase 9): placement maths, exact segments,
colour fidelity through the RGB grade path, the whole segment → concat →
loudness → master chain on real FFmpeg, and the QA verdicts."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from synthcut_audio.filters import loudnorm_apply, loudnorm_measure, parse_loudnorm
from synthcut_color.grade import bake, write_cube
from synthcut_media import normalize, run_ffmpeg, run_ffprobe
from synthcut_media.final import (
    TELEGRAM_LIMIT,
    SegmentSpec,
    SfxInput,
    concat_list,
    cover_filters,
    loudness_pass,
    master_command,
    overlay_fps,
    overlay_size,
    segment_command,
    telegram_copy_command,
)
from synthcut_media.qa import Expected, Measured, judge, parse_qa_log, qa_command
from synthcut_schemas.grade import ColorGrade, MixPlan
from synthcut_schemas.qa import QaSpan

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
# The repository copy locally; the image copy (SYNTHCUT_SFX_DIR) in the test container.
SFX = (
    Path(os.environ.get("SYNTHCUT_SFX_DIR") or Path(__file__).resolve().parents[2] / "assets" / "sfx")
    / "whoosh.flac"
)


# --------------------------------------------------------------------------- placement


def test_cover_crop_centres_and_moves_within_the_picture():
    assert cover_filters(1920, 1080, 1080, 1920) == ["scale=3414:1920:flags=lanczos", "crop=1080:1920:1167:0"]
    right = cover_filters(1920, 1080, 1080, 1920, x=-0.5)  # picture moves left: we see its right side
    assert right[1] == "crop=1080:1920:1707:0"
    edge = cover_filters(1920, 1080, 1080, 1920, x=-3.0)
    assert edge[1] == "crop=1080:1920:2334:0"  # clamped to the picture's edge, no border
    assert cover_filters(1080, 1920, 1080, 1920) == ["scale=1080:1920:flags=lanczos"]


def test_fit_leaves_borders_and_pads_to_the_frame():
    f = cover_filters(1080, 1920, 1920, 1080, scale=(1080 / 1920) / (1920 / 1080))
    assert f[0] == "scale=608:1080:flags=lanczos" and f[-1] == "pad=1920:1080:656:0:black"


def test_overlay_is_drawn_at_most_1920_and_30_fps():
    assert overlay_size(1080, 1920) == (1080, 1920)
    assert overlay_size(3840, 2160) == (1920, 1080)
    assert (overlay_fps(25), overlay_fps(30), overlay_fps(50), overlay_fps(60)) == (25, 30, 25, 30)


def test_telegram_copy_fits_the_limit():
    args = telegram_copy_command(Path("in.mp4"), Path("out.mp4"), duration=180, width=1080, height=1920)
    video = int(args[args.index("-b:v") + 1])
    assert (video + 128_000) * 180 / 8 < TELEGRAM_LIMIT
    assert "scale=720:1280" in args[args.index("-vf") + 1]  # ~1.9 Mbit/s: 720p looks better than 1080p


# --------------------------------------------------------------------------- real FFmpeg


def _src(tmp: Path, name: str, size: str, rate: str, *, audio: bool, colour: str | None = None) -> Path:
    out = tmp / name
    video = f"color=c={colour}:s={size}:r={rate}:d=3" if colour else f"testsrc2=s={size}:r={rate}:d=3"
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=f=440:r=48000:d=3", "-c:a", "aac", "-shortest"]
    args += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264",
             "-crf", "10", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", str(out)]  # fmt: skip
    subprocess.run(args, check=True)
    return out


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_entries",
         "stream=codec_type,nb_read_frames,width,height,duration_ts,time_base", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def _rgb(path: Path, at: float = 0.5) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).astype(float)


@needs_ffmpeg
def test_segments_are_frame_and_sample_exact(tmp_path):
    src = _src(tmp_path, "src.mp4", "640x360", "30000/1001", audio=True)  # 29.97 fps into 30
    spec = SegmentSpec(source=str(src), start=0.4, duration=1.5, src_w=640, src_h=360)
    out = tmp_path / "seg.mkv"
    run_ffmpeg(segment_command(spec, out, width=360, height=640, fps=30, zscale=False))
    p = _probe(out)
    assert int(p["video"]["nb_read_frames"]) == 45
    assert (p["video"]["width"], p["video"]["height"]) == (360, 640)
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-f", "s16le", "-"], capture_output=True
    ).stdout
    assert len(pcm) == 72000 * 2 * 2  # 1.5 s × 48 kHz × stereo × 16 bit
    # The source ends at 3 s: the last frame is cloned and the sound padded with silence.
    short = SegmentSpec(source=str(src), start=2.5, duration=1.0, src_w=640, src_h=360)
    run_ffmpeg(segment_command(short, tmp_path / "s2.mkv", width=360, height=640, fps=30, zscale=False))
    assert int(_probe(tmp_path / "s2.mkv")["video"]["nb_read_frames"]) == 30
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(tmp_path / "s2.mkv"), "-f", "s16le", "-"], capture_output=True
    ).stdout
    assert len(pcm) == 48000 * 2 * 2
    silent = SegmentSpec(source=str(src), start=0, duration=0.5, src_w=640, src_h=360, audio=False)
    run_ffmpeg(segment_command(silent, tmp_path / "s3.mkv", width=360, height=640, fps=30, zscale=False))
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(tmp_path / "s3.mkv"), "-f", "s16le", "-"], capture_output=True
    ).stdout
    assert len(pcm) == 24000 * 2 * 2 and not any(pcm)  # muted: exact-length silence


@needs_ffmpeg
def test_the_grade_path_keeps_colour_in_rec709(tmp_path):
    """yuv → RGB (LUT) → yuv must come back as the same Rec.709 colour. FFmpeg
    ≥ 7.1 negotiates colour spaces through the graph (a forced BT.601 matrix
    is converted back for the BT.709-tagged encoder — checked on 9.0); the
    explicit matrix in the chain keeps older builds right. This guards the
    result, whichever mechanism provides it."""
    src = _src(tmp_path, "blue.mp4", "320x180", "30", audio=False, colour="0x2a5cc8")
    lut = write_cube(bake(ColorGrade()), tmp_path / "identity.cube")
    spec = SegmentSpec(source=str(src), start=0, duration=1.0, src_w=320, src_h=180, lut=lut, audio=False)
    out = tmp_path / "graded.mkv"
    run_ffmpeg(segment_command(spec, out, width=320, height=180, fps=30, zscale=False))
    before, after = _rgb(src).reshape(-1, 3).mean(axis=0), _rgb(out).reshape(-1, 3).mean(axis=0)
    np.testing.assert_allclose(after, before, atol=3)
    np.testing.assert_allclose(before, [0x2A, 0x5C, 0xC8], atol=4)


@needs_ffmpeg
def test_segments_concat_and_master_to_target_loudness(tmp_path):
    land = _src(tmp_path, "land.mp4", "640x360", "30", audio=True)
    tall = _src(tmp_path, "tall.mp4", "360x640", "25", audio=False)
    lut = write_cube(bake(ColorGrade(exposure=0.5)), tmp_path / "g.cube")
    segs = []
    for n, (spec, d) in enumerate(
        [
            (
                SegmentSpec(source=str(land), start=0.2, duration=1.5, src_w=640, src_h=360, x=0.3, lut=lut),
                1.5,
            ),
            (SegmentSpec(source=str(tall), start=1.0, duration=1.0, src_w=360, src_h=640, audio=False), 1.0),
            (SegmentSpec(source=str(land), start=2.0, duration=0.8, src_w=640, src_h=360), 0.8),
        ]
    ):
        out = tmp_path / f"seg{n}.mkv"
        run_ffmpeg(segment_command(spec, out, width=360, height=640, fps=30, zscale=False))
        segs.append((out, d))
    joined = concat_list(segs, tmp_path / "t.ffconcat", 30)
    mix = MixPlan()
    sfx = [SfxInput(path=SFX, at=1.6)]
    measured = parse_loudnorm(
        run_ffmpeg(loudness_pass(joined, sfx, ["highpass=f=80"], loudnorm_measure(mix)))
    )
    final = tmp_path / "final.mp4"
    run_ffmpeg(
        master_command(
            joined, final, width=360, height=640, fps=30, duration=3.3, overlay=None,
            voice=["highpass=f=80"], loudness=loudnorm_apply(mix, measured), sfx=sfx,
        )
    )  # fmt: skip
    info = normalize(run_ffprobe(str(final)), size_bytes=final.stat().st_size)
    report = judge(
        info,
        parse_qa_log(run_ffmpeg(qa_command(str(final))), duration=info.duration),
        Expected(width=360, height=640, fps=30, duration=3.3, target_lufs=-14.0),
    )
    by = {c.code: c for c in report.checks}
    assert report.status == "pass", report.checks
    assert by["duration"].value == pytest.approx(3.3, abs=0.05)
    assert report.integrated_lufs == pytest.approx(-14.0, abs=1.0)
    assert int(_probe(final)["video"]["nb_read_frames"]) == 99


@needs_ffmpeg
def test_qa_finds_black_frames_in_a_real_file(tmp_path):
    out = tmp_path / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=2",
         "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25:d=1.5",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )  # fmt: skip
    m = parse_qa_log(run_ffmpeg(qa_command(str(out))), duration=3.5)
    assert len(m.black) == 1 and m.black[0].start == pytest.approx(2.0, abs=0.05)


# --------------------------------------------------------------------------- QA verdicts


def _info(**video):
    from synthcut_schemas.media import AudioStream, MediaInfo, VideoStream

    v = dict(
        codec="h264",
        width=1080,
        height=1920,
        display_width=1080,
        display_height=1920,
        fps=30.0,
        pix_fmt="yuv420p",
    )
    v.update(video)
    return MediaInfo(
        kind="video", duration=20.0, size_bytes=1, video=VideoStream(**v), audio=AudioStream(codec="aac")
    )


WANT = Expected(width=1080, height=1920, fps=30, duration=20.0, target_lufs=-14.0)


def test_qa_verdicts():
    ok = judge(_info(), Measured(integrated_lufs=-14.3, true_peak_db=-1.2), WANT)
    assert ok.status == "pass"
    wrong_size = judge(_info(display_width=1920, display_height=1080), Measured(integrated_lufs=-14), WANT)
    assert wrong_size.status == "fail" and wrong_size.checks[0].code == "resolution"
    quiet = judge(_info(), Measured(integrated_lufs=-16.5), WANT)
    assert quiet.status == "warn" and any(c.code == "loudness" and c.status == "warn" for c in quiet.checks)
    very_quiet = judge(_info(), Measured(integrated_lufs=-20), WANT)
    assert very_quiet.status == "fail"
    black = judge(_info(), Measured(integrated_lufs=-14, black=[QaSpan(start=4, end=5)]), WANT)
    assert (
        black.status == "warn"
        and "4.0–5.0 s" in next(c for c in black.checks if c.code == "black_frames").message
    )
    mostly_black = judge(_info(), Measured(integrated_lufs=-14, black=[QaSpan(start=0, end=15)]), WANT)
    assert mostly_black.status == "fail"


def test_qa_log_parsing():
    log = """
[blackdetect @ 0x1] black_start:1.2 black_end:2.04 black_duration:0.84
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 5.5
[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 2.5
[freezedetect @ 0x2] lavfi.freezedetect.freeze_end: 8
[silencedetect @ 0x3] silence_start: 10.25
[silencedetect @ 0x3] silence_end: 14 | silence_duration: 3.75
[silencedetect @ 0x3] silence_start: 18.5
[Parsed_ebur128_0 @ 0x4] Summary:

  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.3 LUFS

  Loudness range:
    LRA:         5.1 LU

  True peak:
    Peak:       -1.3 dBFS
"""
    m = parse_qa_log(log, duration=20.0)
    assert m.black == [QaSpan(start=1.2, end=2.04)]
    assert m.frozen == [QaSpan(start=5.5, end=8.0)]
    assert m.silence == [QaSpan(start=10.25, end=14.0), QaSpan(start=18.5, end=20.0)]  # silent to the end
    assert (m.integrated_lufs, m.true_peak_db, m.decode_errors) == (-14.2, -1.3, 0)


def test_each_clip_lut_carries_the_originals_gamut():
    from synthcut_timeline import EffectRef, VideoClip
    from synthcut_worker.render.final import clip_grade

    def clip(*effects):
        return VideoClip(
            id="c", asset_id="00000000-0000-4000-8000-000000000001", source_in=0, source_out=1,
            timeline_start=0, timeline_end=1, effects=list(effects),
        )  # fmt: skip

    graded = EffectRef(type="grade", params=ColorGrade(exposure=0.3).model_dump(mode="json"))
    assert clip_grade(clip(graded), "display_p3").input_transform == "display_p3"
    assert clip_grade(clip(), "display_p3").input_transform == "display_p3"  # gamut alone still needs a LUT
    assert clip_grade(clip(graded), "rec709").input_transform == "none"
    assert clip_grade(clip(), "rec709") is None  # nothing to do: no LUT pass at all
    log = EffectRef(type="grade", params=ColorGrade(input_transform="apple_log").model_dump(mode="json"))
    assert clip_grade(clip(log), "apple_log").input_transform == "apple_log"


@needs_ffmpeg
def test_wide_gamut_segment_skips_zscale_when_the_lut_converts():
    spec = SegmentSpec(source="in.mov", start=0, duration=1, src_w=1920, src_h=1080, color_profile="display_p3",
                       lut=Path("g.cube"), gamut_in_lut=True)  # fmt: skip
    graph = segment_command(spec, Path("o.mkv"), width=1920, height=1080, fps=30, zscale=True)
    assert "zscale" not in " ".join(graph) and "lut3d" in " ".join(graph)
    plain = SegmentSpec(
        source="in.mov", start=0, duration=1, src_w=1920, src_h=1080, color_profile="display_p3"
    )
    assert "zscale=p=bt709" in " ".join(
        segment_command(plain, Path("o.mkv"), width=1920, height=1080, fps=30, zscale=True)
    )
