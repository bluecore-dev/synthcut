"""Shot analysis (spec §12, Phase 5): the proxy and speech track that
ingestion made → one ``clipanalysis/1`` record per shot (framing, faces,
camera motion, sharpness, exposure, speech, duplicates, usability), a JPEG
sheet per shot for people and the vision agent, and ``clips.json``.

Measurements only — the semantic fields wait for the vision agent (5b).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from synthcut_analysis.clips import ClipContext
from synthcut_analysis.pipeline import AssetAnalysis as Result
from synthcut_analysis.pipeline import analyze
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Asset, AssetAnalysis, ClipAnalysisRow, MediaFile, utcnow
from synthcut_core.stages import refresh_analysis_stage
from synthcut_media import MediaError
from synthcut_schemas.analysis import Span
from synthcut_schemas.enums import AnalysisStatus, EventLevel, JobQueue
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import AnalyzeAssetPayload, JobKind
from synthcut_speech.audio import load_pcm
from synthcut_speech.vad import speech_spans
from synthcut_storage import Area, derived_key

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..derived import upsert_media_file
from ..registry import handler

FLAG_WORDS = {
    "blurry": "xira",
    "underexposed": "qorong'i",
    "overexposed": "o'ta yorug'",
    "shaky": "silkingan",
    "duplicate": "takror",
    "black": "qora",
    "frozen": "qotgan",
    "too_short": "juda qisqa",
}


@dataclass(frozen=True, slots=True)
class Target:
    asset_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    proxy_key: str
    width: int
    height: int
    speech_key: str | None
    duration: float
    shots: list[tuple[float, float]]
    ctx: ClipContext
    known_hashes: dict[str, str]
    old_sheets: list[str]


def _start(ctx: JobContext, payload: AnalyzeAssetPayload) -> tuple[Target | None, str | None]:
    with ctx.session() as s:
        asset = s.get(Asset, payload.asset_id)
        if asset is None or asset.deleted_at is not None:
            return None, "asset_missing"
        if asset.project_id != ctx.job.project_id:
            raise PermanentError("asset belongs to another project")  # worker sandbox (spec §39)
        row = s.execute(
            select(AssetAnalysis).where(AssetAnalysis.asset_id == asset.id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            row = AssetAnalysis(asset_id=asset.id, project_id=asset.project_id, runs=1)
            s.add(row)
        elif row.status == AnalysisStatus.DONE.value and not payload.force:
            return None, "already_done"
        files = {m.kind: m for m in s.scalars(select(MediaFile).where(MediaFile.asset_id == asset.id))}
        proxy = files.get("proxy_720p")
        if asset.kind != "video" or proxy is None or not proxy.width or not proxy.height:
            row.status = AnalysisStatus.FAILED.value
            row.error = "Faylda tahlil qilinadigan video yo'q"
            refresh_analysis_stage(s, asset.project_id, source="worker")
            commit_and_publish_sync(s, ctx.redis)
            return None, "no_video"
        shots_file = files.get("shots")
        shots = [
            (float(x["start"]), float(x["end"]))
            for x in (shots_file.meta.get("shots", []) if shots_file else [])
        ]
        duration = float(asset.duration_sec or proxy.duration_sec or 0.0)
        known = {
            clip_id: digest
            for clip_id, digest in s.execute(
                select(ClipAnalysisRow.clip_id, ClipAnalysisRow.dhash).where(
                    ClipAnalysisRow.project_id == asset.project_id,
                    ClipAnalysisRow.asset_id != asset.id,
                    ClipAnalysisRow.dhash.is_not(None),
                )
            ).all()
        }
        old_sheets = [
            k
            for k in s.scalars(select(ClipAnalysisRow.sheet_key).where(ClipAnalysisRow.asset_id == asset.id))
            if k
        ]
        row.status = AnalysisStatus.RUNNING.value
        row.error = None
        row.started_at = utcnow()
        refresh_analysis_stage(s, asset.project_id, source="worker")
        target = Target(
            asset_id=asset.id,
            project_id=asset.project_id,
            name=asset.original_filename,
            proxy_key=proxy.storage_key,
            width=proxy.width,
            height=proxy.height,
            speech_key=files["audio_speech"].storage_key if "audio_speech" in files else None,
            duration=duration,
            shots=shots,
            ctx=ClipContext(
                asset_prefix=str(asset.id)[:8],
                resolution=f"{asset.width}x{asset.height}" if asset.width and asset.height else None,
                fps=asset.fps,
                color_profile=asset.color_profile,
                audio_present=bool(asset.has_audio),
            ),
            known_hashes=known,
            old_sheets=old_sheets,
        )
        commit_and_publish_sync(s, ctx.redis)
    return target, None


def _set_status(ctx: JobContext, target: Target, status: AnalysisStatus, error: str | None) -> None:
    with ctx.session() as s:
        row = s.execute(
            select(AssetAnalysis).where(AssetAnalysis.asset_id == target.asset_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return
        row.status = status.value
        row.error = error[:500] if error else None
        if status is AnalysisStatus.FAILED:
            row.finished_at = utcnow()
            emit(
                s,
                project_id=target.project_id,
                type=EventType.ANALYSIS_FAILED,
                level=EventLevel.ERROR,
                message=f"{target.name}: kadrlar tahlil qilinmadi — {(error or '')[:200]}",
                source="worker",
                data={"asset_id": str(target.asset_id)},
                job_id=ctx.job.id,
            )
        refresh_analysis_stage(s, target.project_id, source="worker")
        commit_and_publish_sync(s, ctx.redis)


@handler(JobKind.ANALYZE_ASSET, queue=JobQueue.CPU)
def analyze_asset(ctx: JobContext, payload: AnalyzeAssetPayload) -> dict[str, Any]:
    target, skipped = _start(ctx, payload)
    if target is None:
        return {"skipped": skipped}
    try:
        result, sheets, clips_size = _analyze(ctx, target)
    except LeaseLost:
        raise
    except JobInterrupted:
        _set_status(ctx, target, AnalysisStatus.QUEUED, None)
        raise
    except JobCancelled:
        _set_status(ctx, target, AnalysisStatus.FAILED, "bekor qilindi")
        raise
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _set_status(ctx, target, AnalysisStatus.FAILED, str(exc))
            raise PermanentError(str(exc)) from exc
        _set_status(ctx, target, AnalysisStatus.QUEUED, f"qayta urinish: {exc}")
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        last = ctx.job.attempts >= ctx.job.max_attempts
        _set_status(
            ctx,
            target,
            AnalysisStatus.FAILED if last else AnalysisStatus.QUEUED,
            f"{type(exc).__name__}: {exc}",
        )
        raise
    _finish(ctx, target, result, sheets, clips_size)
    return {"clips": len(result.clips), "sample_fps": result.sample_fps}


def _analyze(ctx: JobContext, target: Target) -> tuple[Result, dict[int, str], int]:
    tag = {"asset_id": str(target.asset_id)}
    work = ctx.scratch_dir
    ctx.progress(0.01, "proxy", data=tag)
    proxy = work / "proxy.mp4"
    ctx.storage.download_file(target.proxy_key, proxy)
    ctx.check()
    speech: list[Span] | None = None
    if target.speech_key and target.ctx.audio_present:
        ctx.progress(0.05, "nutq joylari", data=tag)
        flac = work / "speech.flac"
        ctx.storage.download_file(target.speech_key, flac)
        speech = speech_spans(load_pcm(flac, work, check=ctx.check))
        flac.unlink(missing_ok=True)
    result = analyze(
        proxy,
        work,
        ctx=target.ctx,
        width=target.width,
        height=target.height,
        duration=target.duration,
        shots=target.shots,
        speech=speech,
        known_hashes=target.known_hashes,
        check=ctx.check,
        on_progress=lambda f: ctx.progress(0.1 + 0.85 * f, "kadrlar", data=tag),
    )
    ctx.progress(0.97, "saqlash", data=tag)
    sheet_keys: dict[int, str] = {}
    for index, body in result.sheets.items():
        key = derived_key(target.project_id, Area.ANALYSIS, target.asset_id, f"shot_{index:03d}.jpg")
        ctx.storage.put_derived_bytes(key, body, "image/jpeg")
        sheet_keys[index] = key
        ctx.check()
    clips_json = json.dumps([c.model_dump(mode="json") for c in result.clips]).encode()
    ctx.storage.put_derived_bytes(
        derived_key(target.project_id, Area.ANALYSIS, target.asset_id, "clips.json"),
        clips_json,
        "application/json",
    )
    return result, sheet_keys, len(clips_json)


def _summary(result: Result) -> str:
    clips = result.clips
    if not clips:
        return "kadr topilmadi"
    avg = sum(c.usable_score for c in clips) / len(clips)
    counts: dict[str, int] = {}
    for c in clips:
        for f in c.flags:
            counts[f] = counts.get(f, 0) + 1
    issues = ", ".join(
        f"{n} {FLAG_WORDS.get(f, f)}" for f, n in sorted(counts.items(), key=lambda x: -x[1])[:3]
    )
    return f"{len(clips)} kadr · yaroqlilik {round(avg * 100)}%" + (f" · {issues}" if issues else "")


def _finish(ctx: JobContext, target: Target, result: Result, sheets: dict[int, str], clips_size: int) -> None:
    now = utcnow()
    with ctx.session() as s:
        row = s.execute(
            select(AssetAnalysis).where(AssetAnalysis.asset_id == target.asset_id).with_for_update()
        ).scalar_one_or_none()
        if row is None or s.get(Asset, target.asset_id) is None:
            return  # the asset was deleted meanwhile
        s.execute(delete(ClipAnalysisRow).where(ClipAnalysisRow.asset_id == target.asset_id))
        for clip in result.clips:
            s.add(
                ClipAnalysisRow(
                    asset_id=target.asset_id,
                    project_id=target.project_id,
                    clip_id=clip.clip_id,
                    shot_index=clip.index,
                    start_sec=clip.start,
                    end_sec=clip.end,
                    shot_type=clip.shot_type,
                    camera_motion=clip.camera_motion,
                    usable_score=clip.usable_score,
                    flags=list(clip.flags),
                    dhash=result.hashes.get(clip.index),
                    sheet_key=sheets.get(clip.index),
                    data=clip.model_dump(mode="json"),
                )
            )
        clips_key = derived_key(target.project_id, Area.ANALYSIS, target.asset_id, "clips.json")
        upsert_media_file(
            s,
            asset_id=target.asset_id,
            project_id=target.project_id,
            kind="clips",
            storage_key=clips_key,
            content_type="application/json",
            size_bytes=clips_size,
            now=now,
            meta={"count": len(result.clips)},
        )
        clips = result.clips
        row.status = AnalysisStatus.DONE.value
        row.source = "metrics"
        row.clip_count = len(clips)
        row.usable_avg = round(sum(c.usable_score for c in clips) / len(clips), 3) if clips else None
        row.sample_fps = result.sample_fps
        row.error = None
        row.finished_at = now
        emit(
            s,
            project_id=target.project_id,
            type=EventType.ANALYSIS_READY,
            message=f"{target.name}: kadrlar tahlil qilindi — {_summary(result)}",
            source="worker",
            data={"asset_id": str(target.asset_id), "clips": len(clips)},
            job_id=ctx.job.id,
        )
        refresh_analysis_stage(s, target.project_id, source="worker")
        commit_and_publish_sync(s, ctx.redis)
    # Sheets of shots that no longer exist (fewer shots after a re-ingest).
    for key in set(target.old_sheets) - set(sheets.values()):
        ctx.storage.delete_derived(key)
