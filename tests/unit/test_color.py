"""Phase 8 colour: published curves, the grade pipeline, baked LUTs, automatic
grades and shot matching — checked against numbers, and once through FFmpeg."""

import shutil
import subprocess

import numpy as np
import pytest
from synthcut_color.auto import auto_grade, matched_grades, measure
from synthcut_color.grade import GREY, apply_grade, bake, contrast_curve, is_identity, write_cube
from synthcut_color.spaces import (
    REC2020,
    apple_log_decode,
    apple_log_encode,
    display_decode,
    display_encode,
    gamut_matrix,
    luma,
    slog3_decode,
    slog3_encode,
)
from synthcut_schemas.grade import ColorGrade, ColorMeasure

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def grey(v: float) -> np.ndarray:
    return np.array([[v, v, v]])


# --------------------------------------------------------------------------- curves


def test_published_curve_values_and_round_trips():
    assert float(apple_log_encode(np.array(0.18))) == pytest.approx(0.4883, abs=1e-3)  # Apple white paper
    assert float(slog3_encode(np.array(0.18))) * 1023 == pytest.approx(
        420.0, abs=0.05
    )  # Sony: 18 % grey = 420
    xs = np.array([0.0, 0.005, 0.01, 0.18, 0.9, 4.0, 16.0])
    np.testing.assert_allclose(apple_log_decode(apple_log_encode(xs)), xs, atol=1e-9)
    np.testing.assert_allclose(slog3_decode(slog3_encode(xs)), xs, atol=1e-9)
    codes = np.linspace(0.05, 1.0, 50)
    np.testing.assert_allclose(display_encode(display_decode(codes)), codes, atol=1e-12)


def test_gamut_matrix_keeps_white_and_maps_wide_colours_outside():
    m = gamut_matrix(REC2020)
    np.testing.assert_allclose(m @ np.ones(3), np.ones(3), atol=1e-9)
    red2020 = m @ np.array([1.0, 0.0, 0.0])
    assert red2020[0] > 1.0 and red2020[1] < 0.0  # more saturated than Rec.709 can show


# --------------------------------------------------------------------------- grade


def test_neutral_grade_is_an_identity_lut():
    g = ColorGrade()
    assert is_identity(g)
    lut = bake(g, size=9)
    axis = np.linspace(0, 1, 9)
    np.testing.assert_allclose(lut[2, 5, :, 0], axis, atol=1e-12)  # R varies fastest
    np.testing.assert_allclose(lut[2, :, 7, 1], axis, atol=1e-12)
    np.testing.assert_allclose(lut[:, 1, 3, 2], axis, atol=1e-12)


@pytest.mark.parametrize(("stops", "factor"), [(1.0, 2.0), (-1.0, 0.5), (2.0, 4.0), (0.5, 2**0.5)])
def test_exposure_is_stops_in_linear_light(stops, factor):
    out = apply_grade(grey(0.2), ColorGrade(exposure=stops))
    assert display_decode(out[0, 0]) == pytest.approx(factor * display_decode(0.2), rel=1e-6)


def test_white_balance_warms_without_changing_luminance():
    out = apply_grade(grey(0.5), ColorGrade(temperature=20))[0]
    assert out[0] > out[1] > out[2]
    assert float(luma(display_decode(out))) == pytest.approx(float(display_decode(0.5)), rel=0.01)


def test_saturation_contrast_and_profiles():
    colour = np.array([[0.8, 0.4, 0.2]])
    flat = apply_grade(colour, ColorGrade(saturation=0.0))[0]
    assert np.ptp(flat) < 1e-9
    bw = apply_grade(colour, ColorGrade(creative_profile="bw_classic"))[0]
    assert np.ptp(bw) < 1e-9
    off = apply_grade(colour, ColorGrade(creative_profile="cinematic_clean", intensity=0.0))
    np.testing.assert_allclose(off, colour, atol=1e-9)
    v = np.array([0.0, 0.2, GREY, 0.8, 1.0])
    c = contrast_curve(v, 1.3)
    assert c[0] == 0 and c[-1] == 1 and c[2] == pytest.approx(GREY)
    assert c[1] < 0.2 < 0.8 < c[3]  # darker darks, brighter brights
    for name in ("cinematic_clean", "warm_film", "cool_teal", "vivid_social"):
        out = apply_grade(np.random.default_rng(1).random((200, 3)), ColorGrade(creative_profile=name))
        assert out.min() >= 0 and out.max() <= 1


def test_apple_log_lands_neutral_and_rolls_highlights_off():
    g = ColorGrade(input_transform="apple_log")
    mid = apply_grade(grey(float(apple_log_encode(np.array(0.18)))), g)[0]
    assert np.ptp(mid) < 1e-6 and 0.4 < mid[0] < 0.5  # neutral, near display mid-grey
    codes = np.linspace(0.3, 1.0, 30)
    ramp = apply_grade(np.repeat(codes[:, None], 3, axis=1), g)[:, 0]
    assert np.all(np.diff(ramp) > 0) and ramp[-1] < 1.0  # monotonic, no hard clip


def test_cube_file_format(tmp_path):
    lut = bake(ColorGrade(), size=3)
    text = write_cube(lut, tmp_path / "g.cube").read_text().splitlines()
    assert "LUT_3D_SIZE 3" in text
    rows = [line for line in text if line[:1].isdigit()]
    assert len(rows) == 27 and rows[1] == "0.500000 0.000000 0.000000"  # red changes first


# --------------------------------------------------------------------------- automatic grade


def m(**kw) -> ColorMeasure:
    base = dict(
        luma_mean=0.45, luma_p05=0.1, luma_p95=0.85, cast_red=0.0, cast_blue=0.0, saturation=0.2, frames=10
    )
    base.update(kw)
    return ColorMeasure(**base)


def test_auto_grade_corrects_what_is_off_and_explains_it():
    neutral = auto_grade(m())
    assert (neutral.exposure, neutral.temperature, neutral.tint) == (0.0, 0.0, 0.0)
    dark = auto_grade(m(luma_mean=0.28))
    assert dark.exposure > 0.5 and any("Ekspozitsiya" in n for n in dark.notes)
    blue = auto_grade(m(cast_blue=0.05, cast_red=-0.02))
    assert blue.temperature > 5 and any("iliqroq" in n for n in blue.notes)
    green = auto_grade(m(cast_red=-0.03, cast_blue=-0.03))
    assert green.tint > 5
    flat = auto_grade(m(luma_p05=0.3, luma_p95=0.6, saturation=0.08))
    assert flat.contrast > 1.1 and flat.saturation == 1.15
    black = auto_grade(m(luma_mean=0.01))
    assert black.exposure == 0.0  # black frames say nothing about exposure
    log = auto_grade(m(), transform="apple_log", profile="cinematic_clean")
    assert log.input_transform == "apple_log" and "Apple Log" in log.notes[0]


def test_measure_reads_casts_on_midtones_only():
    rng = np.random.default_rng(3)
    # Luminance noise (shared by the channels, like real camera noise at proxy size).
    frames = np.repeat(np.clip(0.45 + rng.normal(0, 0.08, (4, 20, 30, 1)), 0, 1), 3, axis=-1)
    frames[..., 2] += 0.06  # blue cast in the midtones
    frames[:, :10] = 1.0  # half of every frame is a clipped white sky: no colour information
    got = measure(np.clip(frames, 0, 1))
    assert got.cast_blue > 0.05 and abs(got.cast_red) < 0.02 and got.frames == 4
    assert got.luma_p95 == pytest.approx(1.0, abs=0.01)


def test_shot_matching_pulls_shots_to_one_exposure():
    dark, bright, normal = m(luma_mean=0.32), m(luma_mean=0.58), m(luma_mean=0.45)
    grades = matched_grades([dark, bright, normal])
    after = [
        float(display_encode(display_decode(x.luma_mean) * 2**g.exposure))
        for x, g in zip([dark, bright, normal], grades, strict=True)
    ]
    assert max(after) - min(after) < (0.58 - 0.32) * 0.5  # at least halves the jump between cuts


# --------------------------------------------------------------------------- through FFmpeg


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_baked_lut_brightens_a_grey_card_in_ffmpeg(tmp_path):
    cube = write_cube(bake(ColorGrade(exposure=1.0)), tmp_path / "plus1.cube")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x4d4d4d:s=64x64:d=0.2",
         "-vf", f"format=gbrp,lut3d=file={cube}:interp=tetrahedral,format=rgb24",
         "-frames:v", "1", "-f", "rawvideo", str(tmp_path / "out.rgb")],
        check=True,
    )  # fmt: skip
    pixels = np.fromfile(tmp_path / "out.rgb", dtype=np.uint8).astype(float) / 255
    expected = float(display_encode(2 * display_decode(0x4D / 255)))
    assert pixels.mean() == pytest.approx(expected, abs=0.02)


def test_a_colourful_scene_is_not_mistaken_for_a_cast():
    """The owner's clip: an orange brick wall behind a white shirt. Grey world
    cooled it by -13; the neutral surfaces say there is no cast."""
    rng = np.random.default_rng(5)
    frames = np.zeros((3, 40, 40, 3))
    frames[:, :30] = np.array([0.72, 0.42, 0.28]) + rng.normal(0, 0.02, (3, 30, 40, 3))  # brick
    frames[:, 30:] = 0.8 + rng.normal(0, 0.01, (3, 10, 40, 3))  # white shirt, neutral
    got = measure(np.clip(frames, 0, 1))
    assert abs(got.cast_red) < 0.01 and abs(got.cast_blue) < 0.01
    assert auto_grade(got).temperature == 0.0
    tinted = frames.copy()
    tinted[:, 30:, :, 2] += 0.05  # now the shirt itself is blue: a real cast
    assert measure(np.clip(tinted, 0, 1)).cast_blue > 0.03


def test_wide_gamut_sdr_converts_inside_the_lut():
    from synthcut_color.spaces import DISPLAY_P3

    g = ColorGrade(input_transform="display_p3")
    assert not is_identity(g)
    white, grey18 = apply_grade(grey(1.0), g)[0], apply_grade(grey(0.5), g)[0]
    np.testing.assert_allclose(white, [1, 1, 1], atol=1e-9)  # D65 stays D65
    np.testing.assert_allclose(grey18, [0.5, 0.5, 0.5], atol=1e-9)
    p3 = np.array([[0.3, 0.7, 0.4]])  # a P3 green that Rec.709 shows less saturated
    expected = display_encode(np.clip(display_decode(p3) @ gamut_matrix(DISPLAY_P3).T, 0, 1))
    np.testing.assert_allclose(apply_grade(p3, g), expected, atol=1e-9)
    assert apply_grade(p3, g)[0, 1] > p3[0, 1]  # the same light needs a stronger 709 green
    assert apply_grade(p3, ColorGrade())[0, 1] == pytest.approx(0.7)  # untouched without the transform
