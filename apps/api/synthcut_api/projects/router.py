from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from synthcut_core.events import commit_and_publish
from synthcut_core.models import Asset, Job, UploadSession
from synthcut_core.projects import (
    archive_project,
    create_project,
    get_owned_project,
    list_project_summaries,
    project_detail,
    update_project,
)
from synthcut_schemas.api import (
    AssetList,
    ErrorResponse,
    JobList,
    JobOut,
    PresetOut,
    ProjectCreate,
    ProjectList,
    ProjectOut,
    ProjectUpdate,
)
from synthcut_schemas.enums import PRESET_SPECS, UploadSessionStatus

from ..deps import CurrentUser, DbSession, RedisClient
from ..errors import not_found
from ..uploads.service import asset_out

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
async def list_assets(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AssetList:
    if await get_owned_project(db, user.id, project_id) is None:
        raise not_found("Loyiha")
    rows = await db.execute(
        select(Asset, UploadSession)
        .outerjoin(UploadSession, UploadSession.asset_id == Asset.id)
        .where(Asset.project_id == project_id, Asset.deleted_at.is_(None))
        .order_by(Asset.sort_index, Asset.created_at)
    )
    return AssetList(
        items=[asset_out(asset, sess if sess and sess.status in _OPEN else None) for asset, sess in rows]
    )


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
