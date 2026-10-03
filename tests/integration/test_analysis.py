"""Phase 5a end to end: ingestion queues shot analysis, the worker measures
every shot of the proxy, and the API serves the records and their sheets
(spec §12). Order on the cpu queue: ingest → analysis → transcription."""

import shutil
import subprocess
import uuid

import httpx
import pytest
from sqlalchemy import select
from synthcut_core.models import AssetAnalysis, ClipAnalysisRow, Event, Job, ProjectStage
from synthcut_worker.speech import jobs as speech_jobs

from .conftest import SECOND_USER, login, make_project
from .test_ingest import run_worker, upload
from .test_speech import FakeEngine

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("analysis-media")
    # Two scenes: a steady test card, then a fast pan across a fractal.
    ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(d / "a.mp4"))  # fmt: skip
    ff("-f", "lavfi", "-i", "mandelbrot=s=2560x720:r=25", "-t", "3", "-vf", "crop=1280:720:x='t*300':y=0",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "b.mp4"))  # fmt: skip
    (d / "list.txt").write_text(f"file {d / 'a.mp4'}\nfile {d / 'b.mp4'}\n")
    ff("-f", "concat", "-safe", "0", "-i", str(d / "list.txt"),
       "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=6",
       "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       str(d / "reel.mp4"))  # fmt: skip
    # Same framing, different bytes (identical files are refused as already uploaded).
    ff("-i", str(d / "reel.mp4"), "-c:v", "libx264", "-crf", "30", "-c:a", "copy", str(d / "reel_take2.mp4"))
    ff("-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=3", str(d / "voice.wav"))
    return d


@pytest.fixture
def analysis_settings(settings):
    return settings.model_copy(update={"analysis_auto": True})


async def test_ingestion_queues_analysis_and_the_api_serves_clips(
    client, auth, analysis_settings, media, Session
):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "reel.mp4", "video/mp4")
    assert run_worker(analysis_settings) == ["ingest.asset", "analysis.asset"]

    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    summary = detail["analysis"]
    assert summary["status"] == "done" and summary["source"] == "metrics"
    shots = detail["shots"]
    assert summary["clip_count"] == len(shots) == 2
    assert detail["analysis_status"] == "done" and detail["clip_count"] == 2
    assert "clips" not in {f["kind"] for f in detail["files"]}

    clips = (await client.get(f"/api/v1/assets/{asset['id']}/clips", headers=auth)).json()["items"]
    assert [c["clip_id"] for c in clips] == [f"{asset['id'][:8]}-s000", f"{asset['id'][:8]}-s001"]
    card, pan = clips
    assert card["schema_version"] == "clipanalysis/1" and card["asset_name"] == "reel.mp4"
    assert pan["camera_motion"] == "pan_right"
    assert card["audio_present"] and card["resolution"] == "1280x720"
    assert 0 <= card["usable_score"] <= 1 and card["semantic_description"] is None
    async with httpx.AsyncClient() as s3:
        sheet = await s3.get(card["sheet"]["url"])
        assert sheet.status_code == 200 and sheet.content[:2] == b"\xff\xd8"

    everything = (await client.get(f"/api/v1/projects/{project['id']}/clips", headers=auth)).json()["items"]
    assert len(everything) == 2
    strict = await client.get(f"/api/v1/projects/{project['id']}/clips?min_usable=1.01", headers=auth)
    assert strict.status_code == 422
    none = (await client.get(f"/api/v1/projects/{project['id']}/clips?min_usable=1", headers=auth)).json()
    assert all(c["usable_score"] >= 1 for c in none["items"])

    pid = uuid.UUID(project["id"])
    with Session() as s:
        stage = s.get(ProjectStage, (pid, "analysis"))
        assert stage.status == "done" and stage.detail == "1 ta video · 2 ta kadr"
        assert "analysis.ready" in set(s.scalars(select(Event.type).where(Event.project_id == pid)))
        rows = list(s.scalars(select(ClipAnalysisRow).where(ClipAnalysisRow.project_id == pid)))
        assert len(rows) == 2 and all(r.dhash and r.sheet_key for r in rows)


async def test_order_is_ingest_then_analysis_then_speech(client, auth, settings, media, monkeypatch):
    monkeypatch.setattr(speech_jobs, "engine_for", lambda *a, **k: FakeEngine())
    both = settings.model_copy(update={"analysis_auto": True, "speech_auto": True})
    project = await make_project(client, auth)
    await upload(client, auth, project["id"], media / "reel.mp4", "video/mp4")
    await upload(client, auth, project["id"], media / "reel_take2.mp4", "video/mp4")
    ran = run_worker(both)
    assert ran == [
        "ingest.asset",
        "ingest.asset",
        "analysis.asset",
        "analysis.asset",
        "speech.transcribe",
        "speech.transcribe",
    ]


async def test_a_retake_is_flagged_as_duplicate_of_the_first(client, auth, analysis_settings, media):
    project = await make_project(client, auth)
    first = await upload(client, auth, project["id"], media / "reel.mp4", "video/mp4")
    run_worker(analysis_settings)
    second = await upload(client, auth, project["id"], media / "reel_take2.mp4", "video/mp4")
    run_worker(analysis_settings)
    clips = (await client.get(f"/api/v1/assets/{second['id']}/clips", headers=auth)).json()["items"]
    assert [c["duplicate_of"] for c in clips] == [f"{first['id'][:8]}-s000", f"{first['id'][:8]}-s001"]
    assert all("duplicate" in c["flags"] for c in clips)


async def test_reanalyze_and_projects_without_video(client, auth, analysis_settings, media, Session):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "reel.mp4", "video/mp4")
    run_worker(analysis_settings)
    url = f"/api/v1/assets/{asset['id']}/analyze"
    r = await client.post(url, headers=auth)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert (await client.post(url, headers=auth)).status_code == 202  # a double tap queues once
    assert run_worker(analysis_settings) == ["analysis.asset"]
    with Session() as s:
        row = s.scalar(select(AssetAnalysis).where(AssetAnalysis.asset_id == uuid.UUID(asset["id"])))
        assert (row.status, row.runs, row.clip_count) == ("done", 2, 2)
        assert s.query(ClipAnalysisRow).filter_by(asset_id=uuid.UUID(asset["id"])).count() == 2  # replaced
        keys = list(s.scalars(select(Job.idempotency_key).where(Job.kind == "analysis.asset")))
        assert f"analysis.asset:{asset['id']}:r2" in keys

    audio_only = await make_project(client, auth, name="Podkast")
    voice = await upload(client, auth, audio_only["id"], media / "voice.wav", "audio/wav")
    assert run_worker(analysis_settings) == ["ingest.asset"]
    with Session() as s:
        stage = s.get(ProjectStage, (uuid.UUID(audio_only["id"]), "analysis"))
        assert (stage.status, stage.detail) == ("skipped", "Video fayl yo'q")
    r = await client.post(f"/api/v1/assets/{voice['id']}/analyze", headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_analyzable"


async def test_clips_are_owner_scoped(client, auth, analysis_settings, media):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "reel.mp4", "video/mp4")
    run_worker(analysis_settings)
    other = await login(client, SECOND_USER)
    assert (await client.get(f"/api/v1/assets/{asset['id']}/clips", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{project['id']}/clips", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/assets/{asset['id']}/analyze", headers=other)).status_code == 404
