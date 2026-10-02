from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from synthcut_schemas.api import ComponentCheck, HealthOut, ReadyOut

from .. import __version__

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(request: Request) -> HealthOut:
    """Liveness: the process answers. No dependencies are touched."""
    return HealthOut(status="ok", version=__version__, release=request.app.state.settings.release)


async def _check(coro) -> ComponentCheck:
    try:
        await asyncio.wait_for(coro, timeout=3)
        return ComponentCheck(ok=True)
    except Exception as exc:
        return ComponentCheck(ok=False, detail=type(exc).__name__)


@router.get("/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
async def ready(request: Request) -> JSONResponse:
    """Readiness: database, Redis and object storage all answer."""
    state = request.app.state

    async def db() -> None:
        async with state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    checks = {
        "database": await _check(db()),
        "redis": await _check(state.redis.ping()),
        "storage": await _check(asyncio.to_thread(state.storage.ping)),
    }
    ok = all(c.ok for c in checks.values())
    body = ReadyOut(status="ok" if ok else "degraded", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
