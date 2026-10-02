import uuid

from sqlalchemy import select
from synthcut_core.models import Event, ProjectStage
from synthcut_schemas.enums import STAGE_ORDER

from .conftest import OWNER, SECOND_USER, STRANGER, init_data, login, make_project


async def test_health_and_ready(client):
    assert (await client.get("/api/v1/health")).json()["status"] == "ok"
    ready = await client.get("/api/v1/ready")
    assert ready.status_code == 200, ready.text
    assert all(c["ok"] for c in ready.json()["checks"].values())


async def test_login_with_valid_init_data(client):
    r = await client.post("/api/v1/auth/telegram", json={"init_data": init_data(OWNER)})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["telegram_id"] == OWNER and body["token_type"] == "bearer"


async def test_stranger_is_refused_even_with_valid_signature(client):
    r = await client.post("/api/v1/auth/telegram", json={"init_data": init_data(STRANGER)})
    assert r.status_code == 403
    assert r.json()["error"] == {
        "code": "not_authorized",
        "message": "Bu xususiy tizim — sizga ruxsat berilmagan",
        "details": {"telegram_id": STRANGER},
    }


async def test_stale_or_forged_init_data_refused(client):
    stale = await client.post("/api/v1/auth/telegram", json={"init_data": init_data(OWNER, age_seconds=7200)})
    assert stale.status_code == 401 and stale.json()["error"]["details"]["reason"] == "expired"
    forged = init_data(OWNER).replace("u777000001", "u666")
    r = await client.post("/api/v1/auth/telegram", json={"init_data": forged})
    assert r.status_code == 401 and r.json()["error"]["details"]["reason"] == "bad_hash"


async def test_endpoints_require_a_token(client):
    assert (await client.get("/api/v1/projects")).status_code == 401
    bad = await client.get("/api/v1/projects", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_token"


async def test_removing_a_user_from_the_allowlist_takes_effect_immediately(client, app, auth):
    original = app.state.settings
    app.state.settings = original.model_copy(update={"authorized_telegram_user_ids": str(SECOND_USER)})
    app.state.settings.__dict__.pop("allowed_telegram_ids", None)
    try:
        r = await client.get("/api/v1/projects", headers=auth)
        assert r.status_code == 403
    finally:
        app.state.settings = original


async def test_refresh_and_me(client, auth):
    r = await client.post("/api/v1/auth/refresh", headers=auth)
    assert r.status_code == 200 and r.json()["access_token"]
    me = (await client.get("/api/v1/me", headers=auth)).json()
    assert me["user"]["telegram_id"] == OWNER
    assert me["limits"]["storage_used_bytes"] == 0 and me["limits"]["disk_free_bytes"] > 0


async def test_login_rate_limited(client):
    statuses = [
        (await client.post("/api/v1/auth/telegram", json={"init_data": "x=1"})).status_code for _ in range(32)
    ]
    assert statuses[-1] == 429 and 401 in statuses


async def test_create_project_initializes_pipeline(client, auth, Session):
    project = await make_project(client, auth, "  My New Reel  ")
    assert project["name"] == "My New Reel"
    assert project["preset"] == "reels_9x16" and project["fps"] == 30 and project["mode"] == "auto"
    assert [s["stage"] for s in project["stages"]] == [s.value for s in STAGE_ORDER]
    assert project["stages"][0]["available"] is True  # upload (phase 2)
    assert next(s for s in project["stages"] if s["stage"] == "director")["available"] is False
    assert project["progress"] == 0 and project["active_stage"] is None
    with Session() as s:
        assert (
            s.scalar(select(Event.type).where(Event.project_id == uuid.UUID(project["id"])))
            == "project.created"
        )
        assert len(s.scalars(select(ProjectStage)).all()) == len(STAGE_ORDER)


async def test_project_validation(client, auth):
    for bad in (
        {"name": ""},
        {"name": "x" * 121},
        {"name": "a", "fps": 29},
        {"name": "a", "preset": "imax"},
        {"name": "a", "unexpected": 1},
    ):
        r = await client.post("/api/v1/projects", json=bad, headers=auth)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", bad


async def test_projects_are_isolated_between_users(client, auth):
    mine = await make_project(client, auth)
    other = await login(client, SECOND_USER)
    assert (await client.get(f"/api/v1/projects/{mine['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{mine['id']}/assets", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{mine['id']}/events", headers=other)).status_code == 404
    assert (await client.get("/api/v1/projects", headers=other)).json()["items"] == []


async def test_update_and_archive(client, auth):
    p = await make_project(client, auth)
    r = await client.patch(
        f"/api/v1/projects/{p['id']}", json={"mode": "assisted", "brief": "Tez, energiyali"}, headers=auth
    )
    assert r.json()["mode"] == "assisted" and r.json()["brief"] == "Tez, energiyali"
    r = await client.post(f"/api/v1/projects/{p['id']}/archive", headers=auth)
    assert r.json()["status"] == "archived"
    assert (await client.get("/api/v1/projects", headers=auth)).json()["items"] == []
    assert (
        len((await client.get("/api/v1/projects?include_archived=true", headers=auth)).json()["items"]) == 1
    )
    events = (await client.get(f"/api/v1/projects/{p['id']}/events", headers=auth)).json()["items"]
    assert [e["type"] for e in events] == ["project.created", "project.updated", "project.archived"]
