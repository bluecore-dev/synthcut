"""Subtitle data from word timings: cues of at most two lines, broken at
sentence ends and pauses, with WebVTT / SRT renderings.

Preset-neutral on purpose (42 characters a line is the broadcast norm for
16:9); the Caption agent re-flows for 9:16 and styles per word in Phase 7.
"""

from __future__ import annotations

from dataclasses import dataclass

from synthcut_schemas.speech import Segment, SubtitleCue, Word

SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")
SOFT_BREAK = (",", ";", ":", "—", "–", "，")


@dataclass(frozen=True, slots=True)
class CueRules:
    max_line_chars: int = 42
    max_lines: int = 2
    max_duration: float = 6.0
    min_duration: float = 0.8
    pause_break: float = 0.6  # a gap this long between words always starts a new cue
    min_sentence_chars: int = 12  # do not close a cue after a one-word sentence fragment
    gap_after: float = 0.04  # never touch the next cue


def _text(words: list[Word]) -> str:
    return " ".join(w.word for w in words)


def _fits(words: list[Word], rules: CueRules) -> bool:
    """Whether the words fill at most ``max_lines`` lines (greedy wrap) — the
    total length alone is not enough, lines break only between words."""
    lines, width = 1, 0
    for w in words:
        need = width + 1 + len(w.word) if width else len(w.word)
        if width and need > rules.max_line_chars:
            lines, width = lines + 1, len(w.word)
        else:
            width = need
    return lines <= rules.max_lines


def split_lines(words: list[Word], rules: CueRules) -> list[str]:
    """One line if it fits, else the two-line split that balances lengths,
    preferring a break after punctuation."""
    text = _text(words)
    if len(text) <= rules.max_line_chars or len(words) < 2:
        return [text]
    best: tuple[float, int] | None = None
    for i in range(1, len(words)):
        first, second = _text(words[:i]), _text(words[i:])
        if len(first) > rules.max_line_chars or len(second) > rules.max_line_chars:
            continue
        score = abs(len(first) - len(second))
        if first.endswith(SOFT_BREAK + SENTENCE_END):
            score -= 12  # a clause per line reads better than equal lengths
        if best is None or score < best[0]:
            best = (score, i)
    i = best[1] if best else len(words) // 2
    return [_text(words[:i]), _text(words[i:])]


def build_cues(segments: list[Segment], rules: CueRules | None = None) -> list[SubtitleCue]:
    rules = rules or CueRules()
    groups: list[tuple[int, list[Word]]] = []  # (index of the first word, words)
    index = 0
    for seg in segments:
        first, current = index, []
        for w in seg.words:
            if current:
                too_long = not _fits([*current, w], rules)
                paused = w.start - current[-1].end >= rules.pause_break
                too_slow = w.end - current[0].start > rules.max_duration
                if too_long or paused or too_slow:
                    groups.append((first, current))
                    first, current = index, []
            current.append(w)
            index += 1
            if w.word.endswith(SENTENCE_END) and len(_text(current)) >= rules.min_sentence_chars:
                groups.append((first, current))
                first, current = index, []
        if current:
            groups.append((first, current))  # segments are sentences: never carry words across

    cues: list[SubtitleCue] = []
    for i, (first, words) in enumerate(groups):
        start, end = words[0].start, max(words[-1].end, words[0].start)
        if end - start < rules.min_duration:
            limit = groups[i + 1][1][0].start - rules.gap_after if i + 1 < len(groups) else end + 10
            end = max(end, min(start + rules.min_duration, limit))
        cues.append(
            SubtitleCue(
                start=round(start, 3),
                end=round(end, 3),
                lines=split_lines(words, rules),
                word_start=first,
                word_end=first + len(words),
            )
        )
    return cues


def _stamp(seconds: float, sep: str) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _vtt_escape(line: str) -> str:
    return line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_webvtt(cues: list[SubtitleCue]) -> str:
    blocks = ["WEBVTT", ""]
    for cue in cues:
        blocks.append(f"{_stamp(cue.start, '.')} --> {_stamp(cue.end, '.')}")
        blocks.extend(_vtt_escape(line) for line in cue.lines)
        blocks.append("")
    return "\n".join(blocks)


def to_srt(cues: list[SubtitleCue]) -> str:
    blocks: list[str] = []
    for n, cue in enumerate(cues, start=1):
        blocks.append(str(n))
        blocks.append(f"{_stamp(cue.start, ',')} --> {_stamp(cue.end, ',')}")
        blocks.extend(cue.lines)
        blocks.append("")
    return "\n".join(blocks)
