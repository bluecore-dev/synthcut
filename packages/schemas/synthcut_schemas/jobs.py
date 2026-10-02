"""Typed payloads for background jobs (spec §30).

A job's ``kind`` names its handler; its payload is validated against the model
registered here before the handler runs, so a malformed payload fails fast and
permanently instead of crashing deep inside media code.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobKind:
    INGEST_ASSET = "ingest.asset"
    EXPIRE_UPLOADS = "maintenance.expire_uploads"
    SWEEP_ORPHAN_UPLOADS = "maintenance.sweep_orphan_uploads"
    PRUNE_JOBS = "maintenance.prune_jobs"


JOB_LABELS: dict[str, str] = {
    JobKind.INGEST_ASSET: "Media ingest",
    JobKind.EXPIRE_UPLOADS: "Eskirgan yuklashlarni tozalash",
    JobKind.SWEEP_ORPHAN_UPLOADS: "Yetim multipart yuklashlarni tozalash",
    JobKind.PRUNE_JOBS: "Eski tizim job'larini tozalash",
}


def job_label(kind: str) -> str:
    return JOB_LABELS.get(kind, kind)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IngestAssetPayload(_Payload):
    asset_id: UUID


class ExpireUploadsPayload(_Payload):
    pass


class SweepOrphanUploadsPayload(_Payload):
    pass


class PruneJobsPayload(_Payload):
    pass


PAYLOAD_MODELS: dict[str, type[_Payload]] = {
    JobKind.INGEST_ASSET: IngestAssetPayload,
    JobKind.EXPIRE_UPLOADS: ExpireUploadsPayload,
    JobKind.SWEEP_ORPHAN_UPLOADS: SweepOrphanUploadsPayload,
    JobKind.PRUNE_JOBS: PruneJobsPayload,
}
