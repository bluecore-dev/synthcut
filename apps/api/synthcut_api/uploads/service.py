"""Resumable direct-to-storage uploads (spec §6, §49, rule 2).

The API only coordinates: it opens an S3 multipart upload, hands out
presigned part URLs whose signature includes each part's ``Content-MD5``, and
on completion verifies the parts storage actually holds before stitching them
together. The bytes travel phone → storage and never touch this process.

Resume: storage's ListParts is the source of truth for what has arrived, so a
client that lost everything (app closed, phone rebooted) re-selects the file,
gets the same session back by fingerprint and uploads only what is missing.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_core.events import commit_and_publish, emit, publish_ephemeral
from synthcut_core.ids import new_id
from synthcut_core.jobs import enqueue_async
from synthcut_core.models import Asset, Project, UploadSession, User, utcnow
from synthcut_core.projects import touch_project
from synthcut_core.settings import Settings
from synthcut_core.stages import StageState, refresh_upload_stage_async, set_stage_async
from synthcut_schemas.api import (
    AssetOut,
    LimitsOut,
    PartSignRequest,
    PartSignResponse,
    SignedPart,
    UploadCreate,
    UploadPartOut,
    UploadSessionOut,
    UploadStateOut,
)
from synthcut_schemas.enums import (
    AssetStatus,
    EventLevel,
    JobPriority,
    JobQueue,
    Stage,
    StageStatus,
    UploadSessionStatus,
)
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import JobKind
from synthcut_storage import (
    NoSuchUploadError,
    Storage,
    UploadedPart,
    expected_part_size,
    original_key,
    plan_parts,
)

from ..errors import ApiError
from .media_types import UnsupportedMediaError, classify, safe_display_name

log = logging.getLogger(__name__)

_STORED_STATES = (AssetStatus.UPLOADED.value, AssetStatus.INGESTING.value, AssetStatus.READY.value)
_OPEN_SESSION_STATES = (UploadSessionStatus.ACTIVE.value, UploadSessionStatus.COMPLETING.value)


def _gb(n: int) -> str:
    return f"{n / 1024**3:.2f} GB"


def asset_out(asset: Asset, sess: UploadSession | None = None) -> AssetOut:
    out = AssetOut.model_validate(asset)
    if sess is not None and sess.status in _OPEN_SESSION_STATES:
        out.upload = UploadStateOut(
            session_id=sess.id,
            status=sess.status,
            bytes_reported=sess.bytes_reported,
            part_size=sess.part_size,
            part_count=sess.part_count,
        )
    return out


class UploadService:
    def __init__(
        self, session: AsyncSession, storage: Storage, settings: Settings, redis: aioredis.Redis | None
    ) -> None:
        self.db = session
        self.storage = storage
        self.settings = settings
        self.redis = redis

    # ------------------------------------------------------------------ capacity

    async def _usage(self) -> tuple[int, int, int]:
        """(stored bytes, declared bytes of open uploads, bytes still to arrive)."""
        stored = (
            await self.db.execute(
                select(func.coalesce(func.sum(Asset.size_bytes), 0)).where(
                    Asset.status.in_(_STORED_STATES), Asset.deleted_at.is_(None)
                )
            )
        ).scalar_one()
        declared, remaining = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(UploadSession.size_bytes), 0),
                    func.coalesce(
                        func.sum(
                            UploadSession.size_bytes
                            - func.least(UploadSession.bytes_reported, UploadSession.size_bytes)
                        ),
                        0,
                    ),
                ).where(UploadSession.status.in_(_OPEN_SESSION_STATES))
            )
        ).one()
        return int(stored), int(declared), int(remaining)

    def _disk_free(self) -> int | None:
        probe = self.settings.disk_probe_path
        if not probe:
            return None
        if not Path(probe).exists():
            raise ApiError(
                503, "disk_probe_unavailable", "Diskni tekshirib bo'lmadi — yuklash vaqtincha to'xtatilgan"
            )
        return shutil.disk_usage(probe).free

    async def limits(self) -> LimitsOut:
        stored, declared, _ = await self._usage()
        return LimitsOut(
            max_upload_bytes=self.settings.max_upload_bytes,
            storage_quota_bytes=self.settings.storage_quota_bytes,
            storage_used_bytes=stored,
            storage_reserved_bytes=declared,
            disk_free_bytes=self._disk_free(),
            part_size_bytes=self.settings.upload_part_size,
        )

    async def _check_capacity(self, size: int) -> None:
        s = self.settings
        if size > s.max_upload_bytes:
            raise ApiError(
                413,
                "file_too_large",
                f"Fayl juda katta: chegarasi {_gb(s.max_upload_bytes)}",
                {"max": s.max_upload_bytes},
            )
        stored, declared, remaining = await self._usage()
        if stored + declared + size > s.storage_quota_bytes:
            raise ApiError(
                507,
                "quota_exceeded",
                f"Saqlash kvotasi yetmaydi: {_gb(stored + declared)} / {_gb(s.storage_quota_bytes)} band",
                {"used": stored, "reserved": declared, "quota": s.storage_quota_bytes},
            )
        free = self._disk_free()
        if free is not None and free - remaining - size < s.disk_reserve_bytes:
            raise ApiError(
                507,
                "disk_full",
                "Serverda bo'sh joy yetarli emas — boshqa xizmatlarni himoya qilish uchun yuklash rad etildi",
                {"free": free, "reserve": s.disk_reserve_bytes},
            )

    # ------------------------------------------------------------------ lookup

    async def get_owned_session(
        self, user: User, session_id: uuid.UUID, *, lock: bool = False
    ) -> UploadSession:
        stmt = (
            select(UploadSession)
            .join(Project, Project.id == UploadSession.project_id)
            .where(UploadSession.id == session_id, Project.owner_id == user.id)
        )
        if lock:
            stmt = stmt.with_for_update(of=UploadSession)
        sess = (await self.db.execute(stmt)).scalar_one_or_none()
        if sess is None:
            raise ApiError(404, "not_found", "Yuklash sessiyasi topilmadi")
        return sess

    async def _asset(self, asset_id: uuid.UUID) -> Asset:
        return (await self.db.execute(select(Asset).where(Asset.id == asset_id))).scalar_one()

    async def _list_parts(self, sess: UploadSession) -> list[UploadedPart]:
        return await asyncio.to_thread(self.storage.list_parts, sess.storage_key, sess.s3_upload_id)

    async def session_out(self, sess: UploadSession, *, resumed: bool = False) -> UploadSessionOut:
        asset = await self._asset(sess.asset_id)
        parts: list[UploadedPart] = []
        if sess.status in _OPEN_SESSION_STATES:
            try:
                parts = await self._list_parts(sess)
            except NoSuchUploadError as exc:
                await self._mark_gone(sess, asset)
                raise ApiError(
                    410, "upload_gone", "Bu yuklash muddati o'tgan — faylni qaytadan yuklang"
                ) from exc
        return UploadSessionOut(
            id=sess.id,
            asset_id=sess.asset_id,
            project_id=sess.project_id,
            status=sess.status,
            size_bytes=sess.size_bytes,
            part_size=sess.part_size,
            part_count=sess.part_count,
            uploaded_parts=[UploadPartOut(number=p.number, size=p.size, etag=p.etag) for p in parts],
            bytes_uploaded=sum(p.size for p in parts)
            if parts
            else (sess.size_bytes if sess.status == "completed" else 0),
            resumed=resumed,
            asset=asset_out(asset, sess),
        )

    async def _mark_gone(self, sess: UploadSession, asset: Asset) -> None:
        sess.status = UploadSessionStatus.FAILED.value
        asset.status = AssetStatus.FAILED.value
        asset.error = "multipart upload no longer exists in storage"
        emit(
            self.db,
            project_id=sess.project_id,
            type=EventType.UPLOAD_FAILED,
            level=EventLevel.ERROR,
            message=f"{asset.original_filename}: yuklash storage'da topilmadi",
            source="api",
            data={"asset_id": str(asset.id)},
        )
        await refresh_upload_stage_async(self.db, sess.project_id, source="api")
        await commit_and_publish(self.db, self.redis)

    # ------------------------------------------------------------------ create / resume

    async def create_or_resume(self, user: User, project: Project, body: UploadCreate) -> UploadSessionOut:
        try:
            kind, ext = classify(body.filename, body.content_type)
        except UnsupportedMediaError as exc:
            raise ApiError(
                415,
                "unsupported_media_type",
                "Bu fayl turi qo'llab-quvvatlanmaydi",
                {"filename": body.filename},
            ) from exc
        display_name = safe_display_name(body.filename)

        resumable = await self._find_resumable(project.id, body.fingerprint, display_name, body.size_bytes)
        if resumable is not None:
            asset, sess = resumable
            emit(
                self.db,
                project_id=project.id,
                type=EventType.UPLOAD_RESUMED,
                message=f"{asset.original_filename}: yuklash davom ettirilmoqda",
                source="api",
                data={"asset_id": str(asset.id)},
            )
            sess.last_activity_at = utcnow()
            await commit_and_publish(self.db, self.redis)
            return await self.session_out(sess, resumed=True)

        duplicate = (
            await self.db.execute(
                select(Asset.id).where(
                    Asset.project_id == project.id,
                    Asset.fingerprint == body.fingerprint,
                    Asset.status.in_(_STORED_STATES),
                    Asset.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ApiError(
                409, "already_uploaded", "Bu fayl loyihaga allaqachon yuklangan", {"asset_id": str(duplicate)}
            )

        await self._check_capacity(body.size_bytes)

        asset_id = new_id()
        key = original_key(project.id, asset_id, ext)
        content_type = body.content_type or "application/octet-stream"
        upload_id = await asyncio.to_thread(self.storage.create_multipart, key, content_type)
        plan = plan_parts(body.size_bytes, self.settings.upload_part_size)
        now = utcnow()
        sort_index = (
            await self.db.execute(
                select(func.coalesce(func.max(Asset.sort_index), -1)).where(Asset.project_id == project.id)
            )
        ).scalar_one() + 1
        asset = Asset(
            id=asset_id,
            project_id=project.id,
            kind=kind.value,
            status=AssetStatus.UPLOADING.value,
            original_filename=display_name,
            extension=ext,
            content_type=content_type,
            size_bytes=body.size_bytes,
            storage_key=key,
            fingerprint=body.fingerprint,
            file_last_modified=(
                datetime.fromtimestamp(body.last_modified_ms / 1000, UTC) if body.last_modified_ms else None
            ),
            sort_index=sort_index,
            created_at=now,
            updated_at=now,
        )
        sess = UploadSession(
            id=new_id(),
            asset_id=asset_id,
            project_id=project.id,
            user_id=user.id,
            s3_upload_id=upload_id,
            storage_key=key,
            size_bytes=body.size_bytes,
            part_size=plan.part_size,
            part_count=plan.part_count,
            status=UploadSessionStatus.ACTIVE.value,
            bytes_reported=0,
            last_activity_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(asset)
        self.db.add(sess)
        try:
            await self.db.flush()
        except IntegrityError:
            # Another request for the same file won the race; resume that one.
            await self.db.rollback()
            await asyncio.to_thread(self.storage.abort_multipart, key, upload_id)
            again = await self._find_resumable(project.id, body.fingerprint, display_name, body.size_bytes)
            if again is None:
                raise
            return await self.session_out(again[1], resumed=True)
        emit(
            self.db,
            project_id=project.id,
            type=EventType.UPLOAD_STARTED,
            message=f"{display_name}: yuklash boshlandi ({_gb(body.size_bytes)}, {plan.part_count} qism)",
            source="api",
            data={"asset_id": str(asset_id), "size": body.size_bytes, "parts": plan.part_count},
        )
        await refresh_upload_stage_async(self.db, project.id, source="api")
        await touch_project(self.db, project.id)
        await commit_and_publish(self.db, self.redis)
        return await self.session_out(sess)

    async def _find_resumable(
        self, project_id: uuid.UUID, fingerprint: str, filename: str, size: int
    ) -> tuple[Asset, UploadSession] | None:
        base = (
            select(Asset, UploadSession)
            .join(UploadSession, UploadSession.asset_id == Asset.id)
            .where(
                Asset.project_id == project_id,
                Asset.status == AssetStatus.UPLOADING.value,
                UploadSession.status == UploadSessionStatus.ACTIVE.value,
            )
        )
        row = (await self.db.execute(base.where(Asset.fingerprint == fingerprint))).first()
        if row is None:
            # Some pickers (iOS Photos) report a new lastModified on every pick, so
            # fall back to name + size. The client verifies a sample of the parts
            # already in storage against its own MD5s before skipping them.
            row = (
                await self.db.execute(
                    base.where(Asset.original_filename == filename, Asset.size_bytes == size).order_by(
                        Asset.created_at.desc()
                    )
                )
            ).first()
        return (row[0], row[1]) if row else None

    # ------------------------------------------------------------------ parts

    async def sign_parts(self, sess: UploadSession, req: PartSignRequest) -> PartSignResponse:
        if sess.status != UploadSessionStatus.ACTIVE.value:
            raise ApiError(409, "upload_not_active", "Yuklash faol emas")
        signed: list[SignedPart] = []
        for item in req.parts:
            if item.number > sess.part_count:
                raise ApiError(422, "invalid_part", f"Qism raqami {item.number} > {sess.part_count}")
            url, headers, expires_at = self.storage.presign_part(
                sess.storage_key,
                sess.s3_upload_id,
                item.number,
                item.md5_b64,
                self.settings.upload_presign_ttl_seconds,
            )
            signed.append(SignedPart(number=item.number, url=url, headers=headers, expires_at=expires_at))
        await self.db.execute(
            update(UploadSession).where(UploadSession.id == sess.id).values(last_activity_at=utcnow())
        )
        await self.db.commit()
        return PartSignResponse(parts=signed)

    async def report_progress(
        self, sess: UploadSession, bytes_uploaded: int, error: str | None = None
    ) -> None:
        if sess.status != UploadSessionStatus.ACTIVE.value:
            return
        value = min(bytes_uploaded, sess.size_bytes)
        await self.db.execute(
            update(UploadSession)
            .where(UploadSession.id == sess.id)
            .values(bytes_reported=value, last_activity_at=utcnow())
        )
        if error:
            # What went wrong on the phone (network, storage status) — otherwise
            # invisible from the server, since parts go straight to storage.
            asset = await self._asset(sess.asset_id)
            emit(
                self.db,
                project_id=sess.project_id,
                type=EventType.UPLOAD_CLIENT_ERROR,
                level=EventLevel.WARNING,
                message=f"{asset.original_filename}: {error}",
                source="client",
                data={"asset_id": str(sess.asset_id), "bytes": value},
            )
        await refresh_upload_stage_async(self.db, sess.project_id, source="api")
        await commit_and_publish(self.db, self.redis)
        await publish_ephemeral(
            self.redis,
            project_id=sess.project_id,
            type=EventType.UPLOAD_PROGRESS,
            message="upload progress",
            source="api",
            data={"asset_id": str(sess.asset_id), "bytes": value, "size": sess.size_bytes},
        )

    # ------------------------------------------------------------------ complete / abort

    def _verify_parts(self, sess: UploadSession, parts: list[UploadedPart]) -> None:
        by_number = {p.number: p for p in parts}
        missing = [n for n in range(1, sess.part_count + 1) if n not in by_number]
        if missing:
            raise ApiError(
                409,
                "upload_incomplete",
                f"{len(missing)} ta qism hali yuklanmagan",
                {"missing": missing[:100], "missing_count": len(missing)},
            )
        extra = sorted(n for n in by_number if n > sess.part_count)
        wrong = [
            n
            for n in range(1, sess.part_count + 1)
            if by_number[n].size != expected_part_size(n, sess.size_bytes, sess.part_size, sess.part_count)
        ]
        if extra or wrong:
            raise ApiError(
                409,
                "upload_corrupt",
                "Qismlar hajmi kutilganidan farq qiladi",
                {"wrong_size": wrong[:100], "unexpected": extra[:100]},
            )

    async def complete(self, user: User, session_id: uuid.UUID) -> AssetOut:
        sess = await self.get_owned_session(user, session_id, lock=True)
        asset = await self._asset(sess.asset_id)
        if sess.status == UploadSessionStatus.COMPLETED.value:
            return asset_out(asset)
        if sess.status not in _OPEN_SESSION_STATES:
            raise ApiError(409, "upload_not_active", "Yuklash faol emas")

        etag: str
        try:
            parts = await self._list_parts(sess)
            self._verify_parts(sess, parts)
            etag = await asyncio.to_thread(
                self.storage.complete_multipart, sess.storage_key, sess.s3_upload_id, parts
            )
        except NoSuchUploadError:
            # A previous attempt may have completed in storage and crashed
            # before our commit; accept it only if the object is whole.
            info = await asyncio.to_thread(self.storage.head, sess.storage_key)
            if info is None or info.size != sess.size_bytes:
                await self._mark_gone(sess, asset)
                raise ApiError(
                    410, "upload_gone", "Bu yuklash muddati o'tgan — faylni qaytadan yuklang"
                ) from None
            etag = info.etag

        info = await asyncio.to_thread(self.storage.head, sess.storage_key)
        if info is None or info.size != sess.size_bytes:
            raise ApiError(500, "storage_mismatch", "Storage'dagi fayl hajmi mos kelmadi")

        now = utcnow()
        sess.status = UploadSessionStatus.COMPLETED.value
        sess.completed_at = now
        sess.bytes_reported = sess.size_bytes
        asset.status = AssetStatus.UPLOADED.value
        asset.etag = etag
        asset.uploaded_at = now
        asset.error = None
        emit(
            self.db,
            project_id=sess.project_id,
            type=EventType.UPLOAD_COMPLETED,
            message=f"{asset.original_filename}: yuklandi va tekshirildi ({_gb(asset.size_bytes)}, ETag {etag[:12]}…)",
            source="api",
            data={"asset_id": str(asset.id), "size": asset.size_bytes, "etag": etag},
        )
        await enqueue_async(
            self.db,
            kind=JobKind.INGEST_ASSET,
            queue=JobQueue.CPU,
            payload={"asset_id": str(asset.id)},
            project_id=sess.project_id,
            priority=JobPriority.HIGH,
            idempotency_key=f"{JobKind.INGEST_ASSET}:{asset.id}",
            max_attempts=3,
        )
        await refresh_upload_stage_async(self.db, sess.project_id, source="api")
        waiting = (
            await self.db.execute(
                select(func.count()).where(
                    Asset.project_id == sess.project_id, Asset.status == AssetStatus.UPLOADED.value
                )
            )
        ).scalar_one()
        await set_stage_async(
            self.db,
            sess.project_id,
            Stage.INGEST,
            StageState(StageStatus.QUEUED, None, f"{waiting} ta fayl navbatda"),
            source="api",
        )
        await touch_project(self.db, sess.project_id)
        await commit_and_publish(self.db, self.redis)
        return asset_out(asset)

    async def abort(self, user: User, session_id: uuid.UUID) -> AssetOut:
        sess = await self.get_owned_session(user, session_id, lock=True)
        asset = await self._asset(sess.asset_id)
        if sess.status == UploadSessionStatus.COMPLETED.value:
            raise ApiError(409, "upload_completed", "Yuklash allaqachon tugagan")
        if sess.status in _OPEN_SESSION_STATES:
            await asyncio.to_thread(self.storage.abort_multipart, sess.storage_key, sess.s3_upload_id)
            sess.status = UploadSessionStatus.ABORTED.value
            asset.status = AssetStatus.CANCELLED.value
            emit(
                self.db,
                project_id=sess.project_id,
                type=EventType.UPLOAD_CANCELLED,
                level=EventLevel.WARNING,
                message=f"{asset.original_filename}: yuklash bekor qilindi",
                source="api",
                data={"asset_id": str(asset.id)},
            )
            await refresh_upload_stage_async(self.db, sess.project_id, source="api")
            await commit_and_publish(self.db, self.redis)
        return asset_out(asset)
