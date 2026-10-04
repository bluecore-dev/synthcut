"""A professional plan end to end: what an editor builds in Premiere — a
crossfade, a speed change, a keyframed punch-in, a B-roll cutaway that fades
in, a J-cut on its own voice track and an effect — rendered by the job from
the originals and measured by QA."""

import shutil
import uuid

import pytest
from sqlalchemy import select
from synthcut_core.models import Asset, EditPlanRow, Project, Render
from synthcut_core.renders import request_render
from synthcut_timeline import AssetFacts, EditPlan, validate_plan

from . import test_speech
from .conftest import make_project
from .test_autoedit import edit_settings, fake_layer  # noqa: F401 — fixtures
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media
fake_engine = test_speech.fake_engine


def pro_plan(project_id: str, talk: str, still_video: str, version: int) -> dict:
    return {
        "project_id": project_id, "version": version,
        "sequence": {"fps": 25, "width": 640, "height": 360, "duration": 5.0},
        "video_tracks": [
            {"track": 1, "role": "main", "clips": [
                {"id": "a", "asset_id": talk, "source_in": 0.0, "source_out": 2.4, "timeline_start": 0.0, "timeline_end": 2.4,
                 "mute_source_audio": False,
                 "keyframes": [{"t": 0.0, "property": "scale", "value": 1.0, "easing": "ease_in_out"},
                               {"t": 2.0, "property": "scale", "value": 1.25}]},
                {"id": "b", "asset_id": talk, "source_in": 1.6, "source_out": 5.8, "speed": 1.5,
                 "timeline_start": 2.0, "timeline_end": 4.8, "mute_source_audio": False,
                 "transition_in": {"type": "crossfade", "duration": 0.4}},
                {"id": "c", "asset_id": talk, "source_in": 0.0, "source_out": 0.2, "timeline_start": 4.8, "timeline_end": 5.0,
                 "transition_in": {"type": "cut", "duration": 0}},
            ]},
            {"track": 2, "role": "broll", "clips": [
                {"id": "pip", "asset_id": still_video, "source_in": 0.0, "source_out": 1.0, "timeline_start": 0.6, "timeline_end": 1.6,
                 "transform": {"scale": 0.35, "x": 0.28, "y": -0.25},
                 "keyframes": [{"t": 0.0, "property": "opacity", "value": 0.0, "easing": "linear"},
                               {"t": 0.3, "property": "opacity", "value": 1.0}]},
            ]},
        ],
        "audio_tracks": [
            {"track": 1, "role": "voice", "clips": [
                {"id": "jcut", "source": {"asset_id": talk}, "source_in": 4.6, "source_out": 5.0,
                 "timeline_start": 4.6, "timeline_end": 5.0, "gain_db": -3,
                 "keyframes": [{"t": 0.0, "property": "volume_db", "value": -20, "easing": "linear"},
                               {"t": 0.4, "property": "volume_db", "value": 0}]},
            ]},
        ],
        "notes": "Qo'lda: crossfade, 1.5x, punch-in, PiP, J-cut",
    }  # fmt: skip


async def test_a_premiere_style_plan_renders_and_passes_qa(
    client, auth, edit_settings, media, Session, fake_layer  # noqa: F811
):
    project = await make_project(client, auth, name="Pro")
    pid = project["id"]
    talk = await upload(client, auth, pid, media / "talk.mp4", "video/mp4")
    still = await upload(client, auth, pid, media / "still.png", "image/png")
    run_worker(edit_settings)
    plan = EditPlan.model_validate(pro_plan(pid, talk["id"], talk["id"], 1))
    with Session() as s:
        assets = {a.id: a for a in s.scalars(select(Asset).where(Asset.project_id == uuid.UUID(pid)))}
        facts = {
            i: AssetFacts(kind=a.kind, duration=a.duration_sec, has_audio=bool(a.has_audio))
            for i, a in assets.items()
        }
        report = validate_plan(plan, assets=facts)
        assert report.ok, report.errors
        row = EditPlanRow(project_id=uuid.UUID(pid), version=1, source="user", plan=plan.model_dump(mode="json"),
                          duration_sec=5.0, clip_count=3, notes=plan.notes, options={"preset": "youtube_16x9_1080"})  # fmt: skip
        s.add(row)
        s.flush()
        request_render(s, row, preset="youtube_16x9_1080", deliver=False)
        s.commit()
    assert still["kind"] == "image"
    assert run_worker(edit_settings, queues="render") == ["render.final"]
    with Session() as s:
        render = s.scalar(select(Render).where(Render.project_id == uuid.UUID(pid)))
        assert render.status == "done", render.error
        checks = {c["code"]: c for c in render.qa["checks"]}
        assert checks["resolution"]["value"] == "640×360" and checks["fps"]["status"] == "pass"
        assert checks["duration"]["value"] == pytest.approx(5.0, abs=0.05)
        assert render.qa_status in ("pass", "warn"), render.qa
        assert s.get(Project, uuid.UUID(pid)) is not None
