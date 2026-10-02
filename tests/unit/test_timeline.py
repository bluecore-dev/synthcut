import uuid

import pytest
from pydantic import ValidationError
from synthcut_timeline import (
    AssetFacts,
    EditPlan,
    PlanValidationError,
    UnknownSchemaVersionError,
    ensure_valid,
    load_plan,
    snap_to_frames,
    validate_plan,
)

PROJECT = uuid.uuid4()
CLIP_A = uuid.uuid4()
CLIP_B = uuid.uuid4()
MUSIC = uuid.uuid4()
ASSETS = {
    CLIP_A: AssetFacts(kind="video", duration=12.0),
    CLIP_B: AssetFacts(kind="video", duration=6.0),
    MUSIC: AssetFacts(kind="audio", duration=180.0),
}


def plan_dict(**overrides):
    """The spec §23 example, completed so the main track covers the sequence."""
    data = {
        "project_id": str(PROJECT),
        "version": 1,
        "sequence": {"fps": 30, "width": 1080, "height": 1920, "duration": 6.0},
        "video_tracks": [
            {
                "track": 1,
                "clips": [
                    {
                        "id": "clip_001",
                        "asset_id": str(CLIP_A),
                        "source_in": 0.5,
                        "source_out": 3.7,
                        "timeline_start": 0,
                        "timeline_end": 3.2,
                        "transform": {"scale": 1.15},
                    },
                    {
                        "id": "clip_002",
                        "asset_id": str(CLIP_B),
                        "source_in": 1.0,
                        "source_out": 3.8,
                        "timeline_start": 3.2,
                        "timeline_end": 6.0,
                    },
                ],
            }
        ],
        "audio_tracks": [
            {
                "track": 2,
                "role": "music",
                "ducking": {"amount_db": -14},
                "clips": [
                    {
                        "id": "music_1",
                        "source": {"asset_id": str(MUSIC)},
                        "source_in": 10,
                        "source_out": 16,
                        "timeline_start": 0,
                        "timeline_end": 6.0,
                        "gain_db": -8,
                        "fade_out": 1.0,
                    }
                ],
            }
        ],
        "graphics": [
            {
                "id": "timer",
                "component": "GamifiedTimer",
                "timeline_start": 1.5,
                "timeline_end": 5.5,
                "props": {"totalTime": 4},
            }
        ],
        "captions": {"enabled": True, "style": "dynamic"},
    }
    data.update(overrides)
    return data


def codes(data, assets=ASSETS):
    return validate_plan(EditPlan.model_validate(data), assets=assets).codes()


def test_spec_example_is_valid():
    report = validate_plan(EditPlan.model_validate(plan_dict()), assets=ASSETS)
    assert report.ok, report.issues


def test_overlap_on_a_track_is_an_error():
    d = plan_dict()
    d["video_tracks"][0]["clips"][1]["timeline_start"] = 3.0
    d["video_tracks"][0]["clips"][1]["source_out"] = 4.0
    assert "E_OVERLAP" in codes(d)


def test_crossfade_allows_matching_overlap():
    d = plan_dict()
    clip = d["video_tracks"][0]["clips"][1]
    clip.update(timeline_start=2.7, source_out=4.3, transition_in={"type": "crossfade", "duration": 0.5})
    assert "E_OVERLAP" not in codes(d)


def test_gap_on_main_track_would_render_black():
    d = plan_dict()
    clip = d["video_tracks"][0]["clips"][1]
    clip.update(timeline_start=3.5, source_out=3.5)
    assert "E_MAIN_GAP" in codes(d)


def test_main_track_must_cover_sequence():
    d = plan_dict()
    d["sequence"]["duration"] = 8.0
    assert "E_MAIN_COVERAGE" in codes(d)


def test_duration_mismatch_detected_and_speed_respected():
    d = plan_dict()
    d["video_tracks"][0]["clips"][0]["source_out"] = 5.0  # 4.5s of source into 3.2s
    assert "E_DURATION_MISMATCH" in codes(d)
    d["video_tracks"][0]["clips"][0].update(source_out=0.5 + 3.2 * 1.5, speed=1.5)
    assert "E_DURATION_MISMATCH" not in codes(d)


def test_unknown_asset_and_reading_past_media_end():
    d = plan_dict()
    d["video_tracks"][0]["clips"][0]["asset_id"] = str(uuid.uuid4())
    d["video_tracks"][0]["clips"][1].update(source_in=4.0, source_out=6.8)  # CLIP_B is 6.0s long
    found = codes(d)
    assert {"E_UNKNOWN_ASSET", "E_SOURCE_RANGE"} <= found


def test_audio_asset_on_video_track_rejected():
    d = plan_dict()
    d["video_tracks"][0]["clips"][0]["asset_id"] = str(MUSIC)
    assert "E_ASSET_KIND" in codes(d)


def test_unknown_motion_component_rejected():
    d = plan_dict()
    d["graphics"][0]["component"] = "InventedWidget"
    assert "E_UNKNOWN_COMPONENT" in codes(d)


def test_duplicate_ids_and_tracks():
    d = plan_dict()
    d["graphics"][0]["id"] = "clip_001"
    d["video_tracks"].append({"track": 1, "role": "overlay", "clips": []})
    assert {"E_DUPLICATE_ID", "E_DUPLICATE_TRACK"} <= codes(d)


def test_off_frame_times_warn_and_snap_fixes_them():
    d = plan_dict()
    d["graphics"][0]["timeline_start"] = 1.517
    d["video_tracks"][0]["clips"][0].update(timeline_end=3.21, source_out=3.71)
    d["video_tracks"][0]["clips"][1].update(timeline_start=3.21, source_out=3.79)
    plan = EditPlan.model_validate(d)
    assert "W_FRAME_ALIGNMENT" in validate_plan(plan).codes()
    snapped = snap_to_frames(plan)
    assert "W_FRAME_ALIGNMENT" not in validate_plan(snapped).codes()
    assert snapped.video_tracks[0].clips[0].timeline_end == pytest.approx(3.2)


def test_structural_errors_are_rejected_by_the_schema():
    for bad in (
        {"sequence": {"fps": 29, "width": 1080, "height": 1920, "duration": 5}},
        {"sequence": {"fps": 30, "width": 1081, "height": 1920, "duration": 5}},
        {"unknown_field": 1},
    ):
        with pytest.raises(ValidationError):
            EditPlan.model_validate(plan_dict(**bad))
    d = plan_dict()
    d["video_tracks"][0]["clips"][0]["source_out"] = 0.1  # before source_in
    with pytest.raises(ValidationError):
        EditPlan.model_validate(d)


def test_ensure_valid_raises_with_report():
    d = plan_dict()
    d["graphics"][0]["component"] = "Nope"
    with pytest.raises(PlanValidationError) as exc:
        ensure_valid(EditPlan.model_validate(d), assets=ASSETS)
    assert "E_UNKNOWN_COMPONENT" in exc.value.report.codes()


def test_versioned_loading():
    assert load_plan(plan_dict()).schema_version == "editplan/1"
    with pytest.raises(UnknownSchemaVersionError):
        load_plan(plan_dict(schema_version="editplan/0"))
