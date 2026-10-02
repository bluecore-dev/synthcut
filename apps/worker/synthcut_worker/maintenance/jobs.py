"""Housekeeping jobs (queue ``io``), scheduled periodically by the worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Asset, Job, UploadSession, utcnow
from synthcut_core.stages import refresh_upload_stage
from synthcut_schemas.enums import AssetStatus, EventLevel, JobQueue, JobStatus, UploadSessionStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import ExpireUploadsPayload, JobKind, PruneJobsPayload, SweepOrphanUploadsPayload

from ..context import JobContext
from ..registry import handler

ORPHAN_MIN_AGE = timedelta(hours=24)
PRUNE_AFTER = timedelta(days=14)


@handler(JobKind.EXPIRE_UPLOADS, queue=JobQueue.IO)
def expire_uploads(ctx: JobContext, _: ExpireUploadsPayload) -> dict[str, Any]:
    """Abort multipart uploads nobody touched for the idle TTL, freeing their
    partial bytes in storage and their quota reservation."""
    cutoff = utcnow() - timedelta(seconds=ctx.settings.upload_session_idle_ttl_seconds)
    expired = 0
    with ctx.session() as s:
        rows = (
            s.execute(
                select(UploadSession)
                .where(
                    UploadSession.status == UploadSessionStatus.ACTIVE.value,
                    UploadSession.last_activity_at < cutoff,
                )
                .with_for_update(skip_locked=True)
                .limit(200)
            )
            .scalars()
            .all()
        )
        projects = set()
        for sess in rows:
            ctx.check()
            ctx.storage.abort_multipart(sess.storage_key, sess.s3_upload_id)
            sess.status = UploadSessionStatus.EXPIRED.value
            asset = s.get(Asset, sess.asset_id)
            if asset is not None and asset.status == AssetStatus.UPLOADING.value:
                asset.status = AssetStatus.FAILED.value
                asset.error = "upload expired after inactivity"
                emit(
                    s,
                    project_id=sess.project_id,
                    type=EventType.UPLOAD_EXPIRED,
                    level=EventLevel.WARNING,
                    message=f"{asset.original_filename}: uzoq vaqt harakatsiz qolgani uchun yuklash bekor qilindi",
                    source="worker",
                    data={"asset_id": str(asset.id)},
                    job_id=ctx.job.id,
                )
            projects.add(sess.project_id)
            expired += 1
        for project_id in projects:
            refresh_upload_stage(s, project_id, source="worker")
        commit_and_publish_sync(s, ctx.redis)
    return {"expired": expired}


@handler(JobKind.SWEEP_ORPHAN_UPLOADS, queue=JobQueue.IO)
def sweep_orphan_uploads(ctx: JobContext, _: SweepOrphanUploadsPayload) -> dict[str, Any]:
    """Abort multipart uploads that exist in storage but not as an open session
    (e.g. the API crashed between creating the upload and committing its row)."""
    refs = ctx.storage.list_multipart_uploads(prefix="projects/")
    with ctx.session() as s:
        open_ids = set(
            s.execute(
                select(UploadSession.s3_upload_id).where(
                    UploadSession.status.in_(
                        [UploadSessionStatus.ACTIVE.value, UploadSessionStatus.COMPLETING.value]
                    )
                )
            ).scalars()
        )
    threshold = datetime.now(UTC) - ORPHAN_MIN_AGE
    aborted = 0
    for ref in refs:
        ctx.check()
        initiated = (
            ref.initiated
            if ref.initiated is None or ref.initiated.tzinfo
            else ref.initiated.replace(tzinfo=UTC)
        )
        if ref.upload_id in open_ids or initiated is None or initiated > threshold:
            continue
        ctx.storage.abort_multipart(ref.key, ref.upload_id)
        aborted += 1
    return {"seen": len(refs), "aborted": aborted}


@handler(JobKind.PRUNE_JOBS, queue=JobQueue.IO)
def prune_jobs(ctx: JobContext, _: PruneJobsPayload) -> dict[str, Any]:
    """Drop finished housekeeping jobs; project jobs are kept as history."""
    with ctx.session() as s:
        result = s.execute(
            delete(Job).where(
                Job.project_id.is_(None),
                Job.status.in_([JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value]),
                Job.finished_at < utcnow() - PRUNE_AFTER,
            )
        )
        s.commit()
    return {"deleted": result.rowcount}
