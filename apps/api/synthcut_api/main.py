"""SynthCut API (spec §4 API Gateway). Run with
``uvicorn --factory synthcut_api.main:create_app``."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from synthcut_core.db import make_async_engine, make_async_sessionmaker
from synthcut_core.redis import make_async_redis
from synthcut_core.settings import Settings, get_settings
from synthcut_storage import Storage, StorageConfig
from synthcut_telemetry import setup_logging

from . import __version__
from .auth.router import router as auth_router
from .errors import install_error_handlers
from .projects.router import router as projects_router
from .routers.health import router as health_router
from .telemetry.router import router as telemetry_router
from .uploads.router import router as uploads_router

log = logging.getLogger("synthcut.api")

API_PREFIX = "/api/v1"


def _check_production_config(settings: Settings) -> None:
    if settings.env != "prod":
        return
    problems = []
    if len(settings.session_secret.get_secret_value()) < 32:
        problems.append("SESSION_SECRET")
    if not settings.telegram_bot_token.get_secret_value():
        problems.append("TELEGRAM_BOT_TOKEN")
    if not settings.allowed_telegram_ids:
        problems.append("AUTHORIZED_TELEGRAM_USER_IDS")
    if not settings.disk_probe_path:
        problems.append("DISK_PROBE_PATH")
    if problems:
        raise RuntimeError("missing production configuration: " + ", ".join(problems))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _check_production_config(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_async_engine(settings.database_url, pool_size=settings.db_pool_size)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = make_async_sessionmaker(engine)
        app.state.redis = make_async_redis(settings.redis_url)
        app.state.storage = Storage(
            StorageConfig(
                endpoint_internal=settings.s3_endpoint_internal,
                endpoint_public=settings.s3_endpoint_public,
                region=settings.s3_region,
                bucket=settings.s3_bucket,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            )
        )
        log.info("api started", extra={"release": settings.release, "env": settings.env})
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="SynthCut API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if settings.env != "prod" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    install_error_handlers(app)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        path = request.url.path
        if not path.endswith(("/health", "/progress")):
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
        return response

    for router in (health_router, auth_router, projects_router, uploads_router, telemetry_router):
        app.include_router(router, prefix=API_PREFIX)
    return app


def run() -> None:  # pragma: no cover - container entry point
    import uvicorn

    settings = get_settings()
    setup_logging("api", settings.log_level)
    uvicorn.run(
        "synthcut_api.main:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - published on 127.0.0.1 only by compose
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,
        # Longer than nginx's upstream keepalive_timeout (30 s): nginx must be the side
        # that closes idle connections, or it reuses one uvicorn just closed -> 502.
        timeout_keep_alive=75,
        timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
