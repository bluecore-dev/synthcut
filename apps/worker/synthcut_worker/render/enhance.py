"""Colour and sound enhancement preview (Phase 8): what the Color and Audio
agents will decide, made automatically from measurements and applied to one
clip — the engines end to end before the agents exist.

Proxy → sampled frames → ``measure`` → ``auto_grade`` → baked 3D LUT;
speech track → VAD → ``measure_voice`` → ``auto_mix`` → voice chain + two-pass
loudness; one FFmpeg pass renders both. Before / after stills come from the
same frame of the proxy and of the result.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from synthcut_audio.filters import loudnorm_apply, loudnorm_measure, parse_loudnorm, voice_filters
from synthcut_audio.measure import measure_voice
from synthcut_audio.plan import auto_mix
from synthcut_color.auto import auto_grade, input_transform_for, measure, sample_rgb
from synthcut_color.grade import bake, write_cube
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Asset, MediaFile, utcnow
from synthcut_media import MediaError, run_ffmpeg
from synthcut_schemas.enums import EventLevel, JobQueue
from synthcut_schemas.events import EventType
from synthcut_schemas.grade import ColorGrade, MixPlan
from synthcut_schemas.jobs import EnhancePreviewPayload, JobKind
from synthcut_speech.audio import load_pcm
from synthcut_speech.vad import speech_spans
from synthcut_storage import Area, derived_key

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..derived import upsert_media_file
from ..registry import handler

INTERNAL_URL_TTL = 6 * 3600


@dataclass(frozen=True, slots=True)
class Target:
    asset_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    proxy_key: str
    speech_key: str | None
    duration: float
    color_profile: str | None
    has_audio: bool
    lufs: float | None
    true_peak: float | None


@dataclass
class Result:
    video: Path
    before: Path
    after: Path
    grade: ColorGrade
    mix: MixPlan | None
    lufs_after: float | None


def _start(ctx: JobContext, payload: EnhancePreviewPayload) -> Target:
    with ctx.session() as s:
        asset = s.get(Asset, payload.asset_id)
        if asset is None or asset.deleted_at is not None:
            raise PermanentError("asset_missing")
        if asset.project_id != ctx.job.project_id:
            raise PermanentError("asset belongs to another project")  # worker sandbox (spec §39)
        files = {m.kind: m for m in s.scalars(select(MediaFile).where(MediaFile.asset_id == asset.id))}
        proxy = files.get("proxy_720p")
        if asset.kind != "video" or proxy is None:
            raise PermanentError("Faylda proxy video yo'q")
        loudness = (asset.media_info or {}).get("loudness") or {}
        return Target(
            asset_id=asset.id,
            project_id=asset.project_id,
            name=asset.original_filename,
            proxy_key=proxy.storage_key,
            speech_key=files["audio_speech"].storage_key if "audio_speech" in files else None,
            duration=float(asset.duration_sec or proxy.duration_sec or 0),
            color_profile=asset.color_profile,
            has_audio=bool(asset.has_audio),
            lufs=loudness.get("integrated_lufs"),
            true_peak=loudness.get("true_peak_dbfs"),
        )


def _still(source: str | Path, at: float, out: Path, ctx: JobContext) -> Path:
    run_ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "3", str(out)],
        check=ctx.check,
        timeout=120,
    )  # fmt: skip
    return out


def _integrated_lufs(path: Path, ctx: JobContext) -> float | None:
    log = run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            "ebur128",
            "-f",
            "null",
            "-",
        ],
        check=ctx.check,
        timeout=600,
    )
    try:
        return round(float(log.rsplit("I:", 1)[1].split("LUFS")[0]), 1)
    except (IndexError, ValueError):
        return None


def _render(ctx: JobContext, target: Target, payload: EnhancePreviewPayload) -> Result:
    tag = {"asset_id": str(target.asset_id)}
    work = ctx.scratch_dir
    proxy = ctx.storage.internal_get_url(target.proxy_key, INTERNAL_URL_TTL)

    ctx.progress(0.02, "rang o'lchovi", data=tag)
    transform = input_transform_for(target.color_profile, from_proxy=True)
    frames = sample_rgb(proxy, work, duration=target.duration, check=ctx.check)
    grade = auto_grade(
        measure(frames, transform), transform=transform, profile=payload.profile, intensity=payload.intensity
    )
    cube = write_cube(bake(grade), work / "grade.cube")
    ctx.check()

    audio_filters: list[str] = []
    mix: MixPlan | None = None
    if target.has_audio and target.speech_key:
        ctx.progress(0.08, "ovoz o'lchovi", data=tag)
        flac = work / "speech.flac"
        ctx.storage.download_file(target.speech_key, flac)
        pcm = load_pcm(flac, work, check=ctx.check)
        voice = measure_voice(
            pcm, speech_spans(pcm), integrated_lufs=target.lufs, true_peak_db=target.true_peak
        )
        del pcm
        mix = auto_mix(
            voice, target=payload.target, denoise=None if payload.denoise == "auto" else payload.denoise
        )
        chain = voice_filters(mix, noise_floor_db=voice.noise_floor_db)
        ctx.progress(0.12, "balandlik o'lchovi", data=tag)
        first = run_ffmpeg(
            ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", proxy, "-vn",
             "-af", ",".join([*chain, loudnorm_measure(mix)]), "-f", "null", "-"],
            check=ctx.check,
            timeout=600 + target.duration * 2,
        )  # fmt: skip
        audio_filters = [*chain, loudnorm_apply(mix, parse_loudnorm(first))]

    ctx.progress(0.2, "render", data=tag)
    out = work / "enhanced.mp4"
    audio = (
        ["-af", ",".join(audio_filters), "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
        if audio_filters
        else ["-c:a", "copy"]
    )
    run_ffmpeg(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-threads", str(ctx.settings.media_threads),
         "-filter_threads", str(ctx.settings.media_threads), "-i", proxy,
         "-vf", f"format=gbrp,lut3d=file={cube}:interp=tetrahedral,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         *audio, "-map", "0:v:0", "-map", "0:a:0?", "-movflags", "+faststart",
         "-progress", "pipe:1", "-nostats", str(out)],
        duration=target.duration,
        on_progress=lambda f: ctx.progress(0.2 + 0.72 * f, "render", data=tag),
        check=ctx.check,
        timeout=900 + target.duration * 20,
    )  # fmt: skip

    ctx.progress(0.94, "taqqoslash", data=tag)
    at = round(min(max(target.duration * 0.3, 0.0), max(target.duration - 0.1, 0.0)), 2)
    before = _still(proxy, at, work / "before.jpg", ctx)
    after = _still(out, at, work / "after.jpg", ctx)
    lufs_after = _integrated_lufs(out, ctx) if audio_filters else None
    return Result(out, before, after, grade, mix, lufs_after)


def _fail(ctx: JobContext, target: Target | None, payload: EnhancePreviewPayload, message: str) -> None:
    if ctx.job.project_id is None:
        return
    with ctx.session() as s:
        emit(
            s,
            project_id=ctx.job.project_id,
            type=EventType.PREVIEW_FAILED,
            level=EventLevel.ERROR,
            message=f"{target.name if target else payload.asset_id}: rang va ovoz yaxshilanmadi — {message[:200]}",
            source="worker",
            data={"asset_id": str(payload.asset_id)},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)


def _summary(result: Result, target: Target) -> str:
    g = result.grade
    parts: list[str] = []
    if g.exposure:
        parts.append(f"{g.exposure:+.1f} EV")
    if g.temperature:
        parts.append("iliqroq" if g.temperature > 0 else "sovuqroq")
    parts.append(g.creative_profile)
    if result.mix is not None and target.lufs is not None and result.lufs_after is not None:
        parts.append(f"{target.lufs:.0f} → {result.lufs_after:.0f} LUFS")
    return ", ".join(parts)


@handler(JobKind.RENDER_ENHANCE_PREVIEW, queue=JobQueue.RENDER)
def enhance_preview(ctx: JobContext, payload: EnhancePreviewPayload) -> dict[str, Any]:
    target: Target | None = None
    try:
        target = _start(ctx, payload)
        result = _render(ctx, target, payload)
    except (LeaseLost, JobInterrupted, JobCancelled):
        raise
    except PermanentError as exc:
        _fail(ctx, target, payload, str(exc))
        raise
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, target, payload, str(exc))
            raise PermanentError(str(exc)) from exc
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        if ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, target, payload, f"{type(exc).__name__}: {exc}")
        raise

    ctx.progress(0.98, "saqlash", data={"asset_id": str(target.asset_id)})
    keys = {
        "enhance_preview": (
            derived_key(target.project_id, Area.PREVIEWS, target.asset_id, "enhanced.mp4"),
            result.video,
            "video/mp4",
        ),
        "enhance_before": (
            derived_key(target.project_id, Area.PREVIEWS, target.asset_id, "enhance_before.jpg"),
            result.before,
            "image/jpeg",
        ),
        "enhance_after": (
            derived_key(target.project_id, Area.PREVIEWS, target.asset_id, "enhance_after.jpg"),
            result.after,
            "image/jpeg",
        ),
    }
    for key, path, content_type in keys.values():
        ctx.storage.put_derived_file(key, path, content_type)
    decisions = {
        "grade": result.grade.model_dump(mode="json"),
        "mix": result.mix.model_dump(mode="json") if result.mix else None,
    }
    ctx.storage.put_derived_bytes(
        derived_key(target.project_id, Area.ANALYSIS, target.asset_id, "enhance.json"),
        json.dumps(decisions).encode(),
        "application/json",
    )
    meta = {
        "profile": payload.profile,
        "intensity": payload.intensity,
        "target": payload.target,
        "denoise": payload.denoise,
        "notes": result.grade.notes + (result.mix.notes if result.mix else []),
        "lufs_before": target.lufs,
        "lufs_after": result.lufs_after,
        **decisions,
    }
    now = utcnow()
    with ctx.session() as s:
        if s.get(Asset, target.asset_id) is None:
            return {"skipped": "asset_deleted"}
        for kind, (key, path, content_type) in keys.items():
            upsert_media_file(
                s,
                asset_id=target.asset_id,
                project_id=target.project_id,
                kind=kind,
                storage_key=key,
                content_type=content_type,
                size_bytes=path.stat().st_size,
                now=now,
                duration_sec=target.duration if kind == "enhance_preview" else None,
                meta=meta if kind == "enhance_preview" else {},
            )
        emit(
            s,
            project_id=target.project_id,
            type=EventType.PREVIEW_READY,
            message=f"{target.name}: rang va ovoz yaxshilandi — {_summary(result, target)}",
            source="worker",
            data={"asset_id": str(target.asset_id), "kind": "enhance"},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)
    return {"profile": payload.profile, "exposure": result.grade.exposure, "lufs_after": result.lufs_after}
