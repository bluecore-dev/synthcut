"""Phase 7 end to end: caption preview = one-clip plan → overlay/1 → motion
layer → FFmpeg composite over the proxy → previews/<asset>/captions.mp4.
The Remotion step is replaced by FFmpeg-made transparent PNG frames of the
right size and count (the real renderer is tested in tests/unit)."""

import shutil
import subprocess
import uuid

import httpx
import pytest
from sqlalchemy import select
from synthcut_core.models import Event, Job, MediaFile
from synthcut_worker.render import jobs as render_jobs
from synthcut_worker.render.remotion import OverlayFrames, RemotionUnavailable
from synthcut_worker.speech import jobs as speech_jobs

from . import test_speech
from .conftest import make_project
from .test_ingest import run_worker, upload
from .test_speech import FakeEngine

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media  # the same module-scoped clips as the speech tests


def transparent_frames(props, work, **kwargs) -> OverlayFrames:
    """What Remotion hands back: RGBA PNG frames of the layer's size and count."""
    out = work / "overlay"
    out.mkdir()
    pad = len(str(props.duration_in_frames - 1))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=white@0.0:s={props.width}x{props.height}:r={props.fps}",
         "-frames:v", str(props.duration_in_frames), "-vf", "format=rgba", "-start_number", "0",
         str(out / f"frame-%0{pad}d.png")],
        check=True,
    )  # fmt: skip
    if kwargs.get("on_progress"):
        kwargs["on_progress"](1.0)
    return OverlayFrames(out, str(out / f"frame-%0{pad}d.png"), props.fps, props.duration_in_frames)


@pytest.fixture
def fake_layer(monkeypatch):
    rendered = []

    def render(props, work, **kwargs):
        rendered.append(props)
        return transparent_frames(props, work, **kwargs)

    monkeypatch.setattr(render_jobs, "render_overlay", render)
    monkeypatch.setattr(speech_jobs, "engine_for", lambda *a, **k: FakeEngine())
    return rendered


@pytest.fixture
def motion_settings(settings):
    return settings.model_copy(update={"speech_auto": True})


async def test_caption_preview_end_to_end(client, auth, motion_settings, media, Session, fake_layer):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    url = f"/api/v1/assets/{asset['id']}/caption-preview"

    early = await client.post(url, json={"style": "karaoke"}, headers=auth)
    assert early.status_code == 409 and early.json()["error"]["code"] == "no_transcript"

    assert run_worker(motion_settings) == ["ingest.asset", "speech.transcribe"]
    r = await client.post(url, json={"style": "karaoke", "position": "center"}, headers=auth)
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["style"] == "karaoke"
    again = await client.post(url, json={"style": "bold"}, headers=auth)
    assert again.json()["style"] == "karaoke"  # the queued request stands; no second job

    assert run_worker(motion_settings, queues="render") == ["render.caption_preview"]
    props = fake_layer[0]
    assert (props.width, props.height, props.fps) == (640, 360, 25)  # proxy size, source rate
    assert props.captions.style == "karaoke" and props.captions.position == "center"
    assert [w.text for line in props.captions.lines for w in line.words] == [
        "Salom,",
        "bu",
        "sinov.",
        "Savol",
        "bormi?",
    ]

    state = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()["caption_preview"]
    assert state["status"] == "done" and state["style"] == "karaoke"
    async with httpx.AsyncClient() as s3:
        video = await s3.get(state["video"]["url"])
        assert video.status_code == 200 and video.content[4:8] == b"ftyp"
        download = await s3.get(state["download"]["url"])
        assert 'filename="talk_subtitr.mp4"' in download.headers["content-disposition"]
    with Session() as s:
        mf = s.scalar(
            select(MediaFile).where(
                MediaFile.asset_id == uuid.UUID(asset["id"]), MediaFile.kind == "caption_preview"
            )
        )
        assert mf.meta["lines"] == 2 and mf.duration_sec == pytest.approx(6.0, abs=0.05)
        assert "preview.ready" in set(
            s.scalars(select(Event.type).where(Event.project_id == uuid.UUID(project["id"])))
        )
    files = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()["files"]
    assert "caption_preview" not in {f["kind"] for f in files}


async def test_missing_motion_engine_fails_with_a_reason(
    client,
    auth,
    motion_settings,
    media,
    Session,
    fake_layer,
    monkeypatch,
):
    def unavailable(*a, **k):
        raise RemotionUnavailable("Remotion bundle not found in /opt/remotion")

    monkeypatch.setattr(render_jobs, "render_overlay", unavailable)
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(motion_settings)
    await client.post(f"/api/v1/assets/{asset['id']}/caption-preview", json={}, headers=auth)
    run_worker(motion_settings, queues="render")
    state = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()["caption_preview"]
    assert state["status"] == "failed" and state["error"].startswith("Motion dvigateli o'rnatilmagan")
    assert state["video"] is None
    with Session() as s:
        job = s.scalar(
            select(Job).where(
                Job.kind == "render.caption_preview", Job.project_id == uuid.UUID(project["id"])
            )
        )
        assert job.status == "dead" and job.attempts == 1
