import shutil
import threading
import time
from pathlib import Path

import pytest
from synthcut_media import (
    MediaError,
    normalize,
    parse_loudness,
    parse_progress_seconds,
    parse_scene_cuts,
    plan_proxy,
    proxy_size,
    run_ffmpeg,
    shots_from_cuts,
    video_filter,
    video_main_pass,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def stream(**kw):
    base = {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160, "pix_fmt": "yuv420p10le",
            "r_frame_rate": "30/1", "avg_frame_rate": "30/1"}  # fmt: skip
    base.update(kw)
    return base


def probe(*streams, fmt=None, tags=None):
    f = {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.5", "bit_rate": "60000000"}
    f.update(fmt or {})
    if tags:
        f["tags"] = tags
    return {"format": f, "streams": list(streams)}


IPHONE_HDR = probe(
    stream(
        color_transfer="arib-std-b67",
        color_primaries="bt2020",
        color_space="bt2020nc",
        side_data_list=[
            {"side_data_type": "DOVI configuration record", "dv_profile": 8},
            {"side_data_type": "Display Matrix", "rotation": -90},
        ],
        avg_frame_rate="2997/100",
        r_frame_rate="30/1",
    ),
    {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "44100"},
    tags={
        "com.apple.quicktime.make": "Apple",
        "com.apple.quicktime.model": "iPhone 16 Pro",
        "com.apple.quicktime.location.ISO6709": "+41.2995+069.2401+455.000/",
    },
)


def test_iphone_hdr_portrait():
    info = normalize(IPHONE_HDR, size_bytes=307_615_269)
    v = info.video
    assert info.kind == "video" and v.rotation == 270 and (v.display_width, v.display_height) == (2160, 3840)
    assert v.orientation == "portrait" and v.bit_depth == 10 and v.chroma == "420" and v.vfr
    assert info.color.profile == "hlg" and info.color.dolby_vision and info.color.hdr
    assert info.color.label == "Dolby Vision · HLG" and info.color.confidence == "high"
    assert info.camera == {"make": "Apple", "model": "iPhone 16 Pro"}
    assert info.has_location and "+41.2995" not in info.model_dump_json()  # never keep coordinates
    assert info.audio.channels == 2 and info.audio_streams == 1


def test_apple_log_without_explicit_tag_is_medium_confidence():
    raw = probe(
        stream(codec_name="prores", profile="HQ", pix_fmt="yuv422p10le", color_primaries="bt2020"),
        tags={"com.apple.quicktime.make": "Apple"},
    )
    color = normalize(raw, size_bytes=1).color
    assert (color.profile, color.confidence, color.log) == ("apple_log", "medium", True)


def test_explicit_apple_log_marker_wins():
    raw = probe(stream(tags={"com.apple.proapps.color": "Apple Log"}))
    assert normalize(raw, size_bytes=1).color.confidence == "high"


def test_other_10bit_untagged_is_suspected_log():
    raw = probe(stream(codec_name="h264", pix_fmt="yuv422p10le"), tags={"make": "Sony"})
    color = normalize(raw, size_bytes=1).color
    assert (color.profile, color.confidence) == ("log_suspected", "low")


@pytest.mark.parametrize(
    ("kw", "profile", "confidence"),
    [
        ({"color_transfer": "smpte2084", "color_primaries": "bt2020"}, "pq", "high"),
        ({"color_transfer": "bt709", "color_primaries": "bt709", "pix_fmt": "yuv420p"}, "rec709", "high"),
        ({"pix_fmt": "yuv420p"}, "rec709", "low"),
        ({"color_transfer": "bt709", "color_primaries": "bt2020"}, "rec2020_sdr", "medium"),
    ],
)
def test_color_profiles(kw, profile, confidence):
    color = normalize(probe(stream(**kw)), size_bytes=1).color
    assert (color.profile, color.confidence) == (profile, confidence)


def test_image_audio_and_cover_art():
    img = normalize(
        {
            "format": {"format_name": "png_pipe"},
            "streams": [stream(codec_name="png", width=800, height=600, pix_fmt="rgba")],
        },
        size_bytes=1,
    )
    assert img.kind == "image" and img.color.profile == "srgb" and img.duration is None
    audio = normalize(
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "60"},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000"},
                stream(codec_name="mjpeg", disposition={"attached_pic": 1}),
            ],
        },
        size_bytes=1,
    )
    assert audio.kind == "audio" and audio.video is None and audio.duration == 60
    assert normalize({"format": {}, "streams": []}, size_bytes=1).kind == "other"


def test_anamorphic_and_odd_sizes():
    v = normalize(probe(stream(width=1440, height=1080, sample_aspect_ratio="4:3")), size_bytes=1).video
    assert (v.display_width, v.display_height) == (1920, 1080)
    assert proxy_size(1920, 1080) == (1280, 720)
    assert proxy_size(2160, 3840) == (720, 1280)
    assert proxy_size(640, 360) == (640, 360)  # never upscaled
    assert proxy_size(1001, 563) == (1000, 562)  # even


def test_hdr_proxy_is_tonemapped_only_when_zscale_exists():
    info = normalize(IPHONE_HDR, size_bytes=1)
    plan = plan_proxy(info, zscale=True)
    assert plan.tonemap and (plan.width, plan.height) == (720, 1280)
    chain = video_filter(plan)
    assert chain.index("scale=720:1280") < chain.index("tonemap=")  # tone-map at 720p, not 4K
    assert not plan_proxy(info, zscale=False).tonemap
    log = normalize(
        probe(stream(codec_name="prores", pix_fmt="yuv422p10le"), tags={"make": "Apple"}), size_bytes=1
    )
    assert not plan_proxy(log, zscale=True).tonemap and "Log" in plan_proxy(log, zscale=True).color_note


def test_main_pass_arguments_are_a_safe_list():
    info = normalize(IPHONE_HDR, size_bytes=1)
    plan = plan_proxy(info, zscale=False)
    hostile = "http://x/a.mov; rm -rf / #"
    common = {
        "plan": plan,
        "proxy": Path("/s/p.mp4"),
        "sprite_path": Path("/s/sp.jpg"),
        "sprite_tiles": 12,
        "duration": 12.5,
    }
    args = video_main_pass(hostile, speech=Path("/s/a.flac"), **common)
    assert args[args.index("-i") + 1] == hostile  # one argv element, never parsed by a shell
    assert "/s/a.flac" in args and "/s/sp.jpg" in args and args.count("-map") == 5
    graph = args[args.index("-filter_complex") + 1]
    # one decode feeds the proxy, scene detection and the filmstrip
    assert "split=3" in graph and "scdet=" in graph and "tile=12x1" in graph and "fps=0.960000" in graph
    silent = video_main_pass("u", speech=None, **common)
    assert "-an" in silent and "flac" not in silent


def test_parsers():
    lines = [
        "[Parsed_scdet_1 @ 0x1] lavfi.scd.score: 28.514, lavfi.scd.time: 3",
        "noise",
        "[Parsed_scdet_1 @ 0x1] lavfi.scd.score: 15.0, lavfi.scd.time: 3.2",
        "[Parsed_scdet_1 @ 0x1] lavfi.scd.score: 40.0, lavfi.scd.time: 9.75",
    ]
    cuts = parse_scene_cuts(lines)
    assert cuts == [(3.0, 28.514), (3.2, 15.0), (9.75, 40.0)]
    shots = shots_from_cuts(cuts, 10.0)
    # 3.2 is a flash right after 3.0, 9.75 is too close to the end: both ignored
    assert [(s["start"], s["end"]) for s in shots] == [(0.0, 3.0), (3.0, 10.0)]
    assert shots_from_cuts([], 4.0) == [{"index": 0, "start": 0.0, "end": 4.0, "duration": 4.0}]
    summary = """[Parsed_ebur128_0 @ 0x8] Summary:

  Integrated loudness:
    I:         -21.8 LUFS
    Threshold: -31.8 LUFS

  Loudness range:
    LRA:         6.3 LU

  True peak:
    Peak:      -1.5 dBFS"""
    loud = parse_loudness(summary)
    assert (loud.integrated_lufs, loud.lra_lu, loud.true_peak_dbfs) == (-21.8, 6.3, -1.5)
    assert parse_loudness("no summary here") is None
    assert parse_loudness("Summary:\n I:  -inf LUFS\n Peak:  -inf dBFS") is None
    assert parse_progress_seconds("out_time_us=6000000\n") == 6.0
    assert parse_progress_seconds("progress=end") is None


def test_flash_cuts_are_merged():
    cuts = [(2.0, 30.0), (2.1, 30.0), (5.0, 30.0), (9.9, 30.0)]
    shots = shots_from_cuts(cuts, 10.0)
    assert [s["start"] for s in shots] == [0.0, 2.0, 5.0]
    assert shots[-1]["end"] == 10.0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_runner_cancels_a_running_ffmpeg():
    args = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-re",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=60",
        "-f",
        "null",
        "-",
    ]
    stop = threading.Event()

    def check():
        if stop.is_set():
            raise KeyboardInterrupt("cancelled")

    threading.Timer(1.0, stop.set).start()
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        run_ffmpeg(args, check=check, timeout=30)
    assert time.monotonic() - started < 8


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_runner_classifies_corrupt_input_as_permanent(tmp_path):
    bad = tmp_path / "broken.mov"
    bad.write_bytes(b"not a movie" * 1000)
    with pytest.raises(MediaError) as exc:
        run_ffmpeg(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(bad), "-f", "null", "-"], timeout=30)
    assert exc.value.permanent


def test_display_p3_is_recognised_and_gamut_mapped():
    raw = probe(
        stream(codec_name="h264", pix_fmt="yuv420p", color_primaries="smpte432", color_transfer="bt709")
    )
    info = normalize(raw, size_bytes=1)
    assert (info.color.profile, info.color.label, info.color.confidence) == (
        "display_p3",
        "Display P3",
        "high",
    )
    plan = plan_proxy(info, zscale=True)
    assert plan.gamut_to_709 and "zscale=p=bt709" in video_filter(plan)
    assert not plan_proxy(info, zscale=False).gamut_to_709
