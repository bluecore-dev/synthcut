"""Quality control of a rendered file (spec §26, Phase 9). One decode of the
output measures black frames, frozen picture, loudness, true peak and
silences; ffprobe's normalised description checks the container. ``judge``
turns the measurements into a ``qa/1`` report with Uzbek messages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from synthcut_schemas.media import MediaInfo
from synthcut_schemas.qa import QaCheck, QaReport, QaSpan, Verdict

from .parse import parse_loudness

BLACK_MIN = 0.5
FREEZE_MIN = 2.0
SILENCE_MIN = 3.0


def qa_command(path: str, *, threads: int = 2) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-threads", str(threads), "-i", path,
        "-vf", f"blackdetect=d={BLACK_MIN}:pix_th=0.10,freezedetect=n=-60dB:d={FREEZE_MIN}",
        "-af", f"ebur128=peak=true:framelog=quiet,silencedetect=n=-50dB:d={SILENCE_MIN}",
        "-f", "null", "-",
    ]  # fmt: skip


@dataclass
class Measured:
    black: list[QaSpan] = field(default_factory=list)
    frozen: list[QaSpan] = field(default_factory=list)
    silence: list[QaSpan] = field(default_factory=list)
    integrated_lufs: float | None = None
    true_peak_db: float | None = None
    decode_errors: int = 0


_NUM = r"(-?\d+(?:\.\d+)?)"
_BLACK = re.compile(rf"black_start:\s*{_NUM}\s+black_end:\s*{_NUM}")
_FREEZE_START = re.compile(rf"freeze_start:\s*{_NUM}")
_FREEZE_END = re.compile(rf"freeze_end:\s*{_NUM}")
_SILENCE_START = re.compile(rf"silence_start:\s*{_NUM}")
_SILENCE_END = re.compile(rf"silence_end:\s*{_NUM}")
_DECODE_ERROR = re.compile(r"error while decoding|corrupt|Invalid NAL|concealing \d+ ", re.I)


def _pairs(log: str, start: re.Pattern[str], end: re.Pattern[str], until: float | None) -> list[QaSpan]:
    spans: list[QaSpan] = []
    open_at: float | None = None
    for line in log.splitlines():
        if (m := start.search(line)) is not None:
            open_at = float(m.group(1))
        elif (m := end.search(line)) is not None and open_at is not None:
            spans.append(QaSpan(start=round(max(0.0, open_at), 3), end=round(float(m.group(1)), 3)))
            open_at = None
    if open_at is not None and until is not None:  # still frozen / silent at the end
        spans.append(QaSpan(start=round(max(0.0, open_at), 3), end=round(until, 3)))
    return spans


def parse_qa_log(log: str, *, duration: float | None = None) -> Measured:
    loud = parse_loudness(log)
    return Measured(
        black=[QaSpan(start=float(a), end=float(b)) for a, b in _BLACK.findall(log)],
        frozen=_pairs(log, _FREEZE_START, _FREEZE_END, duration),
        silence=_pairs(log, _SILENCE_START, _SILENCE_END, duration),
        integrated_lufs=loud.integrated_lufs if loud else None,
        true_peak_db=loud.true_peak_dbfs if loud else None,
        decode_errors=len(_DECODE_ERROR.findall(log)),
    )


@dataclass(frozen=True, slots=True)
class Expected:
    width: int
    height: int
    fps: int
    duration: float
    audio: bool = True
    target_lufs: float | None = -14.0
    true_peak_db: float = -1.0


def _spans(spans: list[QaSpan]) -> str:
    shown = ", ".join(f"{s.start:.1f}–{s.end:.1f} s" for s in spans[:4])
    return shown + (f" (+{len(spans) - 4})" if len(spans) > 4 else "")


def _worst(checks: list[QaCheck]) -> Verdict:
    statuses = {c.status for c in checks}
    return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"


def judge(info: MediaInfo, m: Measured, want: Expected) -> QaReport:
    checks: list[QaCheck] = []

    def add(code: str, status: Verdict, message: str, value: float | str | None = None) -> None:
        checks.append(QaCheck(code=code, status=status, message=message, value=value))

    v = info.video
    if v is None:
        add("video_stream", "fail", "Faylda video oqimi yo'q")
    else:
        size = f"{v.display_width}×{v.display_height}"
        if (v.display_width, v.display_height) == (want.width, want.height):
            add("resolution", "pass", f"O'lcham {size}", size)
        else:
            add("resolution", "fail", f"O'lcham {size}, kerak edi {want.width}×{want.height}", size)
        if v.fps is not None and abs(v.fps - want.fps) < 0.01:
            add("fps", "pass", f"{want.fps} fps", v.fps)
        else:
            add("fps", "fail", f"Kadr chastotasi {v.fps}, kerak edi {want.fps}", v.fps)
        if v.codec != "h264" or v.pix_fmt not in (None, "yuv420p"):
            add("codec", "warn", f"Video {v.codec} {v.pix_fmt} — H.264 yuv420p kutilgan", v.codec)

    d = info.duration
    if d is None:
        add("duration", "fail", "Davomiylik o'qilmadi")
    else:
        off = abs(d - want.duration)
        tolerance = max(2 / want.fps, 0.1)
        status: Verdict = "pass" if off <= tolerance else "warn" if off <= 0.5 else "fail"
        add("duration", status, f"Davomiylik {d:.2f} s (reja {want.duration:.2f} s)", round(d, 3))

    if want.audio:
        if info.audio is None:
            add("audio_stream", "fail", "Faylda ovoz yo'q")
        elif want.target_lufs is not None and m.integrated_lufs is not None:
            off = abs(m.integrated_lufs - want.target_lufs)
            status = "pass" if off <= 1.0 else "warn" if off <= 3.0 else "fail"
            add(
                "loudness",
                status,
                f"Balandlik {m.integrated_lufs:.1f} LUFS (maqsad {want.target_lufs:g})",
                m.integrated_lufs,
            )
        if m.true_peak_db is not None:
            ok = m.true_peak_db <= want.true_peak_db + 0.5
            add(
                "true_peak",
                "pass" if ok else "warn",
                f"Cho'qqi {m.true_peak_db:.1f} dBTP" + ("" if ok else f" — {want.true_peak_db:g} dan baland"),
                m.true_peak_db,
            )
        if m.silence:
            add("silence", "warn", f"Uzun jimlik: {_spans(m.silence)}", len(m.silence))

    black = sum(s.end - s.start for s in m.black)
    if m.black:
        status = "fail" if d and black > d * 0.5 else "warn"
        add("black_frames", status, f"Qora kadrlar: {_spans(m.black)}", round(black, 2))
    else:
        add("black_frames", "pass", "Qora kadr yo'q", 0.0)
    if m.frozen:
        add("frozen_frames", "warn", f"Qotib qolgan kadr: {_spans(m.frozen)}", len(m.frozen))
    if m.decode_errors:
        add("decode_errors", "fail", f"Dekodlashda {m.decode_errors} ta xato", m.decode_errors)

    return QaReport(
        status=_worst(checks),
        checks=checks,
        width=v.display_width if v else None,
        height=v.display_height if v else None,
        fps=v.fps if v else None,
        duration=d,
        video_codec=v.codec if v else None,
        audio_codec=info.audio.codec if info.audio else None,
        integrated_lufs=m.integrated_lufs,
        true_peak_db=m.true_peak_db,
        black=m.black,
        frozen=m.frozen,
        silence=m.silence,
    )
