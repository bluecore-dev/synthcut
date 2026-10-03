from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from synthcut_core.events import commit_and_publish
from synthcut_core.jobs import enqueue_async
from synthcut_core.models import Asset, Job, Project, UploadSession
from synthcut_core.projects import (
    archive_project,
    create_project,
    get_owned_project,
    list_project_summaries,
    project_detail,
    update_project,
)
from synthcut_core.stages import refresh_ingest_stage_async
from synthcut_schemas.api import (
    AssetDetail,
    AssetList,
    AssetOut,
    ErrorResponse,
    JobList,
    JobOut,
    PresetOut,
    ProjectCreate,
    ProjectList,
    ProjectOut,
    ProjectUpdate,
)
from synthcut_schemas.enums import PRESET_SPECS, AssetStatus, JobPriority, JobQueue, UploadSessionStatus
from synthcut_schemas.jobs import JobKind

from ..deps import AppSettings, CurrentUser, DbSession, RedisClient, StorageClient
from ..errors import ApiError, not_found
from ..uploads.service import asset_out
from .media import files_for, posters

router = APIRouter(tags=["projects"], responses={404: {"model": ErrorResponse}})

_OPEN = (UploadSessionStatus.ACTIVE.value, UploadSessionStatus.COMPLETING.value)


@router.get("/presets", response_model=list[PresetOut])
async def list_presets(_: CurrentUser) -> list[PresetOut]:
    return [
        PresetOut(id=p, width=s.width, height=s.height, aspect=s.aspect, label=s.label, family=s.family)
        for p, s in PRESET_SPECS.items()
    ]


@router.get("/projects", response_model=ProjectList)
async def list_projects(
    user: CurrentUser, db: DbSession, include_archived: Annotated[bool, Query()] = False
) -> ProjectList:
    return ProjectList(items=await list_project_summaries(db, user.id, include_archived=include_archived))


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def new_project(
    body: ProjectCreate, user: CurrentUser, db: DbSession, redis: RedisClient
) -> ProjectOut:
    project = await create_project(db, user.id, body, source="api")
    await commit_and_publish(db, redis)
    return await project_detail(db, project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectOut:
    project = await get_owned_project(db, user.id, project_id)
    if project is None:
        raise not_found("Loyiha")
    return await project_detail(db, project)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def patch_project(
    project_id: uuid.UUID, body: ProjectUpdate, user: CurrentUser, db: DbSession, redis: RedisClient
) -> ProjectOut:
    project = await get_owned_project(db, user.id, project_id, lock=True)
    if project is None:
        raise not_found("Loyiha")
    await update_project(db, project, body, source="api")
    await commit_and_publish(db, redis)
    return await project_detail(db, project)


@router.post("/projects/{project_id}/archive", response_model=ProjectOut)
async def archive(project_id: uuid.UUID, user: CurrentUser, db: DbSession, redis: RedisClient) -> ProjectOut:
    project = await get_owned_project(db, user.id, project_id, lock=True)
    if project is None:
        raise not_found("Loyiha")
    await archive_project(db, project, source="api")
    await commit_and_publish(db, redis)
    return await project_detail(db, project)


@router.get("/projects/{project_id}/assets", response_model=AssetList)
async def list_assets(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: StorageClient, settings: AppSettings
) -> AssetList:
    if await get_owned_project(db, user.id, project_id) is None:
        raise not_found("Loyiha")
    rows = list(
        await db.execute(
            select(Asset, UploadSession)
            .outerjoin(UploadSession, UploadSession.asset_id == Asset.id)
            .where(Asset.project_id == project_id, Asset.deleted_at.is_(None))
            .order_by(Asset.sort_index, Asset.created_at)
        )
    )
    thumbs = await posters(db, storage, [a.id for a, _ in rows], settings.media_url_ttl_seconds)
    return AssetList(
        items=[
            asset_out(asset, sess if sess and sess.status in _OPEN else None, thumbnail=thumbs.get(asset.id))
            for asset, sess in rows
        ]
    )


@router.get("/assets/{asset_id}", response_model=AssetDetail)
async def get_asset(
    asset_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: StorageClient, settings: AppSettings
) -> AssetDetail:
    """One asset with its derived files (proxy, poster, filmstrip), shots and metadata."""
    asset = (
        await db.execute(
            select(Asset)
            .join(Project, Project.id == Asset.project_id)
            .where(Asset.id == asset_id, Project.owner_id == user.id, Asset.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if asset is None:
        raise not_found("Fayl")
    ttl = settings.media_url_ttl_seconds
    files, shots = await files_for(db, storage, asset.id, ttl)
    thumbs = await posters(db, storage, [asset.id], ttl)
    base = asset_out(asset, thumbnail=thumbs.get(asset.id))
    return AssetDetail(**base.model_dump(), media_info=asset.media_info, files=files, shots=shots)


@router.get("/projects/{project_id}/jobs", response_model=JobList)
async def list_jobs(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> JobList:
    if await get_owned_project(db, user.id, project_id) is None:
        raise not_found("Loyiha")
    rows = await db.execute(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(limit)
    )
    return JobList(items=[JobOut.model_validate(j) for j in rows.scalars()])


@router.post("/assets/{asset_id}/reingest", response_model=AssetOut, status_code=202)
async def reingest_asset(
    asset_id: uuid.UUID, user: CurrentUser, db: DbSession, redis: RedisClient
) -> AssetOut:
    """Run ingestion again (after a media-engine update). Derived files are
    rewritten in place; the original is only read."""
    asset = (
        await db.execute(
            select(Asset)
            .join(Project, Project.id == Asset.project_id)
            .where(Asset.id == asset_id, Project.owner_id == user.id, Asset.deleted_at.is_(None))
            .with_for_update(of=Asset)
        )
    ).scalar_one_or_none()
    if asset is None:
        raise not_found("Fayl")
    if asset.status not in (AssetStatus.READY.value, AssetStatus.FAILED.value) or asset.uploaded_at is None:
        raise ApiError(409, "not_ingestable", "Bu fayl hozir qayta tahlil qilinmaydi")
    runs = (
        await db.execute(
            select(func.count()).where(
                Job.kind == JobKind.INGEST_ASSET, Job.payload["asset_id"].astext == str(asset.id)
            )
        )
    ).scalar_one()
    asset.status = AssetStatus.UPLOADED.value
    asset.error = None
    await enqueue_async(
        db,
        kind=JobKind.INGEST_ASSET,
        queue=JobQueue.CPU,
        payload={"asset_id": str(asset.id), "force": True},
        project_id=asset.project_id,
        priority=JobPriority.HIGH,
        idempotency_key=f"{JobKind.INGEST_ASSET}:{asset.id}:r{runs}",
    )
    await refresh_ingest_stage_async(db, asset.project_id, source="api")
    await commit_and_publish(db, redis)
    return asset_out(asset)
