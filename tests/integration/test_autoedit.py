"""Tez montaj end to end: ready material → rule-based EditPlan (versioned) →
final render from the original with real FFmpeg → QA on the file → the
video sent to the owner's chat. Remotion is replaced by FFmpeg-made
transparent frames (the real renderer is tested in tests/unit); Telegram by
an httpx mock transport."""

import os
import shutil
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, update
from synthcut_core.models import EditPlanRow, Event, Job, ProjectStage, Render
from synthcut_media import normalize, run_ffprobe
from synthcut_worker.delivery import notify
from synthcut_worker.render import final as final_jobs

from . import test_motion, test_speech
from .conftest import SECOND_USER, login, make_project
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media
fake_engine = test_speech.fake_engine
SFX_DIR = Path(os.environ.get("SYNTHCUT_SFX_DIR") or Path(__file__).resolve().parents[2] / "assets" / "sfx")


@pytest.fixture
def edit_settings(settings):
    return settings.model_copy(
        update={
            "speech_auto": True,
            "analysis_auto": True,
            "sfx_dir": str(SFX_DIR),
            "public_base_url": "https://synthcut.example",
        }
    )


@pytest.fixture
def fake_layer(monkeypatch, fake_engine):
    rendered = []

    def render(props, work, **kwargs):
        rendered.append(props)
        return test_motion.transparent_frames(props, work, **kwargs)

    monkeypatch.setattr(final_jobs, "render_overlay", render)
    return rendered


@pytest.fixture
def telegram(monkeypatch):
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    monkeypatch.setattr(
        notify, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return sent


async def test_tez_montaj_end_to_end(client, auth, edit_settings, media, Session, fake_layer, telegram):
    project = await make_project(client, auth)
    pid = project["id"]
    await upload(client, auth, pid, media / "talk.mp4", "video/mp4")
    url = f"/api/v1/projects/{pid}/auto-edit"

    early = await client.post(url, json={}, headers=auth)
    assert early.status_code == 409 and early.json()["error"]["code"] == "ingest_running"
    assert run_worker(edit_settings) == ["ingest.asset", "analysis.asset", "speech.transcribe"]

    body = {"captions": "karaoke", "title": "Sinov", "loudness": "podcast", "deliver": True}
    r = await client.post(url, json=body, headers=auth)
    assert r.status_code == 202 and r.json()["job"]["status"] == "queued"
    again = await client.post(url, json={"captions": "off"}, headers=auth)
    assert again.json()["job"]["id"] == r.json()["job"]["id"]  # one request at a time

    assert run_worker(edit_settings) == ["edit.auto"]
    state = (await client.get(f"/api/v1/projects/{pid}/edit", headers=auth)).json()
    assert state["plan"]["version"] == 1 and state["plan"]["source"] == "rules"
    assert state["render"]["status"] == "queued" and state["render"]["preset"] == "reels_9x16"

    plan = (await client.get(f"/api/v1/projects/{pid}/plans/1", headers=auth)).json()
    assert (plan["width"], plan["height"], plan["fps"]) == (1080, 1920, 30)
    assert plan["captions"] == "karaoke" and plan["loudness_lufs"] == -16
    assert [g["component"] for g in plan["graphics"]] == ["TitleCard"]
    # Speech 0.2–1.5 and 2.0–3.0 with a 0.5 s pause: one phrase kept whole (pause < 0.6 s).
    assert len(plan["clips"]) == 1 and plan["clips"][0]["source_in"] == pytest.approx(0.0667, abs=0.04)
    assert plan["clips"][0]["source_out"] == pytest.approx(3.1333, abs=0.04)
    assert plan["clips"][0]["reframed"] is False  # testsrc has no face: centre crop

    assert run_worker(edit_settings, queues="render") == ["render.final"]
    assert (SFX_DIR / "whoosh.flac").exists()  # the title's sound effect really was mixed in
    props = fake_layer[0]
    assert (props.width, props.height, props.fps) == (1080, 1920, 30)
    assert props.captions.style == "karaoke" and props.items[0].component == "TitleCard"

    renders = (await client.get(f"/api/v1/projects/{pid}/renders", headers=auth)).json()["items"]
    out = renders[0]
    assert out["status"] == "done", out
    assert (out["width"], out["height"], out["fps"]) == (1080, 1920, 30)
    assert out["duration_sec"] == pytest.approx(plan["duration_sec"], abs=0.05)
    assert out["qa_status"] in ("pass", "warn") and out["qa"]["schema_version"] == "qa/1"
    loud = next(c for c in out["qa"]["checks"] if c["code"] == "loudness")
    assert loud["value"] == pytest.approx(-16.0, abs=1.0)  # the podcast target, measured on the file
    async with httpx.AsyncClient() as s3:
        video = await s3.get(out["video"]["url"])
        assert video.status_code == 200 and video.content[4:8] == b"ftyp"
        download = await s3.get(out["download"]["url"])
        assert "_v1.mp4" in download.headers["content-disposition"]
        assert (await s3.get(out["poster"]["url"])).status_code == 200
    local = Path(edit_settings.scratch_dir) / "final-check.mp4"
    local.write_bytes(video.content)
    info = normalize(run_ffprobe(str(local)), size_bytes=local.stat().st_size)
    assert (info.video.display_width, info.video.display_height, info.audio.codec) == (1080, 1920, "aac")

    assert out["delivery_status"] == "queued"
    assert run_worker(edit_settings, queues="io")[-1] == "deliver.telegram"
    video_posts = [req for req in telegram if req.url.path.endswith("/sendVideo")]
    assert len(video_posts) == 1
    posted = video_posts[0].read()
    assert (
        b'name="video"; filename="video.mp4"' in posted and b"Sinov" not in posted
    )  # caption = project name
    assert b"Test reel" in posted and f"https://synthcut.example/?p={pid}".encode() in posted

    with Session() as s:
        row = s.scalar(select(Render).where(Render.project_id == uuid.UUID(pid)))
        assert (row.delivery_status, row.telegram_message_id) == ("sent", 77)
        stages = {
            st.stage: st.status
            for st in s.scalars(select(ProjectStage).where(ProjectStage.project_id == uuid.UUID(pid)))
        }
        assert stages["director"] == "skipped"
        assert all(
            stages[k] == "done"
            for k in ("editor", "color", "audio", "captions", "motion", "render", "qa", "delivery")
        )
        render_job = s.scalar(select(Job).where(Job.kind == "render.final", Job.project_id == uuid.UUID(pid)))
        assert {"segments", "overlay", "loudness", "master", "qa"} <= set(render_job.result["timings"])
        types = set(s.scalars(select(Event.type).where(Event.project_id == uuid.UUID(pid))))
        assert {"plan.ready", "render.ready", "delivery.sent"} <= types

    # The same version again: re-used, not re-rendered; asking to deliver sends it again.
    r = await client.post(f"/api/v1/projects/{pid}/plans/1/render", json={"deliver": True}, headers=auth)
    assert r.status_code == 202 and r.json()["id"] == out["id"] and r.json()["status"] == "done"
    assert run_worker(edit_settings, queues="render") == []
    assert run_worker(edit_settings, queues="io") == ["deliver.telegram"]
    other = await client.post(
        f"/api/v1/projects/{pid}/plans/1/render", json={"preset": "youtube_16x9_1080"}, headers=auth
    )
    assert other.status_code == 409 and other.json()["error"]["code"] == "preset_mismatch"

    # A second Tez montaj is a new version; the first stays.
    await client.post(url, json={"captions": "off", "render": False}, headers=auth)
    assert run_worker(edit_settings) == ["edit.auto"]
    versions = (await client.get(f"/api/v1/projects/{pid}/plans", headers=auth)).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert (await client.get(f"/api/v1/projects/{pid}/plans/2", headers=auth)).json()["captions"] is None


async def test_plans_and_renders_are_private(
    client, auth, edit_settings, media, Session, fake_layer, telegram
):
    project = await make_project(client, auth)
    await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(edit_settings)
    await client.post(f"/api/v1/projects/{project['id']}/auto-edit", json={"render": False}, headers=auth)
    run_worker(edit_settings)
    other = await login(client, SECOND_USER)
    for path in ("edit", "plans", "plans/1", "renders"):
        assert (
            await client.get(f"/api/v1/projects/{project['id']}/{path}", headers=other)
        ).status_code == 404
    r = await client.post(f"/api/v1/projects/{project['id']}/auto-edit", json={}, headers=other)
    assert r.status_code == 404


async def test_a_dead_render_is_shown_as_failed(
    client, auth, edit_settings, media, Session, fake_layer, monkeypatch
):
    def broken(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(final_jobs, "segment_command", broken)
    project = await make_project(client, auth)
    await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(edit_settings)
    await client.post(f"/api/v1/projects/{project['id']}/auto-edit", json={"deliver": False}, headers=auth)
    run_worker(edit_settings)
    assert run_worker(edit_settings, queues="render") == ["render.final"]
    first = (await client.get(f"/api/v1/projects/{project['id']}/renders", headers=auth)).json()["items"][0]
    assert first["status"] == "queued" and first["error"].startswith("qayta urinish")  # one more attempt
    with Session() as s:  # skip the back-off
        s.execute(update(Job).where(Job.kind == "render.final").values(run_after=func.now()))
        s.commit()
    assert run_worker(edit_settings, queues="render") == ["render.final"]
    out = (await client.get(f"/api/v1/projects/{project['id']}/renders", headers=auth)).json()["items"][0]
    assert out["status"] == "failed" and "disk on fire" in out["error"]
    with Session() as s:
        job = s.scalar(
            select(Job).where(Job.kind == "render.final", Job.project_id == uuid.UUID(project["id"]))
        )
        assert job.status == "dead"
        assert (
            s.scalar(select(EditPlanRow.version).where(EditPlanRow.project_id == uuid.UUID(project["id"])))
            == 1
        )


async def test_render_refuses_when_scratch_is_full(
    client, auth, edit_settings, media, Session, fake_layer, monkeypatch
):
    from collections import namedtuple

    project = await make_project(client, auth)
    await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(edit_settings)
    await client.post(f"/api/v1/projects/{project['id']}/auto-edit", json={"deliver": False}, headers=auth)
    run_worker(edit_settings)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(final_jobs.shutil, "disk_usage", lambda path: usage(10**9, 10**9 - 10**6, 10**6))
    assert run_worker(edit_settings, queues="render") == ["render.final"]  # permanent: no retry
    monkeypatch.undo()
    out = (await client.get(f"/api/v1/projects/{project['id']}/renders", headers=auth)).json()["items"][0]
    assert out["status"] == "failed" and "diskda joy yetmaydi" in out["error"]
