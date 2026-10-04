"""Phase 10 end to end: choices remembered, quick feedback changes the
preferences by explained rules, a remake keeps the version's own title and
format, and nothing leaks between users."""

import shutil
import uuid

import pytest
from sqlalchemy import select
from synthcut_core.models import EditPlanRow, Event

from . import test_speech
from .conftest import SECOND_USER, login, make_project
from .test_autoedit import edit_settings, fake_layer  # noqa: F401 — fixtures
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media
fake_engine = test_speech.fake_engine


async def test_choices_feedback_and_remake(client, auth, edit_settings, media, Session, fake_layer):  # noqa: F811
    first = (await client.get("/api/v1/preferences/edit", headers=auth)).json()
    assert first["sources"] == {} and first["values"]["denoise"] == "auto"
    assert {o["code"] for o in first["feedback_options"]} >= {"voice_robotic", "cut_too_much"}

    project = await make_project(client, auth)
    pid = project["id"]
    await upload(client, auth, pid, media / "talk.mp4", "video/mp4")
    run_worker(edit_settings)
    body = {"captions": "karaoke", "denoise": "strong", "title": "Sinov", "deliver": False}
    assert (
        await client.post(f"/api/v1/projects/{pid}/auto-edit", json=body, headers=auth)
    ).status_code == 202
    prefs = (await client.get("/api/v1/preferences/edit", headers=auth)).json()
    assert prefs["values"]["captions"] == "karaoke" and prefs["values"]["denoise"] == "strong"
    assert prefs["sources"] == {"captions": "choice", "denoise": "choice", "deliver": "choice"}
    assert run_worker(edit_settings) == ["edit.auto"]
    render = (await client.get(f"/api/v1/projects/{pid}/renders", headers=auth)).json()["items"][0]
    url = f"/api/v1/renders/{render['id']}/feedback"

    empty = await client.post(url, json={"codes": [], "comment": "  "}, headers=auth)
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "empty_feedback"
    r = await client.post(
        url,
        json={"codes": ["voice_robotic", "too_quiet"], "comment": "ovoz g'alati", "at_sec": 1.5},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    fb = r.json()
    assert [c["label"] for c in fb["changes"]] == [
        "Shovqin tozalash: kuchli → o'rta"
    ]  # social is already loudest
    assert fb["plan_version"] == 1 and fb["comment"] == "ovoz g'alati" and fb["remake_job_id"] is None
    prefs = (await client.get("/api/v1/preferences/edit", headers=auth)).json()
    assert prefs["values"]["denoise"] == "medium" and prefs["sources"]["denoise"] == "feedback"

    remake = await client.post(url, json={"codes": ["no_captions"], "remake": True}, headers=auth)
    assert remake.status_code == 201 and remake.json()["remake_job_id"]
    assert run_worker(edit_settings) == ["edit.auto"]
    with Session() as s:
        v2 = s.scalar(
            select(EditPlanRow).where(EditPlanRow.project_id == uuid.UUID(pid), EditPlanRow.version == 2)
        )
        assert v2.plan["captions"] is None  # the correction
        assert v2.options["title"] == "Sinov" and v2.options["denoise"] == "medium"  # kept + remembered
        assert v2.options["preset"] == "reels_9x16"
        messages = list(s.scalars(select(Event.message).where(Event.type == "feedback.recorded")))
        assert any("kuchli → o'rta" in m for m in messages)
    listed = (await client.get(f"/api/v1/projects/{pid}/feedback", headers=auth)).json()["items"]
    assert [f["codes"] for f in listed] == [["no_captions"], ["voice_robotic", "too_quiet"]]

    other = await login(client, SECOND_USER)
    assert (await client.post(url, json={"codes": ["too_loud"]}, headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/feedback", headers=other)).status_code == 404
    theirs = (await client.get("/api/v1/preferences/edit", headers=other)).json()
    assert theirs["sources"] == {} and theirs["values"]["captions"] == "dynamic"  # one user's memory only
