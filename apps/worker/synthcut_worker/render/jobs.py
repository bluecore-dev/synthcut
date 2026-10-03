"""Caption preview (Phase 7): one asset with animated captions burned in —
the motion engine end to end before the Director exists. A one-clip
EditPlan → ``overlay/1`` → Remotion (transparent ProRes 4444) → FFmpeg over
the 720p proxy → ``previews/<asset>/captions.mp4``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Asset, AssetTranscript, MediaFile, utcnow
from synthcut_media import MediaError, composite_overlay, run_ffmpeg
from synthcut_schemas.enums import ALLOWED_FPS, EventLevel, JobQueue, TranscriptStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import CaptionPreviewPayload, JobKind
from synthcut_schemas.speech import Transcript
from synthcut_storage import Area, derived_key
from synthcut_timeline import (
    AssetFacts,
    CaptionTrack,
    EditPlan,
    Sequence,
    VideoClip,
    VideoTrack,
    ensure_valid,
)
from synthcut_timeline.overlay import build_overlay

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..derived import upsert_media_file
from ..registry import handler
from .remotion import RemotionUnavailable, render_overlay

INTERNAL_URL_TTL = 6 * 3600


def preview_fps(source_fps: float | None) -> int:
    """The overlay's frame rate: the nearest allowed rate, at most 30 — captions
    gain nothing from 60 fps, and every frame costs a browser screenshot."""
    fps = source_fps or 30.0
    nearest = min(ALLOWED_FPS, key=lambda f: abs(f - fps))
    return nearest if nearest <= 30 else nearest // 2


def preview_plan(
    *,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    width: int,
    height: int,
    source_fps: float | None,
    duration: float,
    style: str,
    position: str,
) -> EditPlan:
    fps = preview_fps(source_fps)
    length = math.floor(duration * fps) / fps  # whole frames, never past the source
    return EditPlan(
        project_id=project_id,
        version=1,
        sequence=Sequence(fps=fps, width=width, height=height, duration=length),
        video_tracks=[
            VideoTrack(
                track=1,
                role="main",
                clips=[
                    VideoClip(
                        id="source",
                        asset_id=asset_id,
                        source_in=0,
                        source_out=length,
                        timeline_start=0,
                        timeline_end=length,
                    )
                ],
            )
        ],
        captions=CaptionTrack(
            enabled=True,
            style=style,
            position=position,
            max_words_per_line=3 if height > width else 4,
        ),
    )


@dataclass(frozen=True, slots=True)
class Target:
    asset_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    proxy_key: str
    plan: EditPlan
    transcript: Transcript


def _start(ctx: JobContext, payload: CaptionPreviewPayload) -> Target:
    with ctx.session() as s:
        asset = s.get(Asset, payload.asset_id)
        if asset is None or asset.deleted_at is not None:
            raise PermanentError("asset_missing")
        if asset.project_id != ctx.job.project_id:
            raise PermanentError("asset belongs to another project")  # worker sandbox (spec §39)
        proxy = s.scalar(
            select(MediaFile).where(MediaFile.asset_id == asset.id, MediaFile.kind == "proxy_720p")
        )
        row = s.scalar(select(AssetTranscript).where(AssetTranscript.asset_id == asset.id))
        if proxy is None or not proxy.width or not proxy.height:
            raise PermanentError("Faylda proxy video yo'q")
        if row is None or row.status != TranscriptStatus.DONE.value or row.data is None:
            raise PermanentError("Avval nutq matnga o'girilishi kerak")
        duration = float(asset.duration_sec or proxy.duration_sec or 0)
        if duration <= 0:
            raise PermanentError("Video davomiyligi noma'lum")
        plan = preview_plan(
            project_id=asset.project_id,
            asset_id=asset.id,
            width=proxy.width,
            height=proxy.height,
            source_fps=float(proxy.meta.get("fps") or asset.fps or 30),
            duration=duration,
            style=payload.style,
            position=payload.position,
        )
        # Plans are executed only after validation (spec rule 6).
        ensure_valid(plan, assets={asset.id: AssetFacts(kind="video", duration=duration)})
        return Target(
            asset_id=asset.id,
            project_id=asset.project_id,
            name=asset.original_filename,
            proxy_key=proxy.storage_key,
            plan=plan,
            transcript=Transcript.model_validate(row.data),
        )


def _render(ctx: JobContext, target: Target) -> tuple[Path, int]:
    tag = {"asset_id": str(target.asset_id)}
    work = ctx.scratch_dir
    overlay = build_overlay(target.plan, {target.asset_id: target.transcript})
    lines = len(overlay.captions.lines) if overlay.captions else 0
    ctx.progress(0.02, "motion", data=tag)
    layer = render_overlay(
        overlay,
        work,
        remotion_dir=Path(ctx.settings.remotion_dir),
        concurrency=ctx.settings.remotion_concurrency,
        on_progress=lambda f: ctx.progress(0.02 + 0.73 * f, "motion", data=tag),
        check=ctx.check,
    )
    ctx.progress(0.76, "kompozit", data=tag)
    out = work / "captions.mp4"
    background = ctx.storage.internal_get_url(target.proxy_key, INTERNAL_URL_TTL)
    run_ffmpeg(
        composite_overlay(background, layer, out, threads=ctx.settings.media_threads),
        duration=target.plan.sequence.duration,
        on_progress=lambda f: ctx.progress(0.76 + 0.22 * f, "kompozit", data=tag),
        check=ctx.check,
        timeout=600 + target.plan.sequence.duration * 10,
    )
    layer.unlink(missing_ok=True)
    return out, lines


def _fail(ctx: JobContext, target: Target | None, payload: CaptionPreviewPayload, message: str) -> None:
    if ctx.job.project_id is None:
        return
    with ctx.session() as s:
        name = target.name if target else str(payload.asset_id)
        emit(
            s,
            project_id=ctx.job.project_id,
            type=EventType.PREVIEW_FAILED,
            level=EventLevel.ERROR,
            message=f"{name}: subtitrli video yaratilmadi — {message[:200]}",
            source="worker",
            data={"asset_id": str(payload.asset_id)},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)


@handler(JobKind.RENDER_CAPTION_PREVIEW, queue=JobQueue.RENDER)
def caption_preview(ctx: JobContext, payload: CaptionPreviewPayload) -> dict[str, Any]:
    target: Target | None = None
    try:
        target = _start(ctx, payload)
        out, lines = _render(ctx, target)
    except (LeaseLost, JobInterrupted, JobCancelled):
        raise
    except PermanentError as exc:
        _fail(ctx, target, payload, str(exc))
        raise
    except RemotionUnavailable as exc:
        _fail(ctx, target, payload, "Motion dvigateli o'rnatilmagan")
        raise PermanentError(f"Motion dvigateli o'rnatilmagan ({exc})") from exc
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, target, payload, str(exc))
            raise PermanentError(str(exc)) from exc
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        if ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, target, payload, f"{type(exc).__name__}: {exc}")
        raise

    key = derived_key(target.project_id, Area.PREVIEWS, target.asset_id, "captions.mp4")
    ctx.progress(0.99, "saqlash", data={"asset_id": str(target.asset_id)})
    ctx.storage.put_derived_file(key, out, "video/mp4")
    seq = target.plan.sequence
    with ctx.session() as s:
        if s.get(Asset, target.asset_id) is None:
            return {"skipped": "asset_deleted"}
        upsert_media_file(
            s,
            asset_id=target.asset_id,
            project_id=target.project_id,
            kind="caption_preview",
            storage_key=key,
            content_type="video/mp4",
            size_bytes=out.stat().st_size,
            now=utcnow(),
            width=seq.width,
            height=seq.height,
            duration_sec=seq.duration,
            meta={"style": payload.style, "position": payload.position, "lines": lines, "fps": seq.fps},
        )
        emit(
            s,
            project_id=target.project_id,
            type=EventType.PREVIEW_READY,
            message=f"{target.name}: subtitrli video tayyor — {payload.style}, {lines} qator",
            source="worker",
            data={"asset_id": str(target.asset_id), "style": payload.style},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)
    return {"style": payload.style, "lines": lines, "duration": seq.duration}
