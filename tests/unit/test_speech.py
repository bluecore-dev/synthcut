import os
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from synthcut_schemas.speech import Segment, Silence, Transcript, Word
from synthcut_speech.audio import SAMPLE_RATE, load_pcm, parse_silences, silence_threshold_db
from synthcut_speech.cues import CueRules, build_cues, split_lines, to_srt, to_webvtt
from synthcut_speech.engines import (
    EngineResult,
    EngineUnavailable,
    FasterWhisperEngine,
    RawSegment,
    RawWord,
    engine_for,
)
from synthcut_speech.transcript import build_transcript, clean_segments

HAS_FFMPEG = shutil.which("ffmpeg") is not None
FIXTURES = Path(__file__).parent.parent / "fixtures"
# A CTranslate2 "tiny" model directory; the real-engine test is skipped without it.
TINY = Path(os.environ.get("SYNTHCUT_TEST_WHISPER_TINY", Path.home() / ".cache/synthcut-whisper/tiny"))


def words(text: str, start: float = 0.0, step: float = 0.3, gap: float = 0.0) -> list[Word]:
    out = []
    t = start
    for w in text.split():
        out.append(Word(word=w, start=round(t, 3), end=round(t + step - 0.05, 3)))
        t += step + gap
    return out


def seg(text: str, start: float = 0.0, **kw) -> Segment:
    ws = words(text, start, **kw)
    return Segment(id=0, start=ws[0].start, end=ws[-1].end, text=text, words=ws)


# --------------------------------------------------------------------------- silences


def test_silences_pair_up_and_a_silent_ending_runs_to_the_end():
    log = "\n".join(
        [
            "[silencedetect @ 0x1] silence_start: -0.0123",
            "[silencedetect @ 0x1] silence_end: 1.5 | silence_duration: 1.51",
            "frame=  10 fps=0.0 q=-0.0 size=N/A",
            "[silencedetect @ 0x1] silence_start: 7.25",
            "[silencedetect @ 0x1] silence_end: 8.75 | silence_duration: 1.5",
            "[silencedetect @ 0x1] silence_start: 12.0",
        ]
    )
    assert parse_silences(log, 13.0) == [
        Silence(start=0.0, end=1.5),
        Silence(start=7.25, end=8.75),
        Silence(start=12.0, end=13.0),
    ]


def test_silence_threshold_follows_loudness_within_a_band():
    assert silence_threshold_db(None) == -40.0
    assert silence_threshold_db(-20.5) == -42.5
    assert silence_threshold_db(-45.0) == -55.0  # very quiet recording: not all "silence"
    assert silence_threshold_db(-5.0) == -30.0


# --------------------------------------------------------------------------- cues


def test_cues_close_at_sentence_ends_and_index_every_word_once():
    s1 = seg("Raqamlardan boshlaymiz. Bugun uchta mavzu bor.", 0.0)
    s2 = seg("Birinchisi montaj.", 5.0)
    s2.id = 1
    cues = build_cues([s1, s2])
    assert [c.lines for c in cues] == [
        ["Raqamlardan boshlaymiz."],
        ["Bugun uchta mavzu bor."],
        ["Birinchisi montaj."],
    ]
    flat = [w for s in (s1, s2) for w in s.words]
    covered = [i for c in cues for i in range(c.word_start, c.word_end)]
    assert covered == list(range(len(flat)))
    assert all(flat[c.word_start].start == c.start for c in cues)


def test_a_long_pause_starts_a_new_cue():
    s = Segment(
        id=0,
        start=0.0,
        end=4.0,
        text="birinchi qism ikkinchi qism",
        words=[*words("birinchi qism", 0.0), *words("ikkinchi qism", 2.0)],
    )
    cues = build_cues([s])
    assert [c.lines for c in cues] == [["birinchi qism"], ["ikkinchi qism"]]


def test_long_speech_is_cut_by_length_and_duration_into_two_balanced_lines():
    text = " ".join(["so'z"] * 60)
    cues = build_cues([seg(text, 0.0, step=0.25)])
    rules = CueRules()
    assert len(cues) > 3
    for c in cues:
        assert 1 <= len(c.lines) <= 2
        assert all(len(line) <= rules.max_line_chars for line in c.lines)
        assert c.end - c.start <= rules.max_duration + 0.01
    assert all(a.end <= b.start for a, b in pairwise(cues))


def test_two_line_split_prefers_punctuation():
    ws = words("Bugun biz montaj haqida, rang haqida va ovoz haqida gaplashamiz")
    lines = split_lines(ws, CueRules())
    assert lines == ["Bugun biz montaj haqida,", "rang haqida va ovoz haqida gaplashamiz"]


def test_short_cue_is_held_for_reading_but_never_overlaps_the_next():
    a = Segment(id=0, start=0.0, end=0.2, text="Ha.", words=[Word(word="Ha.", start=0.0, end=0.2)])
    b = Segment(id=1, start=0.5, end=1.0, text="Albatta.", words=[Word(word="Albatta.", start=0.5, end=1.0)])
    cues = build_cues([a, b])
    assert cues[0].end == pytest.approx(0.46)  # wants 0.8 s, stops before the next cue
    lone = build_cues([a])
    assert lone[0].end == pytest.approx(0.8)


def test_webvtt_and_srt_rendering():
    s = seg("1 < 2 & 3 > 2.", 3725.5)
    cues = build_cues([s])
    vtt = to_webvtt(cues)
    assert vtt.startswith("WEBVTT\n\n01:02:05.500 --> ")
    assert "1 &lt; 2 &amp; 3 &gt; 2." in vtt
    srt = to_srt(cues)
    assert srt.startswith("1\n01:02:05,500 --> ") and "1 < 2 & 3 > 2." in srt


# --------------------------------------------------------------------------- engine output


def test_clean_segments_strips_clamps_dedupes_and_marks_questions():
    raw = [
        RawSegment(0.0, 1.0, " Salom. ", [RawWord(" Salom.", -0.2, 0.6, 0.91234)]),
        RawSegment(1.0, 2.0, " Salom. ", [RawWord(" Salom.", 1.0, 1.6, 0.9)]),  # repeat → dropped
        RawSegment(
            2.0,
            9.0,
            " Qanday   ishlaymiz? ",
            [
                RawWord(" Qanday", 2.5, 2.4, 0.8),
                RawWord(" ", 3.0, 3.1, 0.1),
                RawWord("ishlaymiz?", 2.0, 9.5, 0.7),
            ],
        ),
        RawSegment(9.0, 9.5, "   ", []),
    ]
    out = clean_segments(raw, duration=8.0)
    assert [s.text for s in out] == ["Salom.", "Qanday ishlaymiz?"]
    assert [s.id for s in out] == [0, 1]
    first = out[0].words[0]
    assert (first.word, first.start, first.probability) == ("Salom.", 0.0, 0.912)
    q = out[1]
    assert q.question and [w.word for w in q.words] == ["Qanday", "ishlaymiz?"]
    assert q.words[0].end >= q.words[0].start
    assert q.words[1].start >= q.words[0].start  # never runs backwards
    assert q.end <= 8.0


def test_build_transcript_fills_the_contract():
    result = EngineResult(
        language="uz",
        language_probability=0.87654,
        segments=[
            RawSegment(0.0, 1.0, "Salom dunyo.", [RawWord("Salom", 0.0, 0.4), RawWord(" dunyo.", 0.5, 1.0)])
        ],
    )
    t = build_transcript(
        result,
        route="faster-whisper:small",
        duration=3.0,
        language_forced=True,
        silences=[Silence(start=1.2, end=3.0)],
    )
    assert isinstance(t, Transcript)
    assert (t.language, t.language_probability, t.word_count, t.speech_seconds) == ("uz", 0.877, 2, 1.0)
    assert t.text == "Salom dunyo." and [w.word for w in t.words] == ["Salom", "dunyo."]
    assert t.cues[0].lines == ["Salom dunyo."]
    assert Transcript.model_validate_json(t.model_dump_json()) == t


def test_engine_routes():
    engine = engine_for("faster-whisper:small", models_dir="/nonexistent", threads=2, beam_size=5)
    assert engine.route == "faster-whisper:small"
    with pytest.raises(EngineUnavailable):
        engine_for("small", models_dir="/m", threads=1, beam_size=1)
    with pytest.raises(EngineUnavailable):
        engine_for("openai:whisper-1", models_dir="/m", threads=1, beam_size=1)


def test_missing_local_model_is_reported_not_downloaded(tmp_path):
    engine = FasterWhisperEngine("tiny", models_dir=tmp_path, threads=1)
    assert not engine.is_fetched()
    with pytest.raises(EngineUnavailable):
        engine.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language=None)
    assert not any(tmp_path.rglob("model.bin"))


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_load_pcm_gives_16k_mono_float(tmp_path):
    src = tmp_path / "tone.flac"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2",
         "-ac", "2", str(src)],
        check=True,
    )  # fmt: skip
    pcm = load_pcm(src, tmp_path)
    assert pcm.dtype == np.float32
    assert abs(len(pcm) - 2 * SAMPLE_RATE) < 400
    assert 0.05 < float(np.abs(pcm).max()) <= 1.0
    assert not (tmp_path / "speech.f32").exists()


# --------------------------------------------------------------------------- pipeline stage


def test_transcription_stage_state():
    from synthcut_core.stages import _transcription_state
    from synthcut_schemas.enums import StageStatus

    running = _transcription_state([("running", 1, 0), ("done", 1, 120), ("queued", 2, 0)], 4, True)
    assert (running.status, running.progress, running.detail) == (StageStatus.RUNNING, 0.25, "1/4 tayyor")
    assert _transcription_state([("queued", 2, 0)], 2, True).detail == "2 ta fayl navbatda"
    done = _transcription_state([("done", 2, 340), ("failed", 1, 0)], 3, True)
    assert (done.status, done.detail) == (StageStatus.DONE, "2 ta faylda nutq · 340 so'z, 1 ta o'qilmadi")
    assert _transcription_state([("failed", 1, 0)], 1, True).status is StageStatus.FAILED
    # Only silent files (images, mute video) once everything is ingested: nothing to transcribe.
    assert _transcription_state([], 0, True).status is StageStatus.SKIPPED
    # Files still uploading/ingesting may bring speech: keep waiting.
    assert _transcription_state([], 1, True).status is StageStatus.PENDING
    assert _transcription_state([], 0, False).status is StageStatus.PENDING


def test_detected_turkic_neighbour_resolves_to_the_preferred_language():
    from synthcut_speech.engines import resolve_language

    assert resolve_language("az", "uz") == "uz"  # the first real clip, heard by "small"
    assert resolve_language("kk", "uz") == "uz"
    assert resolve_language("ru", "uz") == "ru"  # not a neighbour: detection stands
    assert resolve_language("en", "uz") == "en"
    assert resolve_language("az", None) == "az"  # preference disabled
    assert resolve_language("uz", "uz") == "uz"


def test_uzbek_output_is_brought_to_uzbek_latin():
    from synthcut_speech.transcript import normalize_text

    # Lines from large-v3-turbo on the first real clip.
    assert (
        normalize_text("ana janim şirin, uçun, tarixı və gözəl", "uz")
        == "ana janim shirin, uchun, tarixi va go‘zal"
    )
    assert normalize_text("Şu ğalaba", "uz") == "Shu g‘alaba"
    assert normalize_text("şirin", "tr") == "şirin"  # other languages untouched
    raw = [RawSegment(0.0, 1.0, " Çünki şirin", [RawWord(" Çünki", 0.0, 0.4), RawWord(" şirin", 0.5, 1.0)])]
    [seg] = clean_segments(raw, 2.0, "uz")
    assert seg.text == "Chunki shirin" and [w.word for w in seg.words] == ["Chunki", "shirin"]


@pytest.mark.skipif(
    not HAS_FFMPEG or not (TINY / "model.bin").exists(), reason="needs ffmpeg and a tiny model"
)
def test_real_whisper_engine_end_to_end(tmp_path):
    """The fake engine in the integration tests never touches faster-whisper;
    this runs the real one (tiny model) on a synthetic English clip."""
    engine = FasterWhisperEngine(
        str(TINY), models_dir=tmp_path, threads=2, beam_size=1, preferred_language="uz"
    )
    pcm = load_pcm(FIXTURES / "speech_en.flac", tmp_path)
    progress: list[float] = []
    checks: list[int] = []
    result = engine.transcribe(
        pcm, language=None, on_progress=progress.append, check=lambda: checks.append(1)
    )
    assert result.language == "en" and result.language_probability  # no Turkic neighbour: detection stands
    t = build_transcript(
        result, route=engine.route, duration=len(pcm) / SAMPLE_RATE, language_forced=False, silences=[]
    )
    text = t.text.lower()
    assert "hello" in text and "test" in text
    assert t.word_count >= 8 and all(w.end >= w.start for w in t.words)
    assert progress and 0 < progress[-1] <= 1.0 and checks
    assert t.segments[-1].question  # "Can you hear me?"
    assert t.cues[0].start < 1.0


def test_a_snapshot_with_a_broken_weights_link_is_not_fetched(tmp_path):
    """Hugging Face snapshots are symlinks into a blob store; deleting the store
    (it happened while moving a model) must not look like an installed model."""
    repo = tmp_path / "models--Systran--faster-whisper-tiny"
    snap = repo / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("abc123")
    for name in ("config.json", "tokenizer.json", "vocabulary.txt"):
        (snap / name).write_text("{}")
    (snap / "model.bin").symlink_to("../../blobs/gone")
    engine = FasterWhisperEngine("tiny", models_dir=tmp_path, threads=1)
    assert not engine.is_fetched()
    (repo / "blobs").mkdir()
    (repo / "blobs" / "gone").write_bytes(b"\0" * (2 * 1024 * 1024))
    assert engine.is_fetched()


def test_a_sentence_end_is_not_orphaned_by_the_duration_limit():
    # From the first real clip: 8 words over 5.7 s, then "berildi." ending the sentence at 6.2 s.
    ws = words("1989 il, 21 akhtiyabir, uzbek tilida daulat tilida maqamu berildi.", 0.0, step=0.62)
    ws.append(Word(word="Bu", start=6.5, end=6.7))
    s = Segment(id=0, start=0.0, end=6.7, text="…", words=ws)
    cues = build_cues([s])
    assert cues[0].lines[-1].endswith("berildi.")
    assert cues[1].lines == ["Bu"]
