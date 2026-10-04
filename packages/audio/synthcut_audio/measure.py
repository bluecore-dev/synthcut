"""What the voice track sounds like, from the 16 kHz speech PCM and the VAD
speech spans: speech level, the noise floor between words, SNR, clipping."""

from __future__ import annotations

import numpy as np
from synthcut_schemas.analysis import Span
from synthcut_schemas.grade import AudioMeasure

RATE = 16000
WINDOW = 0.05  # seconds


def _window_db(pcm: np.ndarray) -> np.ndarray:
    n = int(RATE * WINDOW)
    usable = len(pcm) // n * n
    if usable == 0:
        return np.zeros(0)
    frames = pcm[:usable].reshape(-1, n)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def measure_voice(
    pcm: np.ndarray,
    spans: list[Span],
    *,
    integrated_lufs: float | None = None,
    true_peak_db: float | None = None,
) -> AudioMeasure:
    db = _window_db(pcm)
    times = (np.arange(len(db)) + 0.5) * WINDOW
    speech = np.zeros(len(db), dtype=bool)
    for s in spans:
        speech |= (times >= s.start) & (times < s.end)
    voiced = db[speech]
    # Between words, ignoring digital silence (padding, muted sections).
    quiet = db[~speech & (db > -90)]
    speech_db = round(float(np.median(voiced)), 1) if voiced.size else None
    noise_db = round(float(np.median(quiet)), 1) if quiet.size >= 10 else None
    return AudioMeasure(
        integrated_lufs=integrated_lufs,
        true_peak_db=true_peak_db,
        speech_db=speech_db,
        noise_floor_db=noise_db,
        snr_db=round(speech_db - noise_db, 1) if speech_db is not None and noise_db is not None else None,
        clipped_ratio=round(float(np.mean(np.abs(pcm) >= 0.999)), 6) if pcm.size else 0.0,
        speech_ratio=round(float(speech.mean()), 3) if speech.size else 0.0,
    )
