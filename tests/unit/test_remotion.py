"""The real motion engine: Python builds overlay/1, Node + Remotion render it,
the result is a transparent PNG sequence of the right size and length with
pixels only where the caption is, and FFmpeg composites it. Needs the bundle and headless Chrome
(``cd apps/remotion && npm ci && npm run bundle && npx remotion browser ensure``);
skipped otherwise. In the worker image both are built in."""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest
from synthcut_media import composite_overlay
from synthcut_schemas.speech import Segment, Transcript, Word
from synthcut_timeline.overlay import build_overlay
from synthcut_worker.render.jobs import preview_plan
from synthcut_worker.render.remotion import render_overlay

REMOTION = Path(os.environ.get("SYNTHCUT_REMOTION_DIR", Path(__file__).parents[2] / "apps" / "remotion"))
READY = (
    shutil.which("node")
    and shutil.which("ffprobe")
    and (REMOTION / "build" / "index.html").exists()
    and (REMOTION / "node_modules" / ".remotion").exists()
)

pytestmark = pytest.mark.skipif(not READY, reason="Remotion bundle / headless Chrome not installed")


def alpha_plane(path: Path, at: float, w: int, h: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-vf", "alphaextract,format=gray", "-f", "rawvideo", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w)


def test_captions_render_to_a_transparent_layer(tmp_path):
    asset = uuid.uuid4()
    plan = preview_plan(
        project_id=uuid.uuid4(), asset_id=asset, width=360, height=640, source_fps=29.97,
        duration=1.2, style="dynamic", position="center",
    )  # fmt: skip
    words = [Word(word="Qadrli", start=0.1, end=0.5), Word(word="do‘stlar!", start=0.55, end=1.0)]
    transcript = Transcript(
        engine="test",
        duration=1.2,
        segments=[Segment(id=0, start=0.1, end=1.0, text="Qadrli do‘stlar!", words=words)],
    )
    props = build_overlay(plan, {asset: transcript})
    seen: list[float] = []
    layer = render_overlay(props, tmp_path, remotion_dir=REMOTION, concurrency=2, on_progress=seen.append)
    assert layer.count == props.duration_in_frames == 36  # 1.2 s at 30 fps
    assert seen and seen[-1] == pytest.approx(1.0)

    def alpha_at(seconds: float) -> np.ndarray:
        frame = Path(layer.pattern % round(seconds * layer.fps))
        return alpha_plane(frame, 0, 360, 640)

    caption = alpha_at(0.8)
    assert caption[0, 0] == 0 and caption[-1, -1] == 0  # corners stay transparent
    assert (caption[250:390, :] > 200).sum() > 500  # opaque caption pixels around the centre line
    assert (alpha_at(0.0) > 0).sum() == 0  # before the first word

    background = tmp_path / "bg.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x204060:s=360x640:r=30:d=1.2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(background)],
        check=True,
    )  # fmt: skip
    out = tmp_path / "out.mp4"
    subprocess.run(
        composite_overlay(background, layer.pattern, out, overlay_fps=layer.fps),
        check=True,
        capture_output=True,
    )
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-of", "default=nw=1", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    assert "codec_name=h264" in info and "width=360" in info and "height=640" in info


def test_keyframes_move_a_graphic_across_the_frame(tmp_path):
    """After Effects-style animation of a whole component: x from left to right."""
    from synthcut_timeline import EditPlan

    plan = EditPlan.model_validate(
        {
            "project_id": str(uuid.uuid4()), "version": 1,
            "sequence": {"fps": 30, "width": 360, "height": 640, "duration": 1.0},
            "video_tracks": [{"track": 1, "role": "main", "clips": [
                {"id": "a", "asset_id": str(uuid.uuid4()), "source_in": 0, "source_out": 1, "timeline_start": 0, "timeline_end": 1}]}],
            "graphics": [{
                "id": "t", "component": "TitleCard", "timeline_start": 0, "timeline_end": 1.0,
                "props": {"title": "Salom", "variant": "lower_third", "enter": "none", "exit": "none"},
                "keyframes": [{"t": 0, "property": "x", "value": -0.3, "easing": "linear"},
                              {"t": 0.9, "property": "x", "value": 0.3}],
            }],
        }
    )  # fmt: skip
    props = build_overlay(plan, {})
    assert [k.frame for k in props.items[0].keyframes] == [0, 27]
    layer = render_overlay(props, tmp_path, remotion_dir=REMOTION, concurrency=2)

    def centre_x(frame: int) -> float:
        alpha = alpha_plane(Path(layer.pattern % frame), 0, 360, 640)
        cols = np.nonzero(alpha > 128)[1]
        assert cols.size > 100, frame
        return float(cols.mean())

    # The card reveals itself first (its own entrance), then rides the keyframes:
    # x = -0.3 + 0.6 * 15/27 at frame 15, 0.3 from frame 27 on.
    mid, end = centre_x(15), centre_x(29)
    assert end - mid == pytest.approx((0.3 - (-0.3 + 0.6 * 15 / 27)) * 360, rel=0.15)
