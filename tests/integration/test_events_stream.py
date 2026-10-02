"""SSE stream: replay after Last-Event-ID, live delivery via Redis, catch-up
of anything the live channel missed (spec §32)."""

import asyncio
import json
import uuid

from synthcut_core.events import commit_and_publish, emit, publish_ephemeral
from synthcut_telemetry import project_event_stream

from .conftest import make_project


def _frames(raw: list[str]) -> list[dict]:
    out = []
    for frame in raw:
        if frame.startswith("data:") or "\ndata:" in frame:
            data_line = next(line for line in frame.splitlines() if line.startswith("data:"))
            out.append(json.loads(data_line[5:].strip()))
    return out


async def _collect(app, project_id, *, after_id=0, during=None, seconds=2.5, catchup=0.5):
    frames: list[str] = []
    stop = asyncio.Event()

    async def disconnected():
        return stop.is_set()

    async def consume():
        async for f in project_event_stream(
            project_id=project_id,
            after_id=after_id,
            sessionmaker=app.state.sessionmaker,
            redis=app.state.redis,
            is_disconnected=disconnected,
            heartbeat_seconds=0.5,
            catchup_seconds=catchup,
        ):
            frames.append(f)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    if during:
        await during()
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    return frames


async def test_replay_then_live_then_dedupe(app, client, auth):
    project = await make_project(client, auth)
    pid = uuid.UUID(project["id"])
    history = (await client.get(f"/api/v1/projects/{pid}/events", headers=auth)).json()["items"]
    created_id = history[-1]["id"]

    async def produce():
        async with app.state.sessionmaker() as s:
            emit(s, project_id=pid, type="stage.updated", message="Director: running", source="test")
            await commit_and_publish(s, app.state.redis)
        await publish_ephemeral(
            app.state.redis, project_id=pid, type="job.progress", message="tick", source="test"
        )

    frames = await _collect(app, pid, after_id=0, during=produce)
    events = _frames(frames)
    persisted = [e for e in events if e["id"] is not None]
    assert [e["type"] for e in persisted] == ["project.created", "stage.updated"]
    assert persisted[0]["id"] == created_id
    assert len({e["id"] for e in persisted}) == len(persisted)  # live + catch-up never duplicate
    assert any(e["type"] == "job.progress" and e["id"] is None for e in events)
    assert any(f.startswith(": ping") for f in frames)


async def test_resume_after_last_event_id(app, client, auth):
    project = await make_project(client, auth)
    pid = uuid.UUID(project["id"])
    first = (await client.get(f"/api/v1/projects/{pid}/events", headers=auth)).json()["items"][-1]["id"]
    async with app.state.sessionmaker() as s:
        emit(s, project_id=pid, type="project.updated", message="later", source="test")
        await s.commit()  # committed without a publish: only catch-up/replay can see it
    events = [e for e in _frames(await _collect(app, pid, after_id=first, seconds=1.0)) if e["id"]]
    assert "project.updated" in [e["type"] for e in events]


async def test_catch_up_finds_events_the_live_channel_missed(app, client, auth):
    project = await make_project(client, auth)
    pid = uuid.UUID(project["id"])

    async def silent_writer():
        async with app.state.sessionmaker() as s:
            emit(s, project_id=pid, type="stage.updated", message="silent", source="test")
            await s.commit()  # no Redis publish

    events = _frames(await _collect(app, pid, during=silent_writer, seconds=1.5, catchup=0.3))
    assert "silent" in [e["message"] for e in events]


async def test_stream_endpoint_requires_ownership(client, auth):
    r = await client.get(f"/api/v1/projects/{uuid.uuid4()}/events/stream", headers=auth)
    assert r.status_code == 404
