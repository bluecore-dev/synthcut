"""Running FFmpeg under the worker's rules: lower CPU priority (the VPS is
shared), progress reporting, cooperative cancellation and a hard timeout."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable

from .errors import MediaError
from .parse import parse_progress_seconds

PERMANENT_MARKERS = (
    "Invalid data found when processing input",
    "moov atom not found",
    "does not contain any stream",
    "Unsupported codec",
    "could not find codec parameters",
    "Invalid argument",
)


def _lower_priority() -> None:  # pragma: no cover - runs in the child
    try:
        os.nice(10)
    except OSError:
        pass


def run_ffmpeg(
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    check: Callable[[], None] | None = None,
    timeout: float = 3600,
    keep_lines: int = 4000,
) -> str:
    """Run and return stderr (log) text. ``check`` is called about twice a
    second and may raise to abort (cancellation, shutdown); the process is then
    terminated and the exception propagates."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        preexec_fn=_lower_priority,
    )
    log: deque[str] = deque(maxlen=keep_lines)

    def read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            log.append(line.rstrip("\n"))

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            seconds = parse_progress_seconds(line)
            if seconds is not None and duration and on_progress:
                on_progress(min(1.0, seconds / duration))

    readers = [
        threading.Thread(target=read_stderr, daemon=True),
        threading.Thread(target=read_stdout, daemon=True),
    ]
    for t in readers:
        t.start()
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if check is not None:
                check()
            if time.monotonic() > deadline:
                raise MediaError("FFmpeg vaqt chegarasidan oshdi", permanent=False)
            time.sleep(0.5)
    except BaseException:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise
    finally:
        for t in readers:
            t.join(timeout=5)

    text = "\n".join(log)
    if proc.returncode != 0:
        tail = " | ".join(line for line in list(log)[-4:] if line.strip())[-400:]
        permanent = any(marker in text for marker in PERMANENT_MARKERS)
        raise MediaError(f"FFmpeg xatosi ({proc.returncode}): {tail}", permanent=permanent)
    return text
