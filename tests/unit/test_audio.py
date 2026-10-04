"""Phase 8 audio: voice measurement, automatic mix plans, FFmpeg chains —
loudness and ducking verified by measuring FFmpeg's actual output."""

import json
import shutil
import subprocess

import numpy as np
import pytest
from synthcut_audio.filters import ducked_mix, loudnorm_apply, loudnorm_measure, parse_loudnorm, voice_filters
from synthcut_audio.measure import RATE, measure_voice
from synthcut_audio.plan import auto_mix, denoise_level
from synthcut_schemas.analysis import Span
from synthcut_schemas.grade import AudioMeasure, Ducking, MixPlan

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def voice_like(
    seconds: float, speech: list[tuple[float, float]], *, voice_amp=0.1, noise_amp=0.003, seed=1
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    pcm = rng.normal(0, noise_amp, t.size)
    for a, b in speech:
        on = (t >= a) & (t < b)
        pcm[on] += voice_amp * np.sqrt(2) * np.sin(2 * np.pi * 220 * t[on])
    return pcm.astype(np.float32)


def am(**kw) -> AudioMeasure:
    base = dict(
        integrated_lufs=-24.0,
        true_peak_db=-3.0,
        speech_db=-22.0,
        noise_floor_db=-62.0,
        snr_db=40.0,
        clipped_ratio=0.0,
        speech_ratio=0.6,
    )
    base.update(kw)
    return AudioMeasure(**base)


def test_measure_separates_voice_from_the_noise_floor():
    spans = [(0.5, 2.0), (2.6, 4.0)]
    got = measure_voice(
        voice_like(5.0, spans), [Span(start=a, end=b) for a, b in spans], integrated_lufs=-21.0
    )
    assert got.speech_db == pytest.approx(-20.0, abs=1.0)  # RMS 0.1
    assert got.noise_floor_db == pytest.approx(-50.5, abs=1.5)  # white noise σ 0.003
    assert got.snr_db == pytest.approx(30, abs=2) and got.speech_ratio == pytest.approx(0.58, abs=0.03)
    assert got.clipped_ratio == 0


def test_denoise_follows_the_noise_floor_and_snr():
    assert denoise_level(am(noise_floor_db=-65)) == "off"
    assert denoise_level(am(noise_floor_db=-55)) == "light"
    assert denoise_level(am(noise_floor_db=-45)) == "medium"
    assert denoise_level(am(noise_floor_db=-35)) == "strong"
    assert denoise_level(am(noise_floor_db=-55, snr_db=10)) == "medium"  # noise close to the voice
    assert denoise_level(am(noise_floor_db=None)) == "off"


def test_auto_mix_targets_and_explains():
    plan = auto_mix(am(noise_floor_db=-47, speech_db=-26), target="podcast")
    assert plan.loudness.target_lufs == -16 and plan.voice.denoise == "medium"
    assert plan.voice.compressor.threshold_db == -24.0  # just above the speech level
    assert any("Shovqin" in n for n in plan.notes) and any("-24.0 → -16 LUFS" in n for n in plan.notes)
    broadcast = auto_mix(am(), target="broadcast")
    assert (broadcast.loudness.target_lufs, broadcast.loudness.true_peak_db) == (-23, -2)
    clipped = auto_mix(am(clipped_ratio=0.01))
    assert any("kliplangan" in n for n in clipped.notes)


def test_voice_chain_order_matches_the_spec():
    chain = voice_filters(auto_mix(am(noise_floor_db=-45)), noise_floor_db=-45)
    names = [f.split("=")[0] for f in chain]
    assert names == ["highpass", "afftdn", "equalizer", "equalizer", "acompressor", "deesser"]
    assert "nf=-45" in chain[1] and "threshold=-20dB" in chain[4]


def test_loudnorm_parse_and_second_pass():
    log = 'frame=1\n[Parsed_loudnorm_0 @ 0x1] \n{\n\t"input_i" : "-27.61",\n\t"input_tp" : "-4.47",\n\t"input_lra" : "18.06",\n\t"input_thresh" : "-39.20",\n\t"output_i" : "-14.0",\n\t"target_offset" : "0.58"\n}\n'
    measured = parse_loudnorm(log)
    second = loudnorm_apply(MixPlan(), measured)
    assert "measured_I=-27.61" in second and "offset=0.58" in second and "linear=true" in second
    with pytest.raises(ValueError):
        parse_loudnorm("no json here")


def _ebur128_integrated(path) -> float:
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    return float(log.rsplit("I:", 1)[1].split("LUFS")[0])


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_two_pass_loudness_hits_the_target(tmp_path):
    src = tmp_path / "quiet.wav"
    pcm = voice_like(8.0, [(0.5, 3.5), (4.0, 7.5)], voice_amp=0.02, noise_amp=0.002)
    pcm.tofile(tmp_path / "quiet.f32")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "f32le",
            "-ar",
            str(RATE),
            "-ac",
            "1",
            "-i",
            str(tmp_path / "quiet.f32"),
            str(src),
        ],
        check=True,
    )
    plan = auto_mix(am(noise_floor_db=-55), target="social")
    chain = ",".join(voice_filters(plan, noise_floor_db=-55))
    first = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", f"{chain},{loudnorm_measure(plan)}", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    measured = parse_loudnorm(first)
    out = tmp_path / "out.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-af", f"{chain},{loudnorm_apply(plan, measured)}", "-ar", "48000", str(out)],
        check=True,
    )  # fmt: skip
    assert _ebur128_integrated(src) < -30
    assert _ebur128_integrated(out) == pytest.approx(-14.0, abs=1.0)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_music_ducks_under_the_voice(tmp_path):
    t = np.arange(int(6 * RATE)) / RATE
    voice = np.where((t >= 2) & (t < 4), 0.3 * np.sin(2 * np.pi * 1000 * t), 0.0).astype(np.float32)
    music = (0.2 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    voice.tofile(tmp_path / "v.f32")
    music.tofile(tmp_path / "m.f32")
    plan = MixPlan(ducking=Ducking(amount_db=-15, attack_ms=50, release_ms=300))
    graph = ducked_mix("0:a", "1:a", plan)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", str(tmp_path / "v.f32"),
         "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", str(tmp_path / "m.f32"),
         "-filter_complex", graph, "-map", "[mix]", "-f", "f32le", "-ar", str(RATE), "-ac", "1", str(tmp_path / "mix.f32")],
        check=True,
    )  # fmt: skip
    mix = np.fromfile(tmp_path / "mix.f32", dtype=np.float32)

    def music_level(a: float, b: float) -> float:
        seg = mix[int(a * RATE) : int(b * RATE)]
        ref = np.sin(2 * np.pi * 300 * np.arange(seg.size) / RATE + 2 * np.pi * 300 * a)
        cos = np.cos(2 * np.pi * 300 * np.arange(seg.size) / RATE + 2 * np.pi * 300 * a)
        return float(np.hypot((seg * ref).mean(), (seg * cos).mean()) * 2)

    alone, under_voice = music_level(0.5, 1.5), music_level(2.5, 3.5)
    assert alone == pytest.approx(0.2, rel=0.15)
    assert under_voice < alone * 0.5  # at least 6 dB down while someone speaks
    assert json.dumps(plan.model_dump(mode="json"))  # the plan stays serialisable
