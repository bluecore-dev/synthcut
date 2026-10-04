"""The rule-based editor ("Tez montaj"): pauses, bad shots, B-roll, target
duration and reframing — every plan it makes must pass the validator."""

from uuid import UUID, uuid4

import pytest
from synthcut_schemas.analysis import ClipAnalysis, Exposure, Face, Motion
from synthcut_schemas.grade import ColorGrade, MixPlan
from synthcut_schemas.speech import Segment, Transcript, Word
from synthcut_timeline import AssetFacts, CaptionTrack, validate_plan
from synthcut_timeline.autoedit import Options, Source, build_plan, reframe

PROJECT = UUID("00000000-0000-4000-8000-000000000001")
REELS = dict(width=1080, height=1920, fps=30)


def words(*spans: tuple[float, float]) -> Transcript:
    ws = [Word(word=f"w{i}", start=a, end=b) for i, (a, b) in enumerate(spans)]
    seg = Segment(id=0, start=ws[0].start, end=ws[-1].end, text=" ".join(w.word for w in ws), words=ws)
    return Transcript(engine="test", duration=60.0, segments=[seg])


def shot(
    start: float, end: float, *, flags=(), usable=0.8, face: tuple[float, float] | None = None
) -> ClipAnalysis:
    return ClipAnalysis(
        clip_id=f"x-s{int(start)}",
        index=int(start),
        start=start,
        end=end,
        duration=end - start,
        faces=[Face(x=face[0], y=face[1], height=0.3, score=0.9)] if face else [],
        sharpness=0.7,
        exposure=Exposure(mean=0.45, dark=0.0, bright=0.0),
        motion=Motion(speed=0.0, shake=0.0, dx=0.0, dy=0.0),
        camera_quality=0.8,
        lighting_quality=0.8,
        usable_score=usable,
        flags=list(flags),
    )


def source(duration=20.0, *, w=1080, h=1920, transcript=None, clips=(), grade=None, has_audio=True) -> Source:
    return Source(
        asset_id=uuid4(),
        name="clip.mov",
        duration=duration,
        width=w,
        height=h,
        transcript=transcript,
        clips=list(clips),
        grade=grade,
        has_audio=has_audio,
    )


def plan_for(sources, **opts):
    options = Options(**{**REELS, **opts})
    plan = build_plan(project_id=PROJECT, version=1, sources=sources, opts=options, mix=MixPlan())
    facts = {
        s.asset_id: AssetFacts(kind="video", duration=s.duration, has_audio=s.has_audio) for s in sources
    }
    report = validate_plan(plan, assets=facts)
    assert report.ok, report.errors
    assert not report.warnings, report.warnings  # every boundary on the frame grid
    return plan


def kept(plan) -> list[tuple[float, float]]:
    return [(c.source_in, c.source_out) for c in plan.video_tracks[0].clips]


def test_pauses_become_jump_cuts_with_air_around_phrases():
    # Two phrases separated by a 3 s pause; a 0.3 s breath inside the first stays.
    s = source(transcript=words((1.0, 1.5), (1.8, 2.6), (5.6, 6.0), (6.1, 7.0)))
    plan = plan_for([s])
    assert kept(plan) == [(pytest.approx(0.9, abs=0.04), pytest.approx(2.7333, abs=0.04)),
                          (pytest.approx(5.4667, abs=0.04), pytest.approx(7.1333, abs=0.04))]  # fmt: skip
    assert plan.sequence.duration == pytest.approx(sum(b - a for a, b in kept(plan)), abs=1e-6)
    assert "Pauzalar kesildi" in plan.notes
    whole = plan_for([s], remove_pauses=False)
    assert len(whole.video_tracks[0].clips) == 1  # one take, edges trimmed only


def test_black_and_frozen_shots_are_cut_out_of_speech():
    s = source(
        transcript=words((0.5, 4.5), (4.6, 9.5)),
        clips=[shot(0, 3), shot(3, 5, flags=["frozen"]), shot(5, 10)],
    )
    plan = plan_for([s])
    for a, b in kept(plan):
        assert b <= 3.0 + 1e-6 or a >= 5.0 - 1e-6  # nothing from the frozen shot
    assert "qotgan" in plan.notes


def test_footage_without_speech_gives_its_usable_shots_as_broll():
    talk = source(transcript=words((0.2, 3.0)))
    broll = source(
        has_audio=False,
        clips=[shot(0, 6), shot(6, 7.5, usable=0.1), shot(7.5, 9, flags=["duplicate"]), shot(9, 14)],
    )
    plan = plan_for([talk, broll])
    clips = plan.video_tracks[0].clips
    assert [c.asset_id for c in clips] == [talk.asset_id, broll.asset_id, broll.asset_id]
    assert [round(c.source_out - c.source_in, 2) for c in clips[1:]] == [3.0, 3.0]  # middle 3 s of each
    assert clips[1].mute_source_audio and not clips[0].mute_source_audio


def test_target_duration_stops_on_a_phrase_boundary():
    phrases = [(i * 4.0, i * 4.0 + 3.0) for i in range(6)]  # 6 phrases of ~3.2 s
    plan = plan_for([source(duration=30, transcript=words(*phrases))], target_duration=10)
    assert plan.sequence.duration <= 10 + 1e-6
    assert plan.sequence.duration > 6  # stopped at a boundary, not at the first phrase
    last = plan.video_tracks[0].clips[-1]
    assert last.source_out == pytest.approx(phrases[len(plan.video_tracks[0].clips) - 1][1] + 0.12, abs=0.04)
    assert "Maqsadli davomiylik" in plan.notes


def test_reframe_keeps_the_face_in_a_vertical_crop_of_landscape_footage():
    s = source(w=1920, h=1080, clips=[shot(0, 10, face=(0.75, 0.4))])
    t, effects = reframe(s, Options(**REELS), 5.0)
    assert effects == []
    # Cover: 1080x1920 from 3413x1920 — the face at 75 % moves to the centre.
    scaled = 1920 * 1920 / 1080
    assert t.x == pytest.approx(-(0.75 - 0.5) * scaled / 1080, abs=1e-3)
    far = source(w=1920, h=1080, clips=[shot(0, 10, face=(0.99, 0.4))])
    slack = (scaled - 1080) / 2 / 1080
    assert reframe(far, Options(**REELS), 5.0)[0].x == pytest.approx(-slack, abs=1e-3)  # clamped: no border
    assert reframe(source(w=1920, h=1080), Options(**REELS), 5.0)[0].x == 0  # no face: centre


def test_vertical_footage_in_a_landscape_frame_is_fitted_over_a_blur():
    s = source(w=1080, h=1920)
    t, effects = reframe(s, Options(width=1920, height=1080, fps=30), 1.0)
    assert t.scale == pytest.approx((1080 / 1920) / (1920 / 1080), abs=1e-3)
    assert effects[0].type == "background" and effects[0].params == {"fill": "blur"}
    square, fx = reframe(source(w=1080, h=1920, clips=[shot(0, 9, face=(0.5, 0.25))]),
                         Options(width=1080, height=1080, fps=30), 1.0)  # fmt: skip
    assert fx == [] and square.y > 0  # cropped, moved down so the face keeps its headroom


def test_grades_titles_and_captions_ride_along():
    grade = ColorGrade(exposure=0.4)
    plan = plan_for(
        [source(transcript=words((0.0, 8.0)), grade=grade)],
        title="Montaj sirlari",
        cta="Obuna bo'ling",
        captions=CaptionTrack(style="karaoke"),
    )
    clip = plan.video_tracks[0].clips[0]
    assert clip.effects[-1].type == "grade" and clip.effects[-1].params["exposure"] == 0.4
    assert [g.component for g in plan.graphics] == ["TitleCard", "CTA"]
    assert plan.graphics[1].timeline_end == plan.sequence.duration
    assert plan.captions.style == "karaoke"
    assert plan.metadata["created_by"] == "rules" and plan.metadata["mix"]["schema_version"] == "mix/1"


def test_nothing_usable_is_an_error_not_an_empty_plan():
    dead = source(has_audio=False, clips=[shot(0, 5, flags=["black"]), shot(5, 9, usable=0.1)])
    with pytest.raises(ValueError, match="yaroqli"):
        build_plan(project_id=PROJECT, version=1, sources=[dead], opts=Options(**REELS))
