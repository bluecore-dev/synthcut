"""Running FFmpeg under the worker's rules: lower CPU priority (the VPS is
shared), progress reporting, cooperative cancellation and a hard timeout."""

from __future__ import annotations

import shutil
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


# Per-frame analysis lines (scdet, ebur128) say nothing about why FFmpeg
# failed; keep them out of the error tail.
NOISE_MARKERS = ("lavfi.scd.", "Parsed_ebur128", "frame=", "size=")


def _error_tail(lines: list[str]) -> str:
    useful = [line for line in lines if line.strip() and not any(m in line for m in NOISE_MARKERS)]
    return " | ".join(useful[-4:])[-400:]


# `nice` execs the command, so the PID we signal is ffmpeg itself. (A
# preexec_fn would be unsafe here: the worker is multi-threaded and forking
# with Python code in the child can deadlock.)
NICE = ["nice", "-n", "10"] if shutil.which("nice") else []


def run_ffmpeg(
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    check: Callable[[], None] | None = None,
    timeout: float = 3600,
    keep_lines: int = 4000,
) -> str:
    """Run FFmpeg and return stderr (log) text. ``check`` is called about twice
    a second and may raise to abort (cancellation, shutdown); the process is
    then terminated and the exception propagates."""

    def progress(line: str) -> float | None:
        seconds = parse_progress_seconds(line)
        return min(1.0, seconds / duration) if seconds is not None and duration else None

    return run_tool(
        args,
        name="FFmpeg",
        progress=progress,
        on_progress=on_progress,
        check=check,
        timeout=timeout,
        keep_lines=keep_lines,
    )


def run_tool(
    args: list[str],
    *,
    name: str,
    progress: Callable[[str], float | None] | None = None,
    on_progress: Callable[[float], None] | None = None,
    check: Callable[[], None] | None = None,
    timeout: float = 3600,
    keep_lines: int = 4000,
    permanent_markers: tuple[str, ...] = PERMANENT_MARKERS,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> str:
    """Any media tool under the worker's rules (nice, cancellable, bounded).
    ``progress`` turns one stdout line into a 0..1 fraction (or None)."""
    proc = subprocess.Popen(
        [*NICE, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        env=env,
        cwd=cwd,
    )
    log: deque[str] = deque(maxlen=keep_lines)

    def read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            log.append(line.rstrip("\n"))

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            fraction = progress(line) if progress else None
            if fraction is not None and on_progress:
                on_progress(fraction)

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
                raise MediaError(f"{name} vaqt chegarasidan oshdi", permanent=False)
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
    if proc.returncode < 0:
        # Killed by a signal we did not send: on this host that is the
        # container's memory limit (OOM killer, SIGKILL). Worth a retry.
        signal_no = -proc.returncode
        hint = " — ehtimol xotira yetmadi" if signal_no == 9 else ""
        raise MediaError(f"{name} to'xtatildi (signal {signal_no}){hint}", permanent=False)
    if proc.returncode != 0:
        permanent = any(marker in text for marker in permanent_markers)
        raise MediaError(f"{name} xatosi ({proc.returncode}): {_error_tail(list(log))}", permanent=permanent)
    return text
