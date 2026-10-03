"""Phase 7: component props, captions on the output timeline, overlay/1."""

from itertools import pairwise

import pytest
from synthcut_schemas.speech import Segment, Transcript, Word
from synthcut_timeline import EditPlan, validate_plan
from synthcut_timeline.overlay import build_overlay, caption_lines, safe_zone, sfx_cues, timeline_words
from synthcut_timeline.registry import GRAPHICS_REGISTRY
from synthcut_timeline.schema import motion_schema

from .test_timeline import ASSETS, CLIP_A, CLIP_B, plan_dict


def transcript(words: list[tuple[str, float, float]]) -> Transcript:
    ws = [Word(word=t, start=s, end=e) for t, s, e in words]
    seg = Segment(id=0, start=ws[0].start, end=ws[-1].end, text=" ".join(t for t, _, _ in words), words=ws)
    return Transcript(engine="test:words", duration=60.0, segments=[seg])


# Clip A plays source 0.5–3.7 at 0–3.2; clip B plays source 1.0–3.8 at 3.2–6.0.
TRANSCRIPTS = {
    CLIP_A: transcript(
        [
            ("cut", 0.0, 0.4),  # before source_in: not in the edit
            ("Salom", 0.6, 1.0),
            ("do'stlar.", 1.1, 1.6),
            ("Bugun", 2.0, 2.3),
            ("montaj", 2.4, 2.8),
            ("haqida", 2.9, 3.3),
            ("gaplashamiz", 3.55, 4.0),  # straddles source_out: more than half outside
        ]
    ),
    CLIP_B: transcript([("Birinchi", 1.2, 1.6), ("qadam", 1.7, 2.0), ("tayyor", 2.1, 2.5)]),
}


def plan(**overrides) -> EditPlan:
    return EditPlan.model_validate(plan_dict(**overrides))


def test_words_follow_the_edit():
    words = [(n, w.text, w.start) for n, w in timeline_words(plan(), TRANSCRIPTS)]
    assert [t for _, t, _ in words] == [
        "Salom",
        "do'stlar.",
        "Bugun",
        "montaj",
        "haqida",
        "Birinchi",
        "qadam",
        "tayyor",
    ]
    assert words[0] == (0, "Salom", pytest.approx(0.1))  # 0.6 s in source - 0.5 in-point
    assert words[5] == (1, "Birinchi", pytest.approx(3.4))  # clip B starts at 3.2, source 1.2 - 1.0


def test_speed_ramps_compress_caption_time():
    data = plan_dict()
    data["video_tracks"][0]["clips"][1].update({"source_in": 1.0, "source_out": 6.6, "speed": 2.0})
    words = {w.text: w for _, w in timeline_words(EditPlan.model_validate(data), TRANSCRIPTS)}
    assert words["tayyor"].start == pytest.approx(3.2 + (2.1 - 1.0) / 2)


def test_caption_lines_break_at_sentences_cuts_and_word_limit():
    settings = plan().captions.model_copy(update={"max_words_per_line": 2})
    lines = caption_lines(plan(), TRANSCRIPTS, settings)
    assert [[w.text for w in line.words] for line in lines] == [
        ["Salom", "do'stlar."],  # sentence end
        ["Bugun", "montaj"],  # word limit
        ["haqida"],  # the cut ends the line
        ["Birinchi", "qadam"],
        ["tayyor"],
    ]
    # A one-word line is held for reading but never overlaps the next one.
    assert lines[2].end <= lines[3].start
    assert all(a.end <= b.start for a, b in pairwise(lines))


def test_overlay_normalises_props_and_frames():
    data = plan_dict()
    data["graphics"].append(
        {
            "id": "cta",
            "component": "CTA",
            "timeline_start": 4.0,
            "timeline_end": 6.0,
            "layer": 2,
            "props": {"text": "Obuna bo'ling", "enter": "none"},
        }
    )
    p = EditPlan.model_validate(data)
    assert validate_plan(p, assets=ASSETS).ok
    ov = build_overlay(p, TRANSCRIPTS)
    timer, cta = ov.items
    assert (timer.from_frame, timer.duration_frames) == (45, 120)  # 1.5–5.5 s at 30 fps
    assert timer.props["total_seconds"] == 4 and timer.props["enter"] == "pop"  # spec alias + defaults
    assert cta.props == {
        "enter": "none",
        "exit": "fade",
        "accent": None,
        "text": "Obuna bo'ling",
        "action": "subscribe",
        "handle": None,
        "position": "bottom",
    }
    assert ov.duration_in_frames == 180 and ov.captions.style == "dynamic"
    assert ov.safe_zone.bottom == 0.22  # 1080×1920
    assert sfx_cues(p) == [(1.5, "sfx/tick")]  # the CTA enters without a sound
    assert build_overlay(p).captions is None  # no transcripts → no captions


def test_safe_zones_per_aspect():
    assert safe_zone(1080, 1920).right > safe_zone(1080, 1920).left  # the like/comment column
    assert safe_zone(1080, 1080).bottom == 0.12
    assert safe_zone(1920, 1080).bottom == 0.08


@pytest.mark.parametrize(
    ("component", "props"),
    [
        ("QuizCard", {"question": "2+2?", "options": ["3", "4"], "correct_index": 2}),
        ("Highlight", {"region": {"x": 0.8, "y": 0.1, "width": 0.4, "height": 0.2}}),
        ("TitleCard", {"title": "x" * 61}),
        ("GamifiedTimer", {"total_seconds": 30, "colour": "red"}),
    ],
)
def test_bad_props_are_rejected_by_the_plan_validator(component, props):
    data = plan_dict()
    data["graphics"] = [
        {"id": "g", "component": component, "timeline_start": 1, "timeline_end": 3, "props": props}
    ]
    assert validate_plan(EditPlan.model_validate(data), assets=ASSETS).codes() == {"E_COMPONENT_PROPS"}


def test_every_component_is_typed_and_exported():
    schema = motion_schema()
    assert all(spec.props_model is not None for spec in GRAPHICS_REGISTRY.values())
    assert set(schema["$defs"]["ComponentProps"]["properties"]) == set(GRAPHICS_REGISTRY)
    assert "OverlayProps" in schema["$defs"]
