"""Speech engines behind one interface, chosen by ``SPEECH_ROUTE``
(``provider:model``). Only the local CPU engine exists today; an API engine
(OpenAI, ElevenLabs, an Uzbek STT service) is one more class here, decided
when its key exists — never guessed.
"""

from __future__ import annotations

import gc
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from .audio import SAMPLE_RATE

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RawWord:
    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass(slots=True)
class RawSegment:
    start: float
    end: float
    text: str
    words: list[RawWord] = field(default_factory=list)
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


@dataclass(slots=True)
class EngineResult:
    language: str | None
    language_probability: float | None
    segments: list[RawSegment]
    seconds: float = 0.0  # wall time, for telemetry


class SpeechEngine(Protocol):
    route: str  # provider:model

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None,
        on_progress: Callable[[float], None] | None = None,
        check: Callable[[], None] | None = None,
    ) -> EngineResult: ...


# Whisper hears Uzbek as one of its Turkic neighbours (the first real clip came
# back as Azerbaijani with "small"). When detection lands on one of these, the
# deployment's preferred language wins; a genuinely Turkish file is forced by
# picking its language explicitly.
TURKIC_NEIGHBOURS = frozenset({"uz", "az", "tr", "kk", "ky", "tk", "tt", "ba", "ug"})


def resolve_language(detected: str, preferred: str | None) -> str:
    if (
        preferred
        and detected != preferred
        and detected in TURKIC_NEIGHBOURS
        and preferred in TURKIC_NEIGHBOURS
    ):
        return preferred
    return detected


class EngineUnavailable(RuntimeError):
    """The configured engine cannot run here (model not fetched, bad route)."""


# Whisper prompts condition style. Without one, Uzbek can come out in Cyrillic
# or without punctuation; a short Latin-script sentence with punctuation steers it.
PROMPTS: dict[str, str] = {
    "uz": "Assalomu alaykum. Bugun sizlarga o‘zbek tilida gapirib beraman, so‘ng savollarga javob beraman.",
}


class FasterWhisperEngine:
    """Whisper on CTranslate2, int8 on CPU (the VPS has no GPU). The model is
    loaded per job and released after it, so the 3 GB media worker never holds
    it while encoding proxies."""

    provider = "faster-whisper"

    def __init__(
        self,
        model: str,
        *,
        models_dir: Path,
        threads: int = 2,
        beam_size: int = 5,
        compute_type: str = "int8",
        preferred_language: str | None = None,
    ) -> None:
        self.model = model
        self.models_dir = Path(models_dir)
        self.threads = threads
        self.beam_size = beam_size
        self.compute_type = compute_type
        self.preferred_language = preferred_language

    @property
    def route(self) -> str:
        return f"{self.provider}:{self.model}"

    def fetch(self) -> Path:
        """Download the model into ``models_dir`` (deploy step, idempotent)."""
        from faster_whisper.utils import download_model

        self.models_dir.mkdir(parents=True, exist_ok=True)
        return Path(download_model(self.model, cache_dir=str(self.models_dir)))

    def is_fetched(self) -> bool:
        """A snapshot folder alone is not enough: its files are symlinks into
        the cache's blob store, and a broken link must count as missing."""
        from faster_whisper.utils import download_model

        try:
            path = Path(download_model(self.model, cache_dir=str(self.models_dir), local_files_only=True))
        except Exception:
            return False
        weights = path / "model.bin"
        return weights.is_file() and weights.stat().st_size > 1024 * 1024

    def _load(self):
        from faster_whisper import WhisperModel

        try:
            return WhisperModel(
                self.model,
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=self.threads,
                num_workers=1,
                download_root=str(self.models_dir),
                local_files_only=True,  # never download in the middle of a job
            )
        except Exception as exc:
            raise EngineUnavailable(f"{self.route}: model not available ({type(exc).__name__})") from exc

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None,
        on_progress: Callable[[float], None] | None = None,
        check: Callable[[], None] | None = None,
    ) -> EngineResult:
        started = time.monotonic()
        duration = len(audio) / SAMPLE_RATE
        model = self._load()
        try:
            detected_probability: float | None = None
            if language is None:
                # Detect first (over a few windows of speech), so the Turkic
                # mix-up can be corrected before decoding starts.
                detected, detected_probability, ranked = model.detect_language(
                    audio, vad_filter=True, language_detection_segments=3
                )
                language = resolve_language(detected, self.preferred_language)
                if language != detected:
                    detected_probability = dict(ranked).get(language)
                if check:
                    check()
            segments, info = model.transcribe(
                audio,
                language=language,
                task="transcribe",
                beam_size=self.beam_size,
                word_timestamps=True,
                vad_filter=True,  # skips non-speech: faster, and no hallucinated text in silence
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,  # stops repetition loops from spreading
                initial_prompt=PROMPTS.get(language or ""),
            )
            out: list[RawSegment] = []
            for seg in segments:  # lazy: decoding happens while we iterate
                out.append(
                    RawSegment(
                        start=seg.start,
                        end=seg.end,
                        text=seg.text,
                        words=[RawWord(w.word, w.start, w.end, w.probability) for w in (seg.words or [])],
                        avg_logprob=seg.avg_logprob,
                        no_speech_prob=seg.no_speech_prob,
                    )
                )
                if on_progress and duration:
                    on_progress(min(1.0, seg.end / duration))
                if check:
                    check()
            return EngineResult(
                language=info.language,
                language_probability=detected_probability,
                segments=out,
                seconds=time.monotonic() - started,
            )
        finally:
            del model
            gc.collect()


def engine_for(
    route: str,
    *,
    models_dir: Path,
    threads: int,
    beam_size: int,
    preferred_language: str | None = None,
) -> SpeechEngine:
    provider, sep, model = route.partition(":")
    if not sep or not model:
        raise EngineUnavailable(f"SPEECH_ROUTE must be 'provider:model', got {route!r}")
    if provider == FasterWhisperEngine.provider:
        return FasterWhisperEngine(
            model,
            models_dir=models_dir,
            threads=threads,
            beam_size=beam_size,
            preferred_language=preferred_language,
        )
    raise EngineUnavailable(f"unknown speech provider {provider!r}")
