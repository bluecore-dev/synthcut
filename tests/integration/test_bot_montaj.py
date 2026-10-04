"""Tez montaj from the chat: the bot starts it with the owner's remembered
settings and asks for the video back; the "ready" notification carries the
button; failures reach the chat when the owner is waiting there."""

import shutil
import uuid

import httpx
import pytest
from sqlalchemy import select
from synthcut_bot.handlers.commands import _tez_montaj
from synthcut_core.db import make_async_engine, make_async_sessionmaker
from synthcut_core.models import Job, Project, User
from synthcut_core.redis import make_async_redis
from synthcut_worker.delivery import notify
from synthcut_worker.render import final as final_jobs

from . import test_speech
from .conftest import DB_URL, OWNER, REDIS_URL, make_project
from .test_autoedit import edit_settings, fake_layer  # noqa: F401 — fixtures
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

media = test_speech.media
fake_engine = test_speech.fake_engine


async def _chat(project_id: str) -> str:
    engine = make_async_engine(DB_URL, pool_size=1)
    redis = make_async_redis(REDIS_URL)
    try:
        async with make_async_sessionmaker(engine)() as session:
            user = (await session.execute(select(User).where(User.telegram_id == OWNER))).scalar_one()
            project = await session.get(Project, uuid.UUID(project_id))
            return await _tez_montaj(session, redis, user, project)
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_montaj_from_the_chat(client, auth, edit_settings, media, Session, fake_layer, monkeypatch):  # noqa: F811
    project = await make_project(client, auth)
    pid = project["id"]
    await upload(client, auth, pid, media / "talk.mp4", "video/mp4")
    early = await _chat(pid)
    assert "o'qilmoqda" in early  # refused with the reason, nothing queued

    assert run_worker(edit_settings) == ["ingest.asset", "analysis.asset", "speech.transcribe"]
    with Session() as s:
        ready = s.scalars(
            select(Job).where(Job.kind == "notify.telegram", Job.project_id == uuid.UUID(pid))
        ).all()
        assert any(j.payload.get("auto_edit_project_id") == pid for j in ready)  # the button rides on "ready"

    # A remembered choice from the Mini App carries over to the chat's request.
    await client.get("/api/v1/preferences/edit", headers=auth)
    from synthcut_core.preferences import store

    engine = make_async_engine(DB_URL, pool_size=1)
    async with make_async_sessionmaker(engine)() as session:
        user = (await session.execute(select(User).where(User.telegram_id == OWNER))).scalar_one()
        await store(session, user.id, {"captions": "bold", "deliver": False}, source="choice")
        await session.commit()
    await engine.dispose()

    started = await _chat(pid)
    assert "boshlandi" in started
    again = await _chat(pid)
    assert "allaqachon" in again
    with Session() as s:
        jobs = s.scalars(select(Job).where(Job.kind == "edit.auto", Job.project_id == uuid.UUID(pid))).all()
        assert len(jobs) == 1
        assert (
            jobs[0].payload["captions"] == "bold" and jobs[0].payload["deliver"] is True
        )  # back to this chat

    def full(*a, **k):  # the render fails while the owner waits in the chat
        raise final_jobs.PermanentError("Render uchun diskda joy yetmaydi: sinov")

    monkeypatch.setattr(final_jobs, "segment_command", full)
    run_worker(edit_settings)
    assert run_worker(edit_settings, queues="render") == ["render.final"]
    with Session() as s:
        texts = [
            j.payload["text"]
            for j in s.scalars(
                select(Job).where(Job.kind == "notify.telegram", Job.project_id == uuid.UUID(pid))
            )
        ]
        assert any("Render v1 bajarilmadi" in t and "sinov" in t for t in texts)


async def test_ready_notification_has_the_button(settings, monkeypatch, Session):
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})

    monkeypatch.setattr(
        notify, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    from synthcut_core.jobs import enqueue
    from synthcut_schemas.enums import JobQueue
    from synthcut_worker.main import Worker

    pid = uuid.uuid4()
    with Session() as s:
        enqueue(s, kind="notify.telegram", queue=JobQueue.IO, idempotency_key="tm-btn", max_attempts=1,
                payload={"chat_id": 42, "text": "tayyor", "open_project_id": str(pid), "auto_edit_project_id": str(pid)})  # fmt: skip
        s.commit()
    https = settings.model_copy(update={"public_base_url": "https://synthcut.example", "worker_queues": "io"})
    worker = Worker(https, worker_id="tm-test")
    while (job := worker._claim()) is not None:
        worker._run(job)
    body = sent[0].read().decode()
    assert f'"callback_data":"tm:{pid}"' in body and "Tez montaj" in body.encode().decode("unicode_escape")
