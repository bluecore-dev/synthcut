"""Running the Remotion app (apps/remotion) from a job: ``overlay/1`` props in,
a transparent ProRes 4444 layer out. Same rules as FFmpeg — nice, cancellable,
bounded — through ``synthcut_media.run_tool``."""

from __future__ import annotations

import json
from collections.abc import Callable
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


def render_overlay(
    props: OverlayProps,
    work: Path,
    *,
    remotion_dir: Path,
    concurrency: int = 2,
    on_progress: Callable[[float], None] | None = None,
    check: Callable[[], None] | None = None,
) -> Path:
    bundle = remotion_dir / "build"
    script = remotion_dir / "scripts" / "render.mjs"
    if not (bundle / "index.html").exists() or not script.exists():
        raise RemotionUnavailable(f"Remotion bundle not found in {remotion_dir}")
    props_path = work / "overlay.json"
    props_path.write_text(props.model_dump_json())
    out = work / "overlay.mov"
    # Generous: capture + ProRes run at ~25 fps on four Mac cores; assume 4 on the VPS.
    timeout = 600 + props.duration_in_frames / 4
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
    if not out.exists() or out.stat().st_size == 0:
        raise MediaError("Remotion produced no output", permanent=False)
    return out
