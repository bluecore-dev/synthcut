"""Agent edits → valid plans: the story in order becomes a frame-exact main
track with transitions, keyframes and inherited framing / colour; overlays,
graphics, captions and the music bed follow; every result validates."""

from uuid import UUID, uuid4

import pytest
from synthcut_agents.runtime.planedit import PlanEdit, apply_edit, summary
from synthcut_schemas.grade import ColorGrade
from synthcut_schemas.speech import Segment, Transcript, Word
from synthcut_timeline import AssetFacts, validate_plan
from synthcut_timeline.autoedit import Music, Options, Source, build_plan

PROJECT = UUID(int=7)
TALK, BROLL, SONG = uuid4(), uuid4(), uuid4()
DUR = {TALK: 30.0, BROLL: 12.0, SONG: 20.0}
FACTS = {
    TALK: AssetFacts("video", 30.0),
    BROLL: AssetFacts("video", 12.0, has_audio=False),
    SONG: AssetFacts("audio", 20.0),
}


def base_plan():
    ws = [Word(word=f"w{i}", start=i * 2.0, end=i * 2.0 + 1.5) for i in range(10)]
    t = Transcript(engine="t", duration=30, segments=[Segment(id=0, start=0, end=19.5, text="x", words=ws)])
    talk = Source(asset_id=TALK, name="talk.mov", duration=30, width=1920, height=1080, transcript=t,
                  grade=ColorGrade(exposure=0.3))  # fmt: skip
    opts = Options(width=1080, height=1920, fps=30)
    return build_plan(project_id=PROJECT, version=1, sources=[talk], opts=opts,
                      music=Music(asset_id=SONG, name="fon.mp3", duration=20.0))  # fmt: skip


def edit(**kw) -> PlanEdit:
    return PlanEdit.model_validate({"notes": "Hook boshiga olindi", **kw})


def check(plan):
    report = validate_plan(plan, assets=FACTS)
    assert report.ok, report.errors
    return plan


def test_the_story_in_order_becomes_a_frame_exact_main_track():
    base = base_plan()
    plan = check(apply_edit(base, edit(main=[
        {"asset_id": str(TALK), "source_in": 8.0, "source_out": 9.6, "why": "hook"},
        {"asset_id": str(TALK), "source_in": 0.0, "source_out": 3.5, "transition": {"type": "crossfade", "duration": 0.4}},
        {"asset_id": str(TALK), "source_in": 4.0, "source_out": 7.0, "speed": 1.5,
         "keyframes": [{"t": 0, "property": "scale", "value": 1.0}, {"t": 1.5, "property": "scale", "value": 1.15}]},
    ]), version=2, durations=DUR, agent="editor"))  # fmt: skip
    main = plan.video_tracks[0].clips
    assert [c.timeline_start for c in main] == [0.0, pytest.approx(1.2), pytest.approx(4.7)]
    assert main[1].transition_in.type == "crossfade" and main[1].transition_in.duration == pytest.approx(0.4)
    assert main[2].timeline_duration == pytest.approx(2.0) and main[2].speed == 1.5
    assert plan.sequence.duration == main[-1].timeline_end
    # framing and colour of the asset come from the base plan
    assert main[0].transform == base.video_tracks[0].clips[0].transform
    assert any(e.type == "grade" and e.params["exposure"] == 0.3 for e in main[0].effects)
    assert main[0].metadata["why"] == "hook" and plan.metadata["created_by"] == "editor"
    # the music bed is rebuilt for the new length
    music = plan.audio_tracks[0]
    assert music.role == "music" and music.clips[-1].timeline_end == pytest.approx(plan.sequence.duration)
    assert "3 bo'lak" in summary(plan) and "1 o'tish" in summary(plan)


def test_cutaways_pip_graphics_and_captions():
    base = base_plan()
    plan = check(apply_edit(base, edit(
        main=[{"asset_id": str(TALK), "source_in": 0.0, "source_out": 10.0}],
        overlays=[
            {"asset_id": str(BROLL), "source_in": 2.0, "source_out": 4.0, "at": 3.0, "why": "mahsulot"},
            {"asset_id": str(BROLL), "source_in": 6.0, "source_out": 7.5, "at": 6.0, "kind": "pip", "fade_in": 0, "fade_out": 0},
        ],
        graphics=[{"component": "TitleCard", "start": 0, "end": 2.5, "props": {"title": "Sinov"}},
                  {"component": "CTA", "start": 8, "end": 12, "props": {"text": "Obuna bo'ling"}}],
        captions={"enabled": True, "style": "bold", "position": "center"},
    ), version=3, durations=DUR, agent="editor"))  # fmt: skip
    cut, pip = plan.video_tracks[1].clips
    assert cut.transform.scale == 1.0 and [k.value for k in cut.keyframes] == [0.0, 1.0, 1.0, 0.0]
    assert pip.transform.scale == 0.35 and pip.keyframes == []
    assert plan.graphics[1].timeline_end == plan.sequence.duration  # clamped to the cut
    assert plan.captions.style == "bold" and plan.captions.position == "center"


def test_sections_left_out_are_kept_and_empty_lists_clear():
    base = base_plan()
    kept = check(
        apply_edit(base, edit(captions={"enabled": False}), version=2, durations=DUR, agent="motion")
    )
    assert kept.video_tracks[0].clips == base.video_tracks[0].clips and kept.captions is None
    cleared = check(apply_edit(base, edit(graphics=[]), version=3, durations=DUR, agent="motion"))
    assert cleared.graphics == []


def test_invalid_edits_are_reported_not_saved():
    base = base_plan()
    with pytest.raises(ValueError, match="shorter than a frame"):
        apply_edit(base, edit(main=[{"asset_id": str(TALK), "source_in": 5.0, "source_out": 5.01}]), version=2,
                   durations=DUR, agent="editor")  # fmt: skip
    bad = apply_edit(base, edit(main=[{"asset_id": str(TALK), "source_in": 0, "source_out": 4},
                                      {"asset_id": str(TALK), "source_in": 4, "source_out": 8, "transition": {"type": "zoom", "duration": 1.0}}],
                                overlays=[{"asset_id": str(BROLL), "source_in": 0, "source_out": 2, "at": 3.5}]),
                     version=2, durations=DUR, agent="editor")  # fmt: skip
    codes = {i.code for i in validate_plan(bad, assets=FACTS).errors}
    assert (
        "E_TRANSITION_SPLIT" in codes
    )  # the overlay starts inside the zoom: the agent hears it and fixes it
    long = apply_edit(base, edit(main=[{"asset_id": str(TALK), "source_in": 25, "source_out": 40}]), version=2,
                      durations=DUR, agent="editor")  # fmt: skip
    assert long.video_tracks[0].clips[0].source_out == pytest.approx(30.0)  # capped at the asset's end


def test_graphics_carry_keyframes_like_after_effects():
    base = base_plan()
    plan = check(apply_edit(base, edit(graphics=[{
        "component": "TitleCard", "start": 0.5, "end": 3.0, "props": {"title": "Sinov"},
        "keyframes": [{"t": 0, "property": "x", "value": -0.4, "easing": "ease_out"},
                      {"t": 0.6, "property": "x", "value": 0.0},
                      {"t": 9.0, "property": "opacity", "value": 0.0}],
    }]), version=2, durations=DUR, agent="motion"))  # fmt: skip
    keys = plan.graphics[0].keyframes
    assert [k.property for k in keys] == ["x", "x", "opacity"] and keys[0].easing == "ease_out"
    assert keys[-1].t == pytest.approx(2.5)  # clamped to the graphic's length
