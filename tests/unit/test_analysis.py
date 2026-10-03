import shutil
import subprocess

import numpy as np
import pytest
from synthcut_analysis.clips import (
    ClipContext,
    build_clip,
    camera_motion,
    is_blurry,
    lighting_quality,
    speech_in,
    subject_for,
    usable_score,
)
from synthcut_analysis.faces import FaceDetector, position, shot_type
from synthcut_analysis.frames import gray_size, sample_rate
from synthcut_analysis.measure import ShotMeasure, dhash, frame_stats, hamming, measure_shot, sharpness_score
from synthcut_analysis.pipeline import analyze
from synthcut_schemas.analysis import ClipAnalysis, Face, Span

HAS_FFMPEG = shutil.which("ffmpeg") is not None
RNG = np.random.default_rng(7)


def texture(h: int = 180, w: int = 640) -> np.ndarray:
    """A wide, detailed, smooth-ish image to pan across."""
    base = RNG.integers(30, 220, size=(h // 6, w // 6)).astype(np.uint8)
    import cv2

    return cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)


def measure(**kw) -> ShotMeasure:
    base = dict(
        frames=np.arange(10),
        luma=0.5,
        dark=0.02,
        bright=0.01,
        sharpness_var=1500.0,
        sharpness=0.9,
        speed=0.0,
        shake=0.0,
        dx=0.0,
        dy=0.0,
        frozen=False,
        black=False,
        best_frame=5,
    )
    base.update(kw)
    return ShotMeasure(**base)


# --------------------------------------------------------------------------- measurements


def test_gray_size_and_sample_rate():
    assert gray_size(1280, 720) == (320, 180)
    assert gray_size(720, 1280) == (320, 568)  # portrait stays portrait, even height
    assert (sample_rate(60), sample_rate(1200), sample_rate(7200)) == (4.0, 2.0, 1.0)


def test_pan_is_measured_from_content_shift():
    wide = texture(180, 960)
    # Camera pans right: the window over the scene moves right 8 px per sample.
    frames = np.stack([wide[:, i * 8 : i * 8 + 320] for i in range(12)])
    stats = frame_stats(frames)
    m = measure_shot(stats, fps=4.0, start=0.0, end=3.0)
    assert m.dx == pytest.approx(11 * 8 / 320, abs=0.02)  # 0.275 frame widths of travel
    assert m.speed == pytest.approx(8 / 320 * 4, abs=0.01)
    assert m.shake < 0.01
    assert camera_motion(m) == "pan_right"


def test_static_black_and_frozen_frames():
    still = np.stack([texture(180, 320)] * 12)
    m = measure_shot(frame_stats(still), fps=4.0, start=0.0, end=3.0)
    assert camera_motion(m) == "static" and m.frozen and not m.black
    black = np.full((8, 180, 320), 16, dtype=np.uint8)
    b = measure_shot(frame_stats(black), fps=4.0, start=0.0, end=2.0)
    assert b.black and b.luma == pytest.approx(0.0)


def test_measurements_never_cross_a_cut():
    frame = texture(180, 320)
    # The cut jumps 60 px: a clean, *reliable* shift that is not camera travel.
    a = np.stack([frame] * 6)
    b = np.stack([np.roll(frame, 60, axis=1)] * 6)
    stats = frame_stats(np.concatenate([a, b]))
    assert stats.reliable[6] and abs(stats.shift[6][0]) == pytest.approx(60, abs=1)
    second = measure_shot(stats, fps=4.0, start=1.5, end=3.0)
    assert second.dx == pytest.approx(0.0, abs=0.01) and camera_motion(second) == "static"


def test_sharpness_scale_matches_the_calibration():
    # Measured on a real phone clip: 950–3900 sharp, σ=3 blur ≈ 350, σ=6 ≈ 80–120.
    assert sharpness_score(2500) == pytest.approx(1.0, abs=0.01)
    assert 0.65 < sharpness_score(1000) < 0.75
    assert 0.3 < sharpness_score(350) < 0.45
    assert sharpness_score(90) == 0.0


def test_dhash_finds_the_same_framing():
    img = texture(180, 320)
    noisy = np.clip(img.astype(int) + RNG.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
    assert hamming(dhash(img), dhash(noisy)) <= 6
    assert hamming(dhash(img), dhash(texture(180, 320))) > 12


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({}, "static"),
        ({"speed": 0.1, "shake": 0.01, "dx": 0.4}, "pan_right"),
        ({"speed": 0.1, "shake": 0.01, "dx": -0.4}, "pan_left"),
        ({"speed": 0.1, "shake": 0.01, "dy": 0.3}, "tilt_down"),
        ({"speed": 0.1, "shake": 0.01, "dy": -0.3}, "tilt_up"),
        ({"speed": 0.06, "shake": 0.12, "dx": 0.02}, "handheld"),
        ({"speed": 0.08, "shake": 0.03, "dx": 0.05}, "moving"),
    ],
)
def test_camera_motion_classes(kw, expected):
    assert camera_motion(measure(**kw)) == expected


def test_shot_type_position_and_subject_from_faces():
    face = lambda h, x=0.5: Face(x=x, y=0.4, height=h, score=0.9)  # noqa: E731
    assert shot_type([face(0.4)]) == "close_up"
    assert shot_type([face(0.2)]) == "medium"
    assert shot_type([face(0.05)]) == "wide"
    assert shot_type([]) == "unknown"
    assert (position([face(0.2, 0.2)]), position([face(0.2, 0.5)]), position([face(0.2, 0.8)])) == (
        "left",
        "center",
        "right",
    )
    assert [subject_for(n) for n in (0, 1, 3, 11)] == [None, "person", "people", "crowd"]


def test_face_detector_runs_on_cpu_and_finds_nothing_in_noise():
    assert FaceDetector().detect(RNG.integers(0, 255, (360, 640, 3), dtype=np.uint8)) == []


def test_blur_is_absolute_or_relative_to_the_footage():
    assert is_blurry(measure(sharpness=0.2, sharpness_var=200), None)
    assert is_blurry(measure(sharpness=0.5, sharpness_var=500), 2000)  # focus miss in sharp footage
    assert not is_blurry(measure(sharpness=0.5, sharpness_var=500), 900)  # soft scene in soft footage
    assert not is_blurry(measure(sharpness=0.9, sharpness_var=1500), 2000)


def test_lighting_and_usability():
    assert lighting_quality(measure()) == 1.0
    assert lighting_quality(measure(luma=0.08, dark=0.5)) < 0.3
    assert lighting_quality(measure(luma=0.9, bright=0.3)) < 0.3
    assert usable_score(1.0, 1.0, []) == 1.0
    assert usable_score(0.9, 0.9, ["black"]) == 0.0
    assert usable_score(1.0, 1.0, ["too_short"]) == 0.5
    assert usable_score(1.0, 1.0, ["duplicate"]) == 1.0  # a retake is information, not a defect


def test_speech_ratio_and_silent_gaps_inside_a_shot():
    spans = [Span(start=0.5, end=2.0), Span(start=4.0, end=9.0)]
    ratio, gaps = speech_in(spans, 1.0, 6.0)
    assert ratio == pytest.approx((1.0 + 2.0) / 5.0)
    assert gaps == [Span(start=2.0, end=4.0)]
    assert speech_in([], 0.0, 3.0) == (0.0, [Span(start=0.0, end=3.0)])


def test_build_clip_fills_the_contract():
    ctx = ClipContext("01a0fe85", "1920x1080", 30.0, "display_p3", True)
    clip = build_clip(
        ctx,
        index=3,
        start=10.0,
        end=10.4,
        measure=measure(sharpness=0.1, sharpness_var=150),
        faces=[Face(x=0.7, y=0.4, height=0.35, score=0.9)],
        face_count=1,
        speech=[Span(start=9.0, end=11.0)],
        duplicate_of="01a0fe85-s001",
        sample_fps=4.0,
    )
    assert clip.clip_id == "01a0fe85-s003" and clip.duration == 0.4
    assert (clip.shot_type, clip.person_position, clip.subject) == ("close_up", "right", "person")
    assert set(clip.flags) == {"blurry", "too_short", "duplicate"}
    assert clip.speech_present and clip.speech_ratio == 1.0
    assert clip.best_frame == 1.25
    assert ClipAnalysis.model_validate_json(clip.model_dump_json()) == clip


# --------------------------------------------------------------------------- end to end


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_pipeline_on_a_synthetic_reel(tmp_path):
    def ff(*args):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)

    ff("-f", "lavfi", "-i", "mandelbrot=s=2560x720:r=25", "-t", "3", "-vf", "crop=1280:720:x='t*300':y=0",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "pan.mp4"))  # fmt: skip
    ff("-f", "lavfi", "-i", "color=black:s=1280x720:r=25:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(tmp_path / "black.mp4"))  # fmt: skip
    (tmp_path / "list.txt").write_text("file pan.mp4\nfile black.mp4\n")
    ff("-f", "concat", "-i", str(tmp_path / "list.txt"), "-c:v", "libx264", "-g", "50", "-pix_fmt", "yuv420p",
       str(tmp_path / "proxy.mp4"))  # fmt: skip

    ctx = ClipContext("abcdef12", "1280x720", 25.0, "rec709", False)
    progress: list[float] = []
    result = analyze(
        tmp_path / "proxy.mp4",
        tmp_path,
        ctx=ctx,
        width=1280,
        height=720,
        duration=5.0,
        shots=[(0.0, 3.0), (3.0, 5.0)],
        speech=None,
        known_hashes={"other-s000": "0000000000000000"},
        on_progress=progress.append,
    )
    pan, black = result.clips
    assert pan.camera_motion == "pan_right" and pan.motion.dx == pytest.approx(0.7, abs=0.1)
    assert "black" in black.flags and black.usable_score == 0.0
    assert black.duplicate_of is None  # black frames never count as a retake
    assert set(result.sheets) == {0, 1} and result.sheets[0][:2] == b"\xff\xd8"
    assert progress[-1] == pytest.approx(1.0)
    assert not (tmp_path / "frames.gray").exists()
