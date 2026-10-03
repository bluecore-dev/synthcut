"""Phase 3 end to end: upload through the API, ingest in the worker, read the
results back through the API (spec §9-11)."""

import base64
import hashlib
import shutil
import subprocess
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from synthcut_core.models import Asset, Event, Job, MediaFile, ProjectStage
from synthcut_media import has_filter
from synthcut_worker.main import Worker

from .conftest import make_project

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    ff(
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "smptebars=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(d / "A001_cut.mp4"),
    )  # fmt: skip
    ff(
        "-display_rotation",
        "90",
        "-i",
        str(d / "A001_cut.mp4"),
        "-c",
        "copy",
        "-map",
        "0",
        str(d / "VERT.mov"),
    )
    ff(
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=2",
        "-vf", "format=yuv420p10le,setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc",
        "-c:v", "libx264", "-preset", "ultrafast", str(d / "HDR_hlg.mov"),
    )  # fmt: skip
    ff(
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=2",
        "-vf", "setparams=color_primaries=smpte432:color_trc=bt709:colorspace=bt709",
        "-c:v", "libx264", "-preset", "ultrafast", str(d / "IMG_p3.mov"),
    )  # fmt: skip
    ff("-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4", str(d / "voice.wav"))
    ff("-f", "lavfi", "-i", "testsrc2=size=800x600:duration=1", "-frames:v", "1", str(d / "logo.png"))
    (d / "broken.mov").write_bytes(b"definitely not a movie " * 4000)
    return d


async def upload(client, auth, project_id, path, content_type):
    data = path.read_bytes()
    r = await client.post(
        f"/api/v1/projects/{project_id}/uploads",
        json={
            "filename": path.name,
            "size_bytes": len(data),
            "content_type": content_type,
            "fingerprint": "fp" + hashlib.sha256(data).hexdigest()[:30],
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    session = r.json()
    for n in range(1, session["part_count"] + 1):
        chunk = data[(n - 1) * session["part_size"] : n * session["part_size"]]
        md5 = base64.b64encode(hashlib.md5(chunk).digest()).decode()
        signed = (
            await client.post(
                f"/api/v1/uploads/{session['id']}/parts",
                json={"parts": [{"number": n, "md5_b64": md5}]},
                headers=auth,
            )
        ).json()["parts"][0]
        async with httpx.AsyncClient() as s3:
            assert (await s3.put(signed["url"], content=chunk, headers=signed["headers"])).status_code == 200
    done = await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    assert done.status_code == 200, done.text
    return done.json()


def run_worker(settings, queues="cpu"):
    worker = Worker(settings.model_copy(update={"worker_queues": queues}), worker_id=f"test-{queues}")
    ran = []
    while (job := worker._claim()) is not None:
        worker._run(job)
        ran.append(job.kind)
    return ran


async def test_video_ingestion_end_to_end(client, auth, settings, media, Session):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "A001_cut.mp4", "video/mp4")
    assert run_worker(settings) == ["ingest.asset"]

    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    assert detail["status"] == "ready" and detail["kind"] == "video"
    assert (detail["width"], detail["height"], detail["fps"], detail["duration_sec"]) == (
        1920,
        1080,
        30.0,
        6.0,
    )
    assert detail["video_codec"] == "h264" and detail["audio_codec"] == "aac" and detail["has_audio"]
    assert detail["color_profile"] == "rec709" and detail["color_label"] == "Rec.709"
    assert detail["sha256"] == hashlib.sha256((media / "A001_cut.mp4").read_bytes()).hexdigest()
    info = detail["media_info"]
    assert info["schema_version"] == "mediainfo/1" and info["loudness"]["integrated_lufs"] < -10
    files = {f["kind"]: f for f in detail["files"]}
    assert set(files) == {"proxy_720p", "poster", "sprite"}  # bookkeeping files are not exposed
    assert (files["proxy_720p"]["width"], files["proxy_720p"]["height"]) == (1280, 720)
    assert files["sprite"]["metadata"]["tiles"] == 6
    assert [(s["start"], s["end"]) for s in detail["shots"]] == [(0.0, 3.0), (3.0, 6.0)]
    assert detail["thumbnail"]["url"].startswith(settings.s3_endpoint_public)

    async with httpx.AsyncClient() as s3:
        proxy = await s3.get(files["proxy_720p"]["url"]["url"], headers={"Range": "bytes=0-1023"})
        assert proxy.status_code == 206 and len(proxy.content) == 1024
        poster = await s3.get(detail["thumbnail"]["url"])
        assert poster.status_code == 200 and poster.content[:2] == b"\xff\xd8"  # JPEG

    with Session() as s:
        kinds = set(s.scalars(select(MediaFile.kind).where(MediaFile.asset_id == uuid.UUID(asset["id"]))))
        assert kinds == {"proxy_720p", "audio_speech", "poster", "sprite", "shots", "mediainfo"}
        stage = s.get(ProjectStage, (uuid.UUID(project["id"]), "ingest"))
        assert stage.status == "done" and stage.detail == "1 ta fayl tayyor"
        types = list(s.scalars(select(Event.type).where(Event.project_id == uuid.UUID(project["id"]))))
        assert "asset.ingested" in types
        notify = s.scalar(select(Job).where(Job.kind == "notify.telegram"))
        assert notify.status == "queued" and notify.payload["open_project_id"] == project["id"]

    listed = (await client.get(f"/api/v1/projects/{project['id']}/assets", headers=auth)).json()["items"]
    assert listed[0]["thumbnail"] and listed[0]["color_label"] == "Rec.709"

    # Running the job again is harmless (idempotent).
    with Session() as s:
        from synthcut_core.jobs import enqueue
        from synthcut_schemas.enums import JobQueue

        enqueue(s, kind="ingest.asset", queue=JobQueue.CPU, payload={"asset_id": asset["id"]},
                project_id=uuid.UUID(project["id"]), idempotency_key="again")  # fmt: skip
        s.commit()
    run_worker(settings)
    with Session() as s:
        again = s.scalar(select(Job).where(Job.idempotency_key == "again"))
        assert again.status == "succeeded" and again.result["skipped"] == "already_ready"


async def test_rotated_portrait_video(client, auth, settings, media):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "VERT.mov", "video/quicktime")
    run_worker(settings)
    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    assert (detail["width"], detail["height"]) == (1080, 1920)
    proxy = next(f for f in detail["files"] if f["kind"] == "proxy_720p")
    assert (proxy["width"], proxy["height"]) == (720, 1280)
    assert detail["media_info"]["video"]["rotation"] in (90, 270)


async def test_hlg_detection_and_tonemapped_proxy(client, auth, settings, media):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "HDR_hlg.mov", "video/quicktime")
    run_worker(settings)
    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    assert detail["color_profile"] == "hlg" and detail["bit_depth"] == 10 and detail["has_audio"] is False
    proxy = next(f for f in detail["files"] if f["kind"] == "proxy_720p")
    assert proxy["metadata"]["tonemapped"] is has_filter("zscale")


async def test_audio_and_image_assets(client, auth, settings, media):
    project = await make_project(client, auth)
    audio = await upload(client, auth, project["id"], media / "voice.wav", "audio/wav")
    image = await upload(client, auth, project["id"], media / "logo.png", "image/png")
    run_worker(settings)
    a = (await client.get(f"/api/v1/assets/{audio['id']}", headers=auth)).json()
    assert a["status"] == "ready" and a["kind"] == "audio" and a["duration_sec"] == 4.0
    assert {f["kind"] for f in a["files"]} == {"audio_proxy"} and a["media_info"]["loudness"]
    i = (await client.get(f"/api/v1/assets/{image['id']}", headers=auth)).json()
    assert i["status"] == "ready" and (i["width"], i["height"]) == (800, 600)
    assert {f["kind"] for f in i["files"]} == {"preview", "poster"} and i["thumbnail"]


async def test_corrupt_file_fails_permanently(client, auth, settings, media, Session):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "broken.mov", "video/quicktime")
    run_worker(settings)
    with Session() as s:
        row = s.get(Asset, uuid.UUID(asset["id"]))
        assert row.status == "failed" and "o'qilmadi" in row.error
        job = s.scalar(select(Job).where(Job.kind == "ingest.asset"))
        assert job.status == "dead" and job.attempts == 1  # permanent: no pointless retries
        stage = s.get(ProjectStage, (uuid.UUID(project["id"]), "ingest"))
        assert stage.status == "failed"
        assert s.scalar(select(Job).where(Job.kind == "notify.telegram")) is None


async def test_asset_detail_is_owner_scoped(client, auth, settings, media):
    from .conftest import SECOND_USER, login

    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "logo.png", "image/png")
    other = await login(client, SECOND_USER)
    assert (await client.get(f"/api/v1/assets/{asset['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/assets/{uuid.uuid4()}", headers=auth)).status_code == 404


def test_notify_handler_sends_and_hides_the_token(settings, monkeypatch, Session):
    from synthcut_core.jobs import enqueue
    from synthcut_schemas.enums import JobQueue
    from synthcut_worker.delivery import notify

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
        return httpx.Response(
            403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
        )

    monkeypatch.setattr(
        notify, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    https = settings.model_copy(update={"public_base_url": "https://synthcut.example", "worker_queues": "io"})
    pid = uuid.uuid4()
    with Session() as s:
        for key in ("n1", "n2"):
            enqueue(s, kind="notify.telegram", queue=JobQueue.IO, idempotency_key=key, max_attempts=3,
                    payload={"chat_id": 42, "text": "<b>salom</b>", "open_project_id": str(pid)})  # fmt: skip
        s.commit()
    worker = Worker(https, worker_id="notify-test")
    while (job := worker._claim()) is not None:
        worker._run(job)
    body = sent[0].read().decode()
    assert '"chat_id":42' in body and f"https://synthcut.example/?p={pid}" in body
    with Session() as s:
        ok = s.scalar(select(Job).where(Job.idempotency_key == "n1"))
        blocked = s.scalar(select(Job).where(Job.idempotency_key == "n2"))
        assert ok.status == "succeeded" and ok.result["message_id"] == 7
        assert blocked.status == "dead" and "blocked" in blocked.error["message"]
        assert settings.telegram_bot_token.get_secret_value() not in str(blocked.error)


async def test_display_p3_and_reingest(client, auth, settings, media, Session):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "IMG_p3.mov", "video/quicktime")
    run_worker(settings)
    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    assert detail["color_profile"] == "display_p3" and detail["color_label"] == "Display P3"
    proxy = next(f for f in detail["files"] if f["kind"] == "proxy_720p")
    assert ("gamut" in proxy["metadata"]["color"]) is has_filter("zscale")

    r = await client.post(f"/api/v1/assets/{asset['id']}/reingest", headers=auth)
    assert r.status_code == 202 and r.json()["status"] == "uploaded"
    assert (await client.post(f"/api/v1/assets/{asset['id']}/reingest", headers=auth)).status_code == 409
    assert run_worker(settings) == ["ingest.asset"]
    with Session() as s:
        jobs = s.scalars(select(Job).where(Job.kind == "ingest.asset").order_by(Job.created_at)).all()
        assert [j.status for j in jobs] == ["succeeded", "succeeded"] and jobs[1].payload["force"] is True
        assert "skipped" not in jobs[1].result
        assert s.get(Asset, uuid.UUID(asset["id"])).status == "ready"
        count = s.scalar(
            select(func.count()).select_from(MediaFile).where(MediaFile.asset_id == uuid.UUID(asset["id"]))
        )
        assert count == 5  # proxy, poster, sprite, shots, mediainfo (no audio track)
