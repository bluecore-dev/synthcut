"""The full upload path: create → sign → PUT parts straight to storage →
resume → complete → ingestion queued (spec §6, §49)."""

import base64
import hashlib
import os
import uuid

import boto3
import httpx
import pytest
from sqlalchemy import select
from synthcut_core.models import Asset, Job, UploadSession
from synthcut_storage import original_key

from .conftest import MIB, SECOND_USER, login, make_project

DATA = os.urandom(12 * MIB + 12345)  # 3 parts of 5 MiB / 5 MiB / ~2 MiB


def md5_b64(chunk: bytes) -> str:
    return base64.b64encode(hashlib.md5(chunk).digest()).decode()


def part_bytes(session: dict, number: int, data: bytes = DATA) -> bytes:
    start = (number - 1) * session["part_size"]
    return data[start : start + session["part_size"]]


async def start_upload(
    client, auth, project_id, *, data=DATA, name="A001_C002.MOV", fingerprint="fp-a001-c002"
):
    r = await client.post(
        f"/api/v1/projects/{project_id}/uploads",
        json={
            "filename": name,
            "size_bytes": len(data),
            "content_type": "video/quicktime",
            "last_modified_ms": 1_759_000_000_000,
            "fingerprint": fingerprint,
        },
        headers=auth,
    )
    return r


async def put_part(client, auth, session, number, body=None, *, md5_of=None):
    body = part_bytes(session, number) if body is None else body
    signed = await client.post(
        f"/api/v1/uploads/{session['id']}/parts",
        json={"parts": [{"number": number, "md5_b64": md5_b64(md5_of if md5_of is not None else body)}]},
        headers=auth,
    )
    assert signed.status_code == 200, signed.text
    part = signed.json()["parts"][0]
    async with httpx.AsyncClient() as storage:
        return await storage.put(part["url"], content=body, headers=part["headers"])


async def test_full_upload_flow(client, auth, Session, settings):
    project = await make_project(client, auth)
    r = await start_upload(client, auth, project["id"])
    assert r.status_code == 200, r.text
    session = r.json()
    assert session["part_count"] == 3 and session["part_size"] == 5 * MIB and not session["resumed"]
    assert session["asset"]["status"] == "uploading" and session["asset"]["kind"] == "video"
    assert session["asset"]["original_filename"] == "A001_C002.MOV"

    for n in (1, 2, 3):
        put = await put_part(client, auth, session, n)
        assert put.status_code == 200, put.text
        assert put.headers["etag"].strip('"') == hashlib.md5(part_bytes(session, n)).hexdigest()

    state = (await client.get(f"/api/v1/uploads/{session['id']}", headers=auth)).json()
    assert [p["number"] for p in state["uploaded_parts"]] == [1, 2, 3]
    assert state["bytes_uploaded"] == len(DATA)

    done = await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    assert done.status_code == 200, done.text
    asset = done.json()
    assert asset["status"] == "uploaded" and asset["etag"].endswith("-3")
    expected = hashlib.md5(
        b"".join(hashlib.md5(part_bytes(session, n)).digest() for n in (1, 2, 3))
    ).hexdigest()
    assert asset["etag"] == f"{expected}-3"

    # the original landed whole, under a server-generated key
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_internal,
        region_name="us-east-1",
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
    )
    key = original_key(project["id"], asset["id"], "mov")
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    assert obj["Body"].read() == DATA

    with Session() as s:
        job = s.scalar(select(Job).where(Job.kind == "ingest.asset"))
        assert job.status == "queued" and job.queue == "cpu" and job.payload == {"asset_id": asset["id"]}
        assert job.idempotency_key == f"ingest.asset:{asset['id']}"

    # completing twice is harmless and does not enqueue twice
    again = await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    assert again.status_code == 200 and again.json()["id"] == asset["id"]
    with Session() as s:
        assert len(s.scalars(select(Job).where(Job.kind == "ingest.asset")).all()) == 1

    detail = (await client.get(f"/api/v1/projects/{project['id']}", headers=auth)).json()
    stages = {st["stage"]: st for st in detail["stages"]}
    assert stages["upload"]["status"] == "done" and stages["ingest"]["status"] == "queued"
    assert detail["asset_count"] == 1 and detail["total_bytes"] == len(DATA)
    assert detail["active_stage"] == "ingest"

    types = [
        e["type"]
        for e in (await client.get(f"/api/v1/projects/{project['id']}/events", headers=auth)).json()["items"]
    ]
    assert {"upload.started", "upload.completed", "job.queued", "stage.updated"} <= set(types)


async def test_resume_returns_the_same_session_with_parts_already_stored(client, auth):
    project = await make_project(client, auth)
    first = (await start_upload(client, auth, project["id"])).json()
    assert (await put_part(client, auth, first, 1)).status_code == 200

    # the app was closed; the user picks the same file again
    again = await start_upload(client, auth, project["id"])
    resumed = again.json()
    assert resumed["resumed"] is True and resumed["id"] == first["id"]
    assert [p["number"] for p in resumed["uploaded_parts"]] == [1]

    # iOS Photos: same name and size, new lastModified -> new fingerprint, still resumes
    fallback = (await start_upload(client, auth, project["id"], fingerprint="fp-new-pick")).json()
    assert fallback["id"] == first["id"]


async def test_completion_refuses_missing_parts(client, auth):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    await put_part(client, auth, session, 2)
    r = await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "upload_incomplete" and r.json()["error"]["details"]["missing"] == [
        1,
        3,
    ]


async def test_completion_refuses_a_wrong_sized_part(client, auth):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    for n in (1, 2):
        await put_part(client, auth, session, n)
    await put_part(client, auth, session, 3, body=b"short")
    r = await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "upload_corrupt"


@pytest.mark.garage
async def test_storage_rejects_a_part_whose_body_differs_from_the_signed_md5(client, auth):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    good = part_bytes(session, 1)
    tampered = await put_part(client, auth, session, 1, body=os.urandom(len(good)), md5_of=good)
    assert tampered.status_code == 400 and b"InvalidDigest" in tampered.content
    state = (await client.get(f"/api/v1/uploads/{session['id']}", headers=auth)).json()
    assert state["uploaded_parts"] == []


async def test_duplicate_of_a_finished_file_is_reported(client, auth):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    for n in (1, 2, 3):
        await put_part(client, auth, session, n)
    await client.post(f"/api/v1/uploads/{session['id']}/complete", headers=auth)
    dup = await start_upload(client, auth, project["id"])
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_uploaded"


async def test_abort_cancels_and_releases_storage(client, auth, Session, settings):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    await put_part(client, auth, session, 1)
    r = await client.delete(f"/api/v1/uploads/{session['id']}", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    with Session() as s:
        sess = s.get(UploadSession, uuid.UUID(session["id"]))
        assert sess.status == "aborted"
    gone = await client.get(f"/api/v1/uploads/{session['id']}", headers=auth)
    assert gone.status_code == 200 and gone.json()["status"] == "aborted"
    # a fresh upload of the same file is allowed after cancelling
    assert (await start_upload(client, auth, project["id"])).json()["resumed"] is False


async def test_capacity_guards(client, auth, app):
    project = await make_project(client, auth)
    original = app.state.settings
    try:
        app.state.settings = original.model_copy(update={"max_upload_bytes": 10 * MIB})
        r = await start_upload(client, auth, project["id"])
        assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"

        app.state.settings = original.model_copy(update={"storage_quota_bytes": 5 * MIB})
        r = await start_upload(client, auth, project["id"])
        assert r.status_code == 507 and r.json()["error"]["code"] == "quota_exceeded"

        app.state.settings = original.model_copy(update={"disk_reserve_bytes": 10**18})
        r = await start_upload(client, auth, project["id"])
        assert r.status_code == 507 and r.json()["error"]["code"] == "disk_full"

        app.state.settings = original.model_copy(update={"disk_probe_path": "/definitely/missing"})
        r = await start_upload(client, auth, project["id"])
        assert r.status_code == 503 and r.json()["error"]["code"] == "disk_probe_unavailable"
    finally:
        app.state.settings = original


async def test_in_flight_uploads_count_against_the_quota(client, auth, app):
    project = await make_project(client, auth)
    original = app.state.settings
    app.state.settings = original.model_copy(update={"storage_quota_bytes": len(DATA) + MIB})
    try:
        assert (await start_upload(client, auth, project["id"])).status_code == 200
        second = await start_upload(client, auth, project["id"], name="B.mov", fingerprint="fp-b-0001")
        assert second.status_code == 507
    finally:
        app.state.settings = original


async def test_rejects_unsupported_types_and_strangers(client, auth):
    project = await make_project(client, auth)
    r = await client.post(
        f"/api/v1/projects/{project['id']}/uploads",
        json={
            "filename": "setup.exe",
            "size_bytes": 10,
            "content_type": "application/x-msdownload",
            "fingerprint": "fp-exe-1",
        },
        headers=auth,
    )
    assert r.status_code == 415
    session = (await start_upload(client, auth, project["id"])).json()
    other = await login(client, SECOND_USER)
    for call in (
        client.get(f"/api/v1/uploads/{session['id']}", headers=other),
        client.post(f"/api/v1/uploads/{session['id']}/complete", headers=other),
        client.delete(f"/api/v1/uploads/{session['id']}", headers=other),
        client.post(
            f"/api/v1/projects/{project['id']}/uploads",
            json={"filename": "a.mov", "size_bytes": 5, "fingerprint": "fp-zzzzz"},
            headers=other,
        ),
    ):
        assert (await call).status_code == 404


async def test_part_numbers_are_bounded(client, auth):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    r = await client.post(
        f"/api/v1/uploads/{session['id']}/parts",
        json={"parts": [{"number": 4, "md5_b64": md5_b64(b"x")}]},
        headers=auth,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_part"
    bad_md5 = await client.post(
        f"/api/v1/uploads/{session['id']}/parts",
        json={"parts": [{"number": 1, "md5_b64": "nope"}]},
        headers=auth,
    )
    assert bad_md5.status_code == 422


async def test_progress_reports_feed_the_upload_stage(client, auth, Session):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    r = await client.post(
        f"/api/v1/uploads/{session['id']}/progress", json={"bytes_uploaded": len(DATA) // 2}, headers=auth
    )
    assert r.status_code == 204
    detail = (await client.get(f"/api/v1/projects/{project['id']}", headers=auth)).json()
    upload = next(s for s in detail["stages"] if s["stage"] == "upload")
    assert upload["status"] == "running" and upload["progress"] == pytest.approx(0.5, abs=0.01)
    assets = (await client.get(f"/api/v1/projects/{project['id']}/assets", headers=auth)).json()["items"]
    assert assets[0]["upload"]["bytes_reported"] == len(DATA) // 2
    with Session() as s:
        assert s.scalar(select(Asset.status)) == "uploading"


async def test_client_side_errors_reach_the_project_log(client, auth):
    project = await make_project(client, auth)
    session = (await start_upload(client, auth, project["id"])).json()
    r = await client.post(
        f"/api/v1/uploads/{session['id']}/progress",
        json={"bytes_uploaded": 0, "error": "qism 1: Storage 403"},
        headers=auth,
    )
    assert r.status_code == 204
    events = (await client.get(f"/api/v1/projects/{project['id']}/events", headers=auth)).json()["items"]
    errors = [e for e in events if e["type"] == "upload.client_error"]
    assert len(errors) == 1 and errors[0]["level"] == "warning"
    assert errors[0]["message"] == "A001_C002.MOV: qism 1: Storage 403"
    too_long = await client.post(
        f"/api/v1/uploads/{session['id']}/progress",
        json={"bytes_uploaded": 0, "error": "x" * 301},
        headers=auth,
    )
    assert too_long.status_code == 422
