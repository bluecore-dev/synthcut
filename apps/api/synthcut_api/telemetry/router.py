from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from synthcut_core.models import Event
from synthcut_core.projects import get_owned_project
from synthcut_schemas.api import ErrorResponse, EventPage
from synthcut_schemas.events import EventEnvelope
from synthcut_telemetry import project_event_stream

from ..deps import CurrentUser, DbSession
from ..errors import not_found

router = APIRouter(tags=["telemetry"], responses={404: {"model": ErrorResponse}})


@router.get("/projects/{project_id}/events", response_model=EventPage)
async def list_events(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> EventPage:
    """Activity log. Default: the latest ``limit`` events, oldest first."""
    if await get_owned_project(db, user.id, project_id) is None:
        raise not_found("Loyiha")
    stmt = select(Event).where(Event.project_id == project_id)
    if after_id is not None:
        rows = list(
            (await db.execute(stmt.where(Event.id > after_id).order_by(Event.id).limit(limit))).scalars()
        )
    else:
        if before_id is not None:
            stmt = stmt.where(Event.id < before_id)
        rows = list(reversed(list((await db.execute(stmt.order_by(Event.id.desc()).limit(limit))).scalars())))
    return EventPage(
        items=[EventEnvelope.model_validate(e) for e in rows],
        next_after_id=rows[-1].id if rows else after_id,
    )


@router.get(
    "/projects/{project_id}/events/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_events(
    project_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    after_id: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Server-Sent Events: replay after ``Last-Event-ID`` / ``after_id``, then live."""
    if await get_owned_project(db, user.id, project_id) is None:
        raise not_found("Loyiha")
    await db.close()  # do not hold a pooled connection for the life of the stream
    start = after_id
    if last_event_id and last_event_id.isdigit():
        start = max(start, int(last_event_id))
    stream = project_event_stream(
        project_id=project_id,
        after_id=start,
        sessionmaker=request.app.state.sessionmaker,
        redis=request.app.state.redis,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
