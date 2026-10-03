"""Integration fixtures: a freshly migrated PostgreSQL schema, Redis, and an S3
endpoint — real Garage when SYNTHCUT_TEST_S3_ENDPOINT is set (server test
stack), otherwise an in-process moto server.

Never point these at production: the schema is dropped and recreated.
"""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import AsyncIterator, Iterator

import boto3
import httpx
import pytest
import redis
from asgi_lifespan import LifespanManager
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from synthcut_api.auth.telegram import sign_init_data
from synthcut_api.main import create_app
from synthcut_core.db import make_sync_sessionmaker
from synthcut_core.migrate import upgrade
from synthcut_core.settings import Settings

DB_URL = os.environ.get("SYNTHCUT_TEST_DATABASE_URL", "")
REDIS_URL = os.environ.get("SYNTHCUT_TEST_REDIS_URL", "redis://localhost:6379/15")
S3_ENDPOINT = os.environ.get("SYNTHCUT_TEST_S3_ENDPOINT", "")
REAL_S3 = bool(S3_ENDPOINT)

BOT_TOKEN = "123456789:TEST-token-for-integration-tests-only"
OWNER = 777000001
SECOND_USER = 777000003
STRANGER = 777000002
MIB = 1024 * 1024

TABLES = "events, jobs, upload_sessions, assets, project_stages, projects, users"


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            if not DB_URL:
                item.add_marker(pytest.mark.skip(reason="set SYNTHCUT_TEST_DATABASE_URL"))
            if "garage" in item.keywords and not REAL_S3:
                item.add_marker(pytest.mark.skip(reason="needs a real S3 endpoint (Garage)"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def s3_env() -> Iterator[dict[str, str]]:
    if REAL_S3:
        yield {
            "endpoint": S3_ENDPOINT,
            "key": os.environ["SYNTHCUT_TEST_S3_KEY"],
            "secret": os.environ["SYNTHCUT_TEST_S3_SECRET"],
            "bucket": os.environ.get("SYNTHCUT_TEST_S3_BUCKET", "synthcut-test"),
        }
        return
    from moto.server import ThreadedMotoServer

    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    endpoint = f"http://127.0.0.1:{port}"
    boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    ).create_bucket(Bucket="synthcut-test")
    yield {"endpoint": endpoint, "key": "test", "secret": "test", "bucket": "synthcut-test"}
    server.stop()


@pytest.fixture(scope="session")
def settings(s3_env, tmp_path_factory) -> Settings:
    probe = tmp_path_factory.mktemp("disk-probe")
    return Settings(
        env="test",
        database_url=DB_URL,
        redis_url=REDIS_URL,
        s3_endpoint_internal=s3_env["endpoint"],
        s3_endpoint_public=s3_env["endpoint"],
        s3_bucket=s3_env["bucket"],
        s3_access_key_id=s3_env["key"],
        s3_secret_access_key=s3_env["secret"],
        telegram_bot_token=BOT_TOKEN,
        telegram_webhook_secret="w" * 32,
        authorized_telegram_user_ids=f"{OWNER},{SECOND_USER}",
        session_secret="s" * 48,
        disk_probe_path=str(probe),
        disk_reserve_bytes=0,
        storage_quota_bytes=50 * 1024**3,
        upload_part_size=5 * MIB,
        scratch_dir=str(tmp_path_factory.mktemp("scratch")),
        worker_queues="io,cpu",
        worker_lease_seconds=30,
        # Off unless a test turns it on (with a fake engine): ingestion tests
        # should not also run Whisper.
        speech_auto=False,
    )


@pytest.fixture(scope="session")
def engine(settings) -> Iterator[Engine]:
    eng = create_engine(DB_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    upgrade(DB_URL)  # the real migration path, not create_all()
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def redis_client(settings) -> redis.Redis:
    client = redis.Redis.from_url(REDIS_URL)
    client.flushdb()
    return client


@pytest.fixture(autouse=True)
def _clean(request, engine, redis_client):
    if "integration" not in request.keywords:
        yield
        return
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    for key in redis_client.scan_iter("sc:rl:*"):
        redis_client.delete(key)
    yield


@pytest.fixture
def Session(engine):
    return make_sync_sessionmaker(engine)


@pytest.fixture(scope="session")
async def app(settings, engine) -> AsyncIterator:
    application = create_app(settings)
    async with LifespanManager(application):
        # The lifespan stores clients on app.state, so the plain app is usable
        # (and its .state reachable) while the manager keeps it running.
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def init_data(telegram_id: int, *, age_seconds: int = 0) -> str:
    return sign_init_data(
        {
            "auth_date": str(int(time.time()) - age_seconds),
            "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
            "user": json.dumps({"id": telegram_id, "first_name": "Test", "username": f"u{telegram_id}"}),
        },
        BOT_TOKEN,
    )


async def login(client: httpx.AsyncClient, telegram_id: int = OWNER) -> dict[str, str]:
    r = await client.post("/api/v1/auth/telegram", json={"init_data": init_data(telegram_id)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def auth(client) -> dict[str, str]:
    return await login(client)


async def make_project(client: httpx.AsyncClient, headers: dict[str, str], name: str = "Test reel") -> dict:
    r = await client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
