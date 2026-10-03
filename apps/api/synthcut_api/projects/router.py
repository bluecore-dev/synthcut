from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from synthcut_core.events import commit_and_publish
from synthcut_core.jobs import enqueue_async
from synthcut_core.models import Asset, AssetTranscript, Job, MediaFile, Project, UploadSession
from synthcut_core.projects import (
    archive_project,
    create_project,
    get_owned_project,
    list_project_summaries,
    project_detail,
    update_project,
)
from synthcut_core.speech import ACTIVE as ACTIVE_TRANSCRIPT
from synthcut_core.speech import request_transcription_async
from synthcut_core.stages import refresh_ingest_stage_async, refresh_transcription_stage_async
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
    TranscribeRequest,
    TranscriptSummary,
)
from synthcut_schemas.enums import (
    PRESET_SPECS,
    AssetStatus,
    JobPriority,
    JobQueue,
    TranscriptStatus,
    UploadSessionStatus,
)
from synthcut_schemas.jobs import JobKind
from synthcut_schemas.speech import Transcript

from ..deps import AppSettings, CurrentUser, DbSession, RedisClient, StorageClient
from ..errors import ApiError, not_found
from ..uploads.service import asset_out
from .media import files_for, posters, transcript_states, transcript_summary

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
    ids = [a.id for a, _ in rows]
    thumbs = await posters(db, storage, ids, settings.media_url_ttl_seconds)
    speech = await transcript_states(db, ids)
    return AssetList(
        items=[
            asset_out(
                asset,
                sess if sess and sess.status in _OPEN else None,
                thumbnail=thumbs.get(asset.id),
                transcript=speech.get(asset.id),
            )
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
    transcript = await transcript_summary(db, storage, asset.id, ttl, filename=asset.original_filename)
    base = asset_out(
        asset,
        thumbnail=thumbs.get(asset.id),
        transcript=(transcript.status, transcript.language, transcript.finished_at) if transcript else None,
    )
    return AssetDetail(
        **base.model_dump(), media_info=asset.media_info, files=files, shots=shots, transcript=transcript
    )


async def _owned_asset(db, user_id: uuid.UUID, asset_id: uuid.UUID, *, lock: bool = False) -> Asset:
    stmt = (
        select(Asset)
        .join(Project, Project.id == Asset.project_id)
        .where(Asset.id == asset_id, Project.owner_id == user_id, Asset.deleted_at.is_(None))
    )
    asset = (await db.execute(stmt.with_for_update(of=Asset) if lock else stmt)).scalar_one_or_none()
    if asset is None:
        raise not_found("Fayl")
    return asset


@router.get("/assets/{asset_id}/transcript", response_model=Transcript)
async def get_transcript(asset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Transcript:
    """Words with timings, segments, silences and subtitle cues (``transcript/1``)."""
    asset = await _owned_asset(db, user.id, asset_id)
    row = (
        await db.execute(select(AssetTranscript).where(AssetTranscript.asset_id == asset.id))
    ).scalar_one_or_none()
    if row is None or row.status != TranscriptStatus.DONE.value or row.data is None:
        raise not_found("Transkript")
    return Transcript.model_validate(row.data)


@router.post("/assets/{asset_id}/transcribe", response_model=TranscriptSummary, status_code=202)
async def transcribe_asset(
    asset_id: uuid.UUID,
    body: TranscribeRequest,
    user: CurrentUser,
    db: DbSession,
    redis: RedisClient,
    storage: StorageClient,
    settings: AppSettings,
) -> TranscriptSummary:
    """Transcribe (again), optionally forcing a language when detection got it wrong."""
    asset = await _owned_asset(db, user.id, asset_id, lock=True)
    has_track = (
        await db.execute(
            select(func.count()).where(MediaFile.asset_id == asset.id, MediaFile.kind == "audio_speech")
        )
    ).scalar_one()
    if asset.status != AssetStatus.READY.value or not has_track:
        raise ApiError(409, "no_speech_track", "Bu faylda nutq audiosi yo'q yoki u hali tahlil qilinmagan")
    project = await db.get(Project, asset.project_id)
    language = body.language.value if body.language else (project.language or "auto")
    # A repeated tap while the same request is queued is a no-op; another language must wait.
    row = await request_transcription_async(
        db, asset_id=asset.id, project_id=asset.project_id, language=language, force=True
    )
    if row.status in ACTIVE_TRANSCRIPT and row.requested_language != language:
        raise ApiError(409, "transcription_running", "Nutq hozir matnga o'girilmoqda — tugashini kuting")
    await refresh_transcription_stage_async(db, asset.project_id, source="api")
    await commit_and_publish(db, redis)
    summary = await transcript_summary(
        db, storage, asset.id, settings.media_url_ttl_seconds, filename=asset.original_filename
    )
    assert summary is not None
    return summary


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
