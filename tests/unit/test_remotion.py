"""The real motion engine: Python builds overlay/1, Node + Remotion render it,
the result is a transparent ProRes 4444 layer of the right size and length
with pixels only where the caption is. Needs the bundle and headless Chrome
(``cd apps/remotion && npm ci && npm run bundle && npx remotion browser ensure``);
skipped otherwise. In the worker image both are built in."""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest
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
    out = render_overlay(props, tmp_path, remotion_dir=REMOTION, concurrency=2, on_progress=seen.append)

    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,pix_fmt,nb_frames",
         "-of", "default=nw=1", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    assert "codec_name=prores" in info and "width=360" in info and "height=640" in info
    assert "pix_fmt=yuva444p" in info  # alpha survived
    assert seen and seen[-1] == pytest.approx(1.0)

    caption = alpha_plane(out, 0.8, 360, 640)
    assert caption[0, 0] == 0 and caption[-1, -1] == 0  # corners stay transparent
    middle = caption[250:390, :]
    assert (middle > 200).sum() > 500  # opaque caption pixels around the centre line
    empty = alpha_plane(out, 0.0, 360, 640)  # before the first word
    assert (empty > 0).sum() == 0
