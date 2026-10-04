"""Project domain service, shared by the API and the bot."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_schemas.api import ProjectCreate, ProjectOut, ProjectSummary, ProjectUpdate, StageOut
from synthcut_schemas.enums import (
    BUILT_STAGES,
    PRESET_SPECS,
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_PHASE,
    AssetStatus,
    ProjectStatus,
    Stage,
    StageStatus,
)
from synthcut_schemas.events import EventType

from .events import emit
from .models import Asset, Project, ProjectStage, utcnow
from .stages import active_stage, init_stages_async, overall_progress

_COUNTED_ASSET_STATES = (
    AssetStatus.UPLOADING.value,
    AssetStatus.UPLOADED.value,
    AssetStatus.INGESTING.value,
    AssetStatus.READY.value,
)


async def create_project(
    session: AsyncSession, owner_id: uuid.UUID, data: ProjectCreate, *, source: str
) -> Project:
    now = utcnow()
    project = Project(
        owner_id=owner_id,
        name=data.name,
        preset=data.preset.value,
        fps=data.fps,
        target_duration_sec=data.target_duration_sec,
        mode=data.mode.value,
        language=data.language.value,
        brief=data.brief,
        status=ProjectStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    await session.flush()
    await init_stages_async(session, project.id)
    spec = PRESET_SPECS[data.preset]
    emit(
        session,
        project_id=project.id,
        type=EventType.PROJECT_CREATED,
        message=f"Loyiha yaratildi: {project.name} ({spec.label}, {spec.width}×{spec.height}, {data.fps} fps)",
        source=source,
        data={"preset": data.preset.value, "mode": data.mode.value},
    )
    return project


async def get_owned_project(
    session: AsyncSession, owner_id: uuid.UUID, project_id: uuid.UUID, *, lock: bool = False
) -> Project | None:
    stmt = select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def touch_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    await session.execute(update(Project).where(Project.id == project_id).values(updated_at=utcnow()))


async def update_project(
    session: AsyncSession, project: Project, data: ProjectUpdate, *, source: str
) -> list[str]:
    changed: list[str] = []
    for field, value in data.model_dump(exclude_unset=True).items():
        if field != "brief" and field != "target_duration_sec" and value is None:
            continue
        stored = value.value if hasattr(value, "value") else value
        if getattr(project, field) != stored:
            setattr(project, field, stored)
            changed.append(field)
    if changed:
        project.updated_at = utcnow()
        emit(
            session,
            project_id=project.id,
            type=EventType.PROJECT_UPDATED,
            message="Loyiha sozlamalari yangilandi: " + ", ".join(changed),
            source=source,
            data={"fields": changed},
        )
    return changed


async def archive_project(session: AsyncSession, project: Project, *, source: str) -> None:
    if project.status == ProjectStatus.ARCHIVED.value:
        return
    project.status = ProjectStatus.ARCHIVED.value
    project.archived_at = utcnow()
    project.updated_at = project.archived_at
    emit(
        session,
        project_id=project.id,
        type=EventType.PROJECT_ARCHIVED,
        message="Loyiha arxivlandi",
        source=source,
    )


# --------------------------------------------------------------------------- read models


async def _asset_totals(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not project_ids:
        return {}
    rows = await session.execute(
        select(Asset.project_id, func.count(), func.coalesce(func.sum(Asset.size_bytes), 0))
        .where(
            Asset.project_id.in_(project_ids),
            Asset.deleted_at.is_(None),
            Asset.status.in_(_COUNTED_ASSET_STATES),
        )
        .group_by(Asset.project_id)
    )
    return {pid: (int(count), int(size)) for pid, count, size in rows.all()}


async def _stage_rows(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ProjectStage]]:
    if not project_ids:
        return {}
    rows = (
        await session.execute(select(ProjectStage).where(ProjectStage.project_id.in_(project_ids)))
    ).scalars()
    grouped: dict[uuid.UUID, list[ProjectStage]] = defaultdict(list)
    for row in rows:
        grouped[row.project_id].append(row)
    return grouped


def _stage_map(rows: list[ProjectStage]) -> dict[str, tuple[str, float | None]]:
    return {r.stage: (r.status, r.progress) for r in rows}


def _summary(project: Project, totals: tuple[int, int], stage_rows: list[ProjectStage]) -> ProjectSummary:
    smap = _stage_map(stage_rows)
    current = active_stage(smap)
    return ProjectSummary(
        id=project.id,
        name=project.name,
        preset=project.preset,
        fps=project.fps,
        mode=project.mode,
        status=project.status,
        asset_count=totals[0],
        total_bytes=totals[1],
        progress=overall_progress(smap),
        active_stage=current,
        active_stage_label=STAGE_LABELS[current] if current else None,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def stage_out(stage: Stage, row: ProjectStage | None) -> StageOut:
    phase = STAGE_PHASE[stage]
    return StageOut(
        stage=stage,
        label=STAGE_LABELS[stage],
        status=row.status if row else StageStatus.PENDING,
        progress=row.progress if row else None,
        detail=row.detail if row else None,
        phase=phase,
        available=stage in BUILT_STAGES,
        started_at=row.started_at if row else None,
        finished_at=row.finished_at if row else None,
        updated_at=row.updated_at if row else None,
    )


async def list_project_summaries(
    session: AsyncSession, owner_id: uuid.UUID, *, include_archived: bool = False, limit: int = 100
) -> list[ProjectSummary]:
    stmt = select(Project).where(Project.owner_id == owner_id)
    if not include_archived:
        stmt = stmt.where(Project.status == ProjectStatus.ACTIVE.value)
    projects = list((await session.execute(stmt.order_by(Project.updated_at.desc()).limit(limit))).scalars())
    ids = [p.id for p in projects]
    totals = await _asset_totals(session, ids)
    stages = await _stage_rows(session, ids)
    return [_summary(p, totals.get(p.id, (0, 0)), stages.get(p.id, [])) for p in projects]


async def project_detail(session: AsyncSession, project: Project) -> ProjectOut:
    totals = (await _asset_totals(session, [project.id])).get(project.id, (0, 0))
    rows = (await _stage_rows(session, [project.id])).get(project.id, [])
    summary = _summary(project, totals, rows)
    by_stage = {r.stage: r for r in rows}
    return ProjectOut(
        **summary.model_dump(),
        target_duration_sec=project.target_duration_sec,
        language=project.language,
        brief=project.brief,
        stages=[stage_out(stage, by_stage.get(stage.value)) for stage in STAGE_ORDER],
        cost_usd=0.0,
        current_agent=None,
    )
