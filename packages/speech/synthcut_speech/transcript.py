"""Engine output → the ``Transcript`` contract: clean words and times, drop
repeated hallucinations, mark questions, attach silences and subtitle cues."""

from __future__ import annotations

from synthcut_schemas.speech import Segment, Silence, Transcript, Word

from .cues import CueRules, build_cues
from .engines import EngineResult, RawSegment

QUESTION_END = ("?", "？", "؟")

# Whisper writes Uzbek with Turkish/Azerbaijani letters ("şirin", "uçun",
# "tarixı", "və"); Uzbek Latin spells these sh, ch, i, a, o‘, g‘, u, ng.
_UZ_LATIN = str.maketrans(
    {
        "ş": "sh", "Ş": "Sh", "ç": "ch", "Ç": "Ch", "ı": "i", "İ": "I",
        "ə": "a", "Ə": "A", "ö": "o‘", "Ö": "O‘", "ğ": "g‘", "Ğ": "G‘",
        "ü": "u", "Ü": "U", "ñ": "ng", "â": "a", "î": "i", "û": "u",
    }
)  # fmt: skip


def normalize_text(text: str, language: str | None) -> str:
    return text.translate(_UZ_LATIN) if language == "uz" else text


def _clean_words(seg: RawSegment, duration: float, language: str | None) -> list[Word]:
    words: list[Word] = []
    floor = max(0.0, seg.start)
    for w in seg.words:
        text = normalize_text(w.word.strip(), language)
        if not text:
            continue
        start = min(max(w.start, floor), duration)
        end = min(max(w.end, start), duration)
        words.append(
            Word(
                word=text,
                start=round(start, 3),
                end=round(end, 3),
                probability=None if w.probability is None else round(w.probability, 3),
            )
        )
        floor = start  # times never run backwards
    return words


def clean_segments(raw: list[RawSegment], duration: float, language: str | None = None) -> list[Segment]:
    out: list[Segment] = []
    previous = ""
    for seg in raw:
        text = normalize_text(" ".join(seg.text.split()), language)
        # Whisper's failure mode on noise is the same line again and again: keep the first.
        if not text or text == previous:
            continue
        previous = text
        words = _clean_words(seg, duration, language)
        start = words[0].start if words else max(0.0, seg.start)
        end = words[-1].end if words else min(duration, seg.end)
        out.append(
            Segment(
                id=len(out),
                start=round(start, 3),
                end=round(max(end, start), 3),
                text=text,
                words=words,
                avg_logprob=None if seg.avg_logprob is None else round(seg.avg_logprob, 3),
                no_speech_prob=None if seg.no_speech_prob is None else round(seg.no_speech_prob, 3),
                question=text.endswith(QUESTION_END),
            )
        )
    return out


def build_transcript(
    result: EngineResult,
    *,
    route: str,
    duration: float,
    language_forced: bool,
    silences: list[Silence],
    rules: CueRules | None = None,
) -> Transcript:
    segments = clean_segments(result.segments, duration, result.language)
    return Transcript(
        engine=route,
        language=result.language,
        language_probability=(
            None if result.language_probability is None else round(result.language_probability, 3)
        ),
        language_forced=language_forced,
        duration=round(duration, 3),
        speech_seconds=round(sum(s.end - s.start for s in segments), 3),
        word_count=sum(len(s.words) for s in segments),
        segments=segments,
        silences=silences,
        cues=build_cues(segments, rules),
    )
