"""Ingestion (spec §9-11, Phase 3): what arrives in storage becomes something
every later stage can work with — normalized metadata and colour detection, a
playable 720p proxy, thumbnails and a filmstrip, a 16 kHz speech track for
Whisper, loudness, scene cuts and a SHA-256 of the original.

The original is only ever *read* (streamed from storage over the private
network); every output is a derived file under a deterministic key, so running
the job again overwrites instead of duplicating (spec rules 1, 9).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.ids import new_id
from synthcut_core.jobs import enqueue
from synthcut_core.models import Asset, MediaFile, Project, User, utcnow
from synthcut_core.stages import refresh_ingest_stage
from synthcut_media import (
    MediaError,
    MediaInfo,
    audio_main_pass,
    image_preview,
    normalize,
    parse_loudness,
    parse_scene_cuts,
    plan_proxy,
    poster,
    run_ffmpeg,
    run_ffprobe,
    shots_from_cuts,
    video_main_pass,
)
from synthcut_schemas.enums import AssetStatus, EventLevel, JobPriority, JobQueue, StageStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import IngestAssetPayload, JobKind
from synthcut_storage import Area, derived_key

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..registry import handler

INTERNAL_URL_TTL = 6 * 3600

# kind -> (storage area, file name)
LAYOUT: dict[str, tuple[Area, str]] = {
    "proxy_720p": (Area.PROXIES, "proxy_720p.mp4"),
    "audio_proxy": (Area.AUDIO, "audio_proxy.m4a"),
    "audio_speech": (Area.AUDIO, "speech_16k.flac"),
    "poster": (Area.THUMBNAILS, "poster.jpg"),
    "sprite": (Area.THUMBNAILS, "sprite.jpg"),
    "preview": (Area.THUMBNAILS, "preview.jpg"),
    "shots": (Area.ANALYSIS, "shots.json"),
    "mediainfo": (Area.ANALYSIS, "mediainfo.json"),
}


@dataclass(frozen=True, slots=True)
class AssetRef:
    id: uuid.UUID
    project_id: uuid.UUID
    key: str
    size: int
    name: str


@dataclass
class Derived:
    kind: str
    path: Path
    content_type: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    key: str = ""
    size: int = 0


@dataclass
class Outcome:
    info: MediaInfo
    sha256: str
    files: list[Derived]
    shots: list[dict[str, float]] | None


# --------------------------------------------------------------------------- lifecycle


def _start(
    ctx: JobContext, asset_id: uuid.UUID, *, force: bool = False
) -> tuple[AssetRef | None, str | None]:
    with ctx.session() as s:
        asset = s.get(Asset, asset_id, with_for_update=True)
        if asset is None or asset.deleted_at is not None:
            return None, "asset_missing"
        if asset.project_id != ctx.job.project_id:
            # Worker sandbox (spec §39): a job may only touch its own project.
            raise PermanentError("asset belongs to another project")
        if asset.status == AssetStatus.READY.value and not force:
            return None, "already_ready"
        if asset.status not in (
            AssetStatus.UPLOADED.value,
            AssetStatus.INGESTING.value,
            AssetStatus.FAILED.value,
            AssetStatus.READY.value,
        ):
            raise PermanentError(f"asset is {asset.status}, not uploaded")
        asset.status = AssetStatus.INGESTING.value
        asset.error = None
        refresh_ingest_stage(s, asset.project_id, source="worker")
        ref = AssetRef(
            asset.id, asset.project_id, asset.storage_key, asset.size_bytes, asset.original_filename
        )
        commit_and_publish_sync(s, ctx.redis)
    return ref, None


def _set_waiting(ctx: JobContext, ref: AssetRef, note: str | None) -> None:
    with ctx.session() as s:
        asset = s.get(Asset, ref.id, with_for_update=True)
        if asset is not None and asset.status == AssetStatus.INGESTING.value:
            asset.status = AssetStatus.UPLOADED.value
            asset.error = note
            refresh_ingest_stage(s, ref.project_id, source="worker")
            commit_and_publish_sync(s, ctx.redis)


def _fail(ctx: JobContext, ref: AssetRef, message: str) -> None:
    with ctx.session() as s:
        asset = s.get(Asset, ref.id, with_for_update=True)
        if asset is None:
            return
        asset.status = AssetStatus.FAILED.value
        asset.error = message[:500]
        emit(
            s,
            project_id=ref.project_id,
            type=EventType.ASSET_INGEST_FAILED,
            level=EventLevel.ERROR,
            message=f"{ref.name}: tahlil qilinmadi — {message[:200]}",
            source="worker",
            data={"asset_id": str(ref.id)},
            job_id=ctx.job.id,
        )
        refresh_ingest_stage(s, ref.project_id, source="worker")
        commit_and_publish_sync(s, ctx.redis)


@handler(JobKind.INGEST_ASSET, queue=JobQueue.CPU)
def ingest_asset(ctx: JobContext, payload: IngestAssetPayload) -> dict[str, Any]:
    ref, skipped = _start(ctx, payload.asset_id, force=payload.force)
    if ref is None:
        return {"skipped": skipped}
    try:
        outcome = _ingest(ctx, ref)
    except LeaseLost:
        raise  # another worker owns the job (and the asset's status) now
    except (JobCancelled, JobInterrupted):
        _set_waiting(ctx, ref, None)
        raise
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, ref, str(exc))
            raise PermanentError(str(exc)) from exc
        _set_waiting(ctx, ref, f"qayta urinish: {exc}"[:500])
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        if ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, ref, f"{type(exc).__name__}: {exc}")
        else:
            _set_waiting(ctx, ref, f"qayta urinish: {type(exc).__name__}"[:500])
        raise
    _finish(ctx, ref, outcome)
    info = outcome.info
    return {
        "kind": info.kind,
        "duration": info.duration,
        "color": info.color.profile if info.color else None,
        "files": [f.kind for f in outcome.files],
        "shots": len(outcome.shots or []),
    }


# --------------------------------------------------------------------------- work


def _timeout(duration: float | None) -> float:
    # Generous: 4K HEVC on two shared cores can run well below real time.
    return min(6 * 3600, 600 + (duration or 60) * 40)


def _sha256(ctx: JobContext, ref: AssetRef, start: float, span: float) -> str:
    digest = hashlib.sha256()
    done = 0
    for chunk in ctx.storage.iter_object(ref.key):
        digest.update(chunk)
        done += len(chunk)
        ctx.progress(start + span * done / max(ref.size, 1), "sha256", data={"asset_id": str(ref.id)})
        ctx.check()
    if done != ref.size:
        raise MediaError(f"original is {done} bytes, expected {ref.size}", permanent=False)
    return digest.hexdigest()


def _image_size(path: Path) -> tuple[int | None, int | None]:
    info = normalize(run_ffprobe(str(path), timeout=30), size_bytes=path.stat().st_size)
    return (info.video.width, info.video.height) if info.video else (None, None)


def _ingest(ctx: JobContext, ref: AssetRef) -> Outcome:
    settings = ctx.settings
    tag = {"asset_id": str(ref.id)}
    work = ctx.scratch_dir
    url = ctx.storage.internal_get_url(ref.key, INTERNAL_URL_TTL)

    ctx.progress(0.01, "ffprobe", data=tag)
    info = normalize(run_ffprobe(url), size_bytes=ref.size)
    if info.kind == "other":
        raise MediaError("Faylda video, audio yoki rasm oqimi topilmadi", permanent=True)
    sha = _sha256(ctx, ref, 0.02, 0.13)
    files: list[Derived] = []
    shots: list[dict[str, float]] | None = None

    def progress(start: float, span: float, message: str):
        return lambda f: ctx.progress(start + span * f, message, data=tag)

    if info.kind == "video":
        assert info.video is not None
        plan = plan_proxy(info, short_side=settings.media_proxy_short_side)
        proxy = work / "proxy_720p.mp4"
        speech = work / "speech_16k.flac" if info.audio else None
        sprite_path = work / "sprite.jpg"
        duration = info.duration or 0.0
        tiles = max(1, min(12, int(duration)))
        log = run_ffmpeg(
            video_main_pass(
                url,
                plan=plan,
                proxy=proxy,
                speech=speech,
                sprite_path=sprite_path,
                sprite_tiles=tiles,
                duration=duration,
                threads=settings.media_threads,
            ),
            duration=info.duration,
            on_progress=progress(0.15, 0.80, "proxy"),
            check=ctx.check,
            timeout=_timeout(info.duration),
        )
        if speech is not None:
            info.loudness = parse_loudness(log)
        pinfo = normalize(run_ffprobe(str(proxy), timeout=60), size_bytes=proxy.stat().st_size)
        # Source time, not the proxy file's length (AAC priming can add ~20 ms).
        duration = info.duration or pinfo.duration or 0.0
        assert pinfo.video is not None
        files.append(
            Derived(
                "proxy_720p",
                proxy,
                "video/mp4",
                pinfo.video.width,
                pinfo.video.height,
                duration,
                {"color": plan.color_note, "tonemapped": plan.tonemap, "fps": pinfo.video.fps},
            )
        )
        if speech is not None:
            files.append(
                Derived("audio_speech", speech, "audio/flac", duration=duration, meta={"rate": 16000})
            )

        ctx.progress(0.96, "thumbnails", data=tag)
        poster_path = work / "poster.jpg"
        run_ffmpeg(poster(proxy, poster_path, at=min(1.0, duration * 0.1)), check=ctx.check, timeout=120)
        files.append(Derived("poster", poster_path, "image/jpeg", *_image_size(poster_path)))
        if sprite_path.exists():
            sw, sh = _image_size(sprite_path)
            files.append(
                Derived(
                    "sprite",
                    sprite_path,
                    "image/jpeg",
                    sw,
                    sh,
                    meta={
                        "tiles": tiles,
                        "tile_width": (sw or 0) // tiles,
                        "interval": round(duration / tiles, 3),
                    },
                )
            )

        cuts = parse_scene_cuts(log.splitlines())
        shots = shots_from_cuts(cuts, duration)
        shots_path = work / "shots.json"
        shots_path.write_text(
            json.dumps(
                {
                    "schema_version": "shots/1",
                    "cuts": [{"time": t, "score": s} for t, s in cuts],
                    "shots": shots,
                }
            )
        )
        files.append(
            Derived(
                "shots", shots_path, "application/json", meta={"count": len(shots), "shots": shots[:2000]}
            )
        )

    elif info.kind == "audio":
        proxy = work / "audio_proxy.m4a"
        speech = work / "speech_16k.flac"
        log = run_ffmpeg(
            audio_main_pass(url, proxy=proxy, speech=speech, threads=settings.media_threads),
            duration=info.duration,
            on_progress=progress(0.15, 0.80, "audio"),
            check=ctx.check,
            timeout=_timeout(info.duration),
        )
        info.loudness = parse_loudness(log)
        files.append(Derived("audio_proxy", proxy, "audio/mp4", duration=info.duration))
        files.append(
            Derived("audio_speech", speech, "audio/flac", duration=info.duration, meta={"rate": 16000})
        )

    else:  # image
        preview = work / "preview.jpg"
        run_ffmpeg(image_preview(url, preview, longest=1600), check=ctx.check, timeout=300)
        files.append(Derived("preview", preview, "image/jpeg", *_image_size(preview)))
        poster_path = work / "poster.jpg"
        run_ffmpeg(image_preview(str(preview), poster_path, longest=640), check=ctx.check, timeout=120)
        files.append(Derived("poster", poster_path, "image/jpeg", *_image_size(poster_path)))

    mediainfo = work / "mediainfo.json"
    mediainfo.write_text(info.model_dump_json())
    files.append(Derived("mediainfo", mediainfo, "application/json"))

    ctx.progress(0.97, "saqlash", data=tag)
    for f in files:
        area, name = LAYOUT[f.kind]
        f.key = derived_key(ref.project_id, area, ref.id, name)
        f.size = f.path.stat().st_size
        ctx.storage.put_derived_file(f.key, f.path, f.content_type)
        ctx.check()
    return Outcome(info=info, sha256=sha, files=files, shots=shots)


# --------------------------------------------------------------------------- results


def _summary(info: MediaInfo, shots: list[dict[str, float]] | None) -> str:
    parts: list[str] = []
    if info.video is not None and info.kind == "video":
        parts.append(f"{info.video.display_width}×{info.video.display_height}")
        if info.video.fps:
            parts.append(f"{info.video.fps:g} fps")
    if info.duration:
        parts.append(f"{info.duration:.1f}s")
    if info.color is not None and info.kind == "video":
        parts.append(info.color.label)
    if shots is not None:
        parts.append(f"{len(shots)} shot")
    if info.loudness and info.loudness.integrated_lufs is not None:
        parts.append(f"{info.loudness.integrated_lufs:.1f} LUFS")
    return " · ".join(parts)


def _finish(ctx: JobContext, ref: AssetRef, outcome: Outcome) -> None:
    info = outcome.info
    now = utcnow()
    with ctx.session() as s:
        asset = s.get(Asset, ref.id, with_for_update=True)
        if asset is None:
            return
        for f in outcome.files:
            stmt = pg_insert(MediaFile).values(
                id=new_id(),
                asset_id=ref.id,
                project_id=ref.project_id,
                kind=f.kind,
                storage_key=f.key,
                content_type=f.content_type,
                size_bytes=f.size,
                width=f.width,
                height=f.height,
                duration_sec=f.duration,
                meta=f.meta,
                created_at=now,
                updated_at=now,
            )
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=[MediaFile.asset_id, MediaFile.kind],
                    set_={
                        "storage_key": stmt.excluded.storage_key,
                        "content_type": stmt.excluded.content_type,
                        "size_bytes": stmt.excluded.size_bytes,
                        "width": stmt.excluded.width,
                        "height": stmt.excluded.height,
                        "duration_sec": stmt.excluded.duration_sec,
                        "metadata": stmt.excluded.metadata,
                        "updated_at": now,
                    },
                )
            )
        video = info.video if info.kind in ("video", "image") else None
        asset.kind = info.kind
        asset.media_info = info.model_dump(mode="json")
        asset.duration_sec = info.duration
        asset.width = video.display_width if video else None
        asset.height = video.display_height if video else None
        asset.fps = video.fps if video and info.kind == "video" else None
        asset.video_codec = video.codec if video else None
        asset.audio_codec = info.audio.codec if info.audio else None
        asset.color_profile = info.color.profile if info.color else None
        asset.has_audio = info.audio is not None
        asset.bit_depth = video.bit_depth if video else None
        asset.rotation = video.rotation if video else None
        asset.sha256 = outcome.sha256
        asset.status = AssetStatus.READY.value
        asset.ready_at = now
        asset.error = None
        emit(
            s,
            project_id=ref.project_id,
            type=EventType.ASSET_INGESTED,
            message=f"{ref.name}: tahlil qilindi — {_summary(info, outcome.shots)}",
            source="worker",
            data={"asset_id": str(ref.id), "kind": info.kind, "files": [f.kind for f in outcome.files]},
            job_id=ctx.job.id,
        )
        state, changed = refresh_ingest_stage(s, ref.project_id, source="worker")
        if changed and state.status is StageStatus.DONE and ctx.settings.notify_telegram:
            _notify_ingest_done(s, ctx, ref.project_id, state.detail or "")
        commit_and_publish_sync(s, ctx.redis)


def _notify_ingest_done(s, ctx: JobContext, project_id: uuid.UUID, detail: str) -> None:
    row = s.execute(
        select(Project.name, User.telegram_id)
        .join(User, User.id == Project.owner_id)
        .where(Project.id == project_id)
    ).one_or_none()
    if row is None:
        return
    ready = s.execute(
        select(func.count()).where(Asset.project_id == project_id, Asset.status == AssetStatus.READY.value)
    ).scalar_one()
    enqueue(
        s,
        kind=JobKind.NOTIFY_TELEGRAM,
        queue=JobQueue.IO,
        priority=JobPriority.HIGH,
        payload={
            "chat_id": row.telegram_id,
            "text": f"✅ <b>{escape(row.name)}</b>\nMedia tahlili tugadi: {escape(detail)}.\n"
            "Proxy, thumbnail, nutq audiosi va kadr kesimlari tayyor.",
            "open_project_id": str(project_id),
        },
        project_id=project_id,
        idempotency_key=f"notify.ingest_done:{project_id}:{ready}",
        max_attempts=4,
    )
