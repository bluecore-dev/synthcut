"""Running the Remotion app (apps/remotion) from a job: ``overlay/1`` props in,
a transparent PNG sequence out (FFmpeg composites it directly). Same rules as
FFmpeg — nice, cancellable, bounded — through ``synthcut_media.run_tool``."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from synthcut_media import MediaError, run_tool
from synthcut_timeline.overlay import OverlayProps

# Remotion / Chromium failures that a retry cannot fix.
PERMANENT = (
    "Could not find composition",
    "is not in the motion registry",
    "Invalid props",
    "TypeError",
    "ReferenceError",
)


class RemotionUnavailable(RuntimeError):
    """The image has no Remotion bundle (wrong image, or the build step failed)."""


def _progress(line: str) -> float | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        value = json.loads(line).get("progress")
    except (ValueError, AttributeError):
        return None
    return float(value) if isinstance(value, (int, float)) else None


@dataclass(frozen=True, slots=True)
class OverlayFrames:
    """A rendered layer: ``pattern`` is an FFmpeg image2 pattern (``frame-%04d.png``)."""

    directory: Path
    pattern: str
    fps: int
    count: int


def render_overlay(
    props: OverlayProps,
    work: Path,
    *,
    remotion_dir: Path,
    concurrency: int = 2,
    on_progress: Callable[[float], None] | None = None,
    check: Callable[[], None] | None = None,
) -> OverlayFrames:
    bundle = remotion_dir / "build"
    script = remotion_dir / "scripts" / "render.mjs"
    if not (bundle / "index.html").exists() or not script.exists():
        raise RemotionUnavailable(f"Remotion bundle not found in {remotion_dir}")
    props_path = work / "overlay.json"
    props_path.write_text(props.model_dump_json())
    out = work / "overlay"
    out.mkdir(exist_ok=True)
    # Measured on the VPS: ~11 frames/s of 720p capture on two cores.
    timeout = 600 + props.duration_in_frames / 3
    run_tool(
        ["node", str(script), str(props_path), str(out), str(bundle), str(concurrency)],
        name="Remotion",
        progress=_progress,
        on_progress=on_progress,
        check=check,
        timeout=timeout,
        permanent_markers=PERMANENT,
        cwd=str(remotion_dir),
    )
    # Remotion pads frame numbers to the width of the last one; read it back
    # from the files rather than assuming it.
    frames = sorted(out.glob("frame-*.png"))
    if len(frames) != props.duration_in_frames:
        raise MediaError(
            f"Remotion rendered {len(frames)} of {props.duration_in_frames} frames", permanent=False
        )
    match = re.fullmatch(r"frame-(\d+)\.png", frames[0].name)
    if match is None:
        raise MediaError(f"unexpected frame name {frames[0].name}", permanent=True)
    return OverlayFrames(out, str(out / f"frame-%0{len(match.group(1))}d.png"), props.fps, len(frames))
