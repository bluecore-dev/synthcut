"""Speech contract (spec §13), stored as ``transcripts.data`` and as
``analysis/<asset>/transcript.json``.

Every later stage reads this shape, never an engine's raw output: the Director
cuts on word boundaries, the Caption agent styles ``cues`` (word timings kept
for karaoke-style captions), the Editor trims ``silences``. Engines are
replaceable (``SPEECH_ROUTE``); the contract is not.

Times are seconds on the *source* clip's timeline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Speech(BaseModel):
    # Responses always carry every field, so the generated TypeScript types
    # mark defaulted fields as present instead of optional.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Word(_Speech):
    word: str
    start: float
    end: float
    probability: float | None = None


class Segment(_Speech):
    """Roughly a sentence (the engine's segmentation, split at long pauses)."""

    id: int
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    question: bool = False


class Silence(_Speech):
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class SubtitleCue(_Speech):
    """Preset-neutral subtitle data: ≤ 2 lines. ``word_start``/``word_end``
    (exclusive) index ``Transcript.words``, so per-word timing stays available
    for animated captions without storing every word twice. The Caption agent
    (Phase 7) re-flows and styles these per output format."""

    start: float
    end: float
    lines: list[str]
    word_start: int
    word_end: int


class Transcript(_Speech):
    schema_version: Literal["transcript/1"] = "transcript/1"
    engine: str  # provider:model, e.g. "faster-whisper:large-v3-turbo"
    language: str | None = None
    language_probability: float | None = None
    language_forced: bool = False
    duration: float
    speech_seconds: float = 0.0
    word_count: int = 0
    segments: list[Segment] = Field(default_factory=list)
    silences: list[Silence] = Field(default_factory=list)
    cues: list[SubtitleCue] = Field(default_factory=list)

    @property
    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if s.text)
