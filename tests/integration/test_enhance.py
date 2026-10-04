"""Phase 8 end to end: measured grade + voice cleanup and loudness rendered on
the proxy with real FFmpeg; the API serves the result, stills and decisions."""

import shutil
import uuid

import httpx
import pytest
from sqlalchemy import select
from synthcut_core.models import Event, MediaFile

from . import test_speech
from .conftest import make_project
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media  # the same module-scoped clips as the speech tests


async def test_enhance_preview_end_to_end(client, auth, settings, media, Session):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    assert run_worker(settings) == ["ingest.asset"]
    url = f"/api/v1/assets/{asset['id']}/enhance-preview"

    bad = await client.post(url, json={"profile": "sepia"}, headers=auth)
    assert bad.status_code == 422
    r = await client.post(
        url, json={"profile": "warm_film", "target": "podcast", "intensity": 1}, headers=auth
    )
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["profile"] == "warm_film"
    again = await client.post(url, json={"profile": "bw_classic"}, headers=auth)
    assert again.json()["profile"] == "warm_film"  # the queued request stands

    assert run_worker(settings, queues="render") == ["render.enhance_preview"]
    state = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()["enhance_preview"]
    assert state["status"] == "done" and state["target"] == "podcast"
    assert state["grade"]["schema_version"] == "grade/1" and state["grade"]["creative_profile"] == "warm_film"
    assert state["lufs_after"] == pytest.approx(-16.0, abs=1.5)  # podcast target, measured on the output
    assert any("LUFS" in n for n in state["notes"])
    async with httpx.AsyncClient() as s3:
        for key in ("video", "before", "after"):
            got = await s3.get(state[key]["url"])
            assert got.status_code == 200 and len(got.content) > 1000, key
        download = await s3.get(state["download"]["url"])
        assert 'filename="talk_enhanced.mp4"' in download.headers["content-disposition"]
    with Session() as s:
        kinds = set(s.scalars(select(MediaFile.kind).where(MediaFile.asset_id == uuid.UUID(asset["id"]))))
        assert {"enhance_preview", "enhance_before", "enhance_after"} <= kinds
        messages = list(s.scalars(select(Event.message).where(Event.type == "preview.ready")))
        assert any("rang va ovoz yaxshilandi" in m for m in messages)
    files = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()["files"]
    assert not {"enhance_preview", "enhance_before", "enhance_after"} & {f["kind"] for f in files}


async def test_enhance_needs_a_video(client, auth, settings, media):
    project = await make_project(client, auth)
    audio = await upload(client, auth, project["id"], media / "gap.wav", "audio/wav")
    run_worker(settings)
    r = await client.post(f"/api/v1/assets/{audio['id']}/enhance-preview", json={}, headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_enhanceable"
