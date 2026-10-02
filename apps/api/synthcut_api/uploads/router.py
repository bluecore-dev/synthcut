from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from synthcut_core.projects import get_owned_project
from synthcut_schemas.api import (
    AssetOut,
    ErrorResponse,
    PartSignRequest,
    PartSignResponse,
    UploadCreate,
    UploadProgressReport,
    UploadSessionOut,
)
from synthcut_schemas.enums import ProjectStatus

from ..deps import AppSettings, CurrentUser, DbSession, RedisClient, StorageClient
from ..errors import ApiError, not_found
from ..ratelimit import rate_limit
from .service import UploadService

router = APIRouter(tags=["uploads"], responses={404: {"model": ErrorResponse}})


@router.post(
    "/projects/{project_id}/uploads",
    response_model=UploadSessionOut,
    responses={409: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 507: {"model": ErrorResponse}},
)
async def create_upload(
    project_id: uuid.UUID,
    body: UploadCreate,
    user: CurrentUser,
    db: DbSession,
    storage: StorageClient,
    settings: AppSettings,
    redis: RedisClient,
) -> UploadSessionOut:
    """Open (or resume) a resumable multipart upload for one file."""
    project = await get_owned_project(db, user.id, project_id)
    if project is None:
        raise not_found("Loyiha")
    if project.status != ProjectStatus.ACTIVE.value:
        raise ApiError(409, "project_archived", "Arxivlangan loyihaga fayl yuklab bo'lmaydi")
    await rate_limit(redis, f"upload-create:{user.id}", limit=120, window_seconds=60)
    return await UploadService(db, storage, settings, redis).create_or_resume(user, project, body)


@router.get("/uploads/{session_id}", response_model=UploadSessionOut)
async def get_upload(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    storage: StorageClient,
    settings: AppSettings,
    redis: RedisClient,
) -> UploadSessionOut:
    """Upload state, including the parts storage already holds (for resume)."""
    svc = UploadService(db, storage, settings, redis)
    return await svc.session_out(await svc.get_owned_session(user, session_id))


@router.post("/uploads/{session_id}/parts", response_model=PartSignResponse)
async def sign_parts(
    session_id: uuid.UUID,
    body: PartSignRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageClient,
    settings: AppSettings,
    redis: RedisClient,
) -> PartSignResponse:
    """Presigned PUT URLs for parts; each signature covers the part's Content-MD5."""
    svc = UploadService(db, storage, settings, redis)
    return await svc.sign_parts(await svc.get_owned_session(user, session_id), body)


@router.post("/uploads/{session_id}/progress", status_code=204)
async def report_progress(
    session_id: uuid.UUID,
    body: UploadProgressReport,
    user: CurrentUser,
    db: DbSession,
    storage: StorageClient,
    settings: AppSettings,
    redis: RedisClient,
) -> Response:
    svc = UploadService(db, storage, settings, redis)
    await svc.report_progress(await svc.get_owned_session(user, session_id), body.bytes_uploaded)
    return Response(status_code=204)


@router.post(
    "/uploads/{session_id}/complete",
    response_model=AssetOut,
    responses={409: {"model": ErrorResponse}, 410: {"model": ErrorResponse}},
)
async def complete_upload(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    storage: StorageClient,
    settings: AppSettings,
    redis: RedisClient,
) -> AssetOut:
    """Verify every part in storage, assemble the original and queue ingestion."""
    return await UploadService(db, storage, settings, redis).complete(user, session_id)


@router.delete("/uploads/{session_id}", response_model=AssetOut)
async def abort_upload(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    storage: StorageClient,
    settings: AppSettings,
    redis: RedisClient,
) -> AssetOut:
    return await UploadService(db, storage, settings, redis).abort(user, session_id)
