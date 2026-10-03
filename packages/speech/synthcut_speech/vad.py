"""Where someone is speaking — Silero VAD (bundled with faster-whisper, ONNX on
CPU, ~1 s per minute of audio). Fast enough to run in shot analysis, long
before the slow transcription finishes."""

from __future__ import annotations

import numpy as np
from synthcut_schemas.analysis import Span

from .audio import SAMPLE_RATE


def speech_spans(pcm: np.ndarray, *, min_silence: float = 0.5, pad: float = 0.1) -> list[Span]:
    if len(pcm) == 0:
        return []
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    chunks = get_speech_timestamps(
        pcm,
        VadOptions(min_silence_duration_ms=int(min_silence * 1000), speech_pad_ms=int(pad * 1000)),
        sampling_rate=SAMPLE_RATE,
    )
    return [
        Span(start=round(c["start"] / SAMPLE_RATE, 3), end=round(c["end"] / SAMPLE_RATE, 3)) for c in chunks
    ]
