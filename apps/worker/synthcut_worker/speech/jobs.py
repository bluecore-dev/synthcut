"""Transcription (spec §13, Phase 4): the 16 kHz speech track that ingestion
made → ``Transcript`` (words with timings, segments, silences, subtitle cues),
stored in ``transcripts`` and as ``transcript.json`` / ``subtitles.vtt`` /
``subtitles.srt`` derived files.

The engine is whatever ``SPEECH_ROUTE`` names; on this host that is Whisper
on two CPU cores, slower than real time — the job reports progress per
segment and can be cancelled between them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Asset, AssetTranscript, MediaFile, Project, utcnow
from synthcut_core.stages import refresh_transcription_stage
from synthcut_media import MediaError
from synthcut_schemas.enums import EventLevel, JobQueue, StageStatus, TranscriptStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import JobKind, TranscribeAssetPayload
from synthcut_schemas.speech import Transcript
from synthcut_speech.audio import SAMPLE_RATE, detect_silences, load_pcm
from synthcut_speech.cues import to_srt, to_webvtt
from synthcut_speech.engines import EngineUnavailable, engine_for
from synthcut_speech.transcript import build_transcript
from synthcut_storage import Area, derived_key

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..delivery.owner import notify_owner
from ..derived import upsert_media_file
from ..registry import handler

LAYOUT: dict[str, tuple[str, str]] = {  # kind -> (file name, content type)
    "transcript": ("transcript.json", "application/json"),
    "subtitles_vtt": ("subtitles.vtt", "text/vtt; charset=utf-8"),
    "subtitles_srt": ("subtitles.srt", "application/x-subrip; charset=utf-8"),
}


@dataclass(frozen=True, slots=True)
class Outcome:
    transcript: Transcript
    files: dict[str, tuple[str, int]]  # kind -> (key, size)
    engine_seconds: float


@dataclass(frozen=True, slots=True)
class Target:
    asset_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    speech_key: str
    lufs: float | None
    language: str  # "auto" or a code


def _lufs(media_info: dict[str, Any] | None) -> float | None:
    loudness = (media_info or {}).get("loudness") or {}
    value = loudness.get("integrated_lufs")
    return float(value) if value is not None else None


def _start(ctx: JobContext, payload: TranscribeAssetPayload) -> tuple[Target | None, str | None]:
    with ctx.session() as s:
        asset = s.get(Asset, payload.asset_id)
        if asset is None or asset.deleted_at is not None:
            return None, "asset_missing"
        if asset.project_id != ctx.job.project_id:
            raise PermanentError("asset belongs to another project")  # worker sandbox (spec §39)
        row = s.execute(
            select(AssetTranscript).where(AssetTranscript.asset_id == asset.id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            row = AssetTranscript(asset_id=asset.id, project_id=asset.project_id, runs=1)
            s.add(row)
        elif row.status == TranscriptStatus.DONE.value and not payload.force:
            return None, "already_done"
        speech_key = s.execute(
            select(MediaFile.storage_key).where(
                MediaFile.asset_id == asset.id, MediaFile.kind == "audio_speech"
            )
        ).scalar_one_or_none()
        if speech_key is None:
            row.status = TranscriptStatus.FAILED.value
            row.error = "Faylda nutq audiosi yo'q"
            refresh_transcription_stage(s, asset.project_id, source="worker")
            commit_and_publish_sync(s, ctx.redis)
            return None, "no_speech_track"
        language = payload.language or s.get(Project, asset.project_id).language or "auto"
        row.status = TranscriptStatus.RUNNING.value
        row.requested_language = language
        row.error = None
        row.started_at = utcnow()
        refresh_transcription_stage(s, asset.project_id, source="worker")
        target = Target(
            asset.id, asset.project_id, asset.original_filename, speech_key, _lufs(asset.media_info), language
        )
        commit_and_publish_sync(s, ctx.redis)
    return target, None


def _set_status(ctx: JobContext, target: Target, status: TranscriptStatus, error: str | None) -> None:
    with ctx.session() as s:
        row = s.execute(
            select(AssetTranscript).where(AssetTranscript.asset_id == target.asset_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return
        row.status = status.value
        row.error = error[:500] if error else None
        if status is TranscriptStatus.FAILED:
            row.finished_at = utcnow()
            emit(
                s,
                project_id=target.project_id,
                type=EventType.TRANSCRIPT_FAILED,
                level=EventLevel.ERROR,
                message=f"{target.name}: nutq matnga o'girilmadi — {(error or '')[:200]}",
                source="worker",
                data={"asset_id": str(target.asset_id)},
                job_id=ctx.job.id,
            )
        refresh_transcription_stage(s, target.project_id, source="worker")
        commit_and_publish_sync(s, ctx.redis)


@handler(JobKind.TRANSCRIBE_ASSET, queue=JobQueue.CPU)
def transcribe_asset(ctx: JobContext, payload: TranscribeAssetPayload) -> dict[str, Any]:
    target, skipped = _start(ctx, payload)
    if target is None:
        return {"skipped": skipped}
    try:
        outcome = _transcribe(ctx, target)
    except LeaseLost:
        raise
    except JobInterrupted:
        _set_status(ctx, target, TranscriptStatus.QUEUED, None)  # handed back, runs again
        raise
    except JobCancelled:
        _set_status(ctx, target, TranscriptStatus.FAILED, "bekor qilindi")
        raise
    except EngineUnavailable as exc:
        _set_status(ctx, target, TranscriptStatus.FAILED, f"Nutq dvigateli tayyor emas: {exc}")
        raise PermanentError(str(exc)) from exc
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _set_status(ctx, target, TranscriptStatus.FAILED, str(exc))
            raise PermanentError(str(exc)) from exc
        _set_status(ctx, target, TranscriptStatus.QUEUED, f"qayta urinish: {exc}")
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        last = ctx.job.attempts >= ctx.job.max_attempts
        status = TranscriptStatus.FAILED if last else TranscriptStatus.QUEUED
        _set_status(ctx, target, status, f"{type(exc).__name__}: {exc}")
        raise
    _finish(ctx, target, outcome)
    transcript = outcome.transcript
    return {
        "engine": transcript.engine,
        "language": transcript.language,
        "words": transcript.word_count,
        "segments": len(transcript.segments),
        "silences": len(transcript.silences),
    }


def _transcribe(ctx: JobContext, target: Target) -> Outcome:
    settings = ctx.settings
    tag = {"asset_id": str(target.asset_id)}
    work = ctx.scratch_dir
    flac = work / "speech.flac"
    ctx.progress(0.01, "audio", data=tag)
    ctx.storage.download_file(target.speech_key, flac)
    ctx.check()
    pcm = load_pcm(flac, work, check=ctx.check)
    duration = len(pcm) / SAMPLE_RATE
    if duration <= 0:
        raise MediaError("Nutq audiosi bo'sh", permanent=True)
    ctx.progress(0.03, "pauzalar", data=tag)
    silences = detect_silences(flac, duration, integrated_lufs=target.lufs, check=ctx.check)

    engine = engine_for(
        settings.speech_route,
        models_dir=Path(settings.speech_models_dir),
        threads=settings.speech_threads,
        beam_size=settings.speech_beam_size,
        preferred_language=settings.speech_preferred_language or None,
    )
    forced = target.language != "auto"
    ctx.progress(0.05, "whisper", data=tag)
    result = engine.transcribe(
        pcm,
        language=target.language if forced else None,
        on_progress=lambda f: ctx.progress(0.05 + 0.93 * f, "whisper", data=tag),
        check=ctx.check,
    )
    del pcm
    transcript = build_transcript(
        result, route=engine.route, duration=duration, language_forced=forced, silences=silences
    )

    ctx.progress(0.99, "saqlash", data=tag)
    bodies = {
        "transcript": transcript.model_dump_json().encode(),
        "subtitles_vtt": to_webvtt(transcript.cues).encode(),
        "subtitles_srt": to_srt(transcript.cues).encode(),
    }
    files: dict[str, tuple[str, int]] = {}
    for kind, body in bodies.items():
        name, content_type = LAYOUT[kind]
        key = derived_key(target.project_id, Area.ANALYSIS, target.asset_id, name)
        ctx.storage.put_derived_bytes(key, body, content_type)
        files[kind] = (key, len(body))
        ctx.check()
    return Outcome(transcript, files, result.seconds)


def _finish(ctx: JobContext, target: Target, outcome: Outcome) -> None:
    transcript = outcome.transcript
    now = utcnow()
    with ctx.session() as s:
        row = s.execute(
            select(AssetTranscript).where(AssetTranscript.asset_id == target.asset_id).with_for_update()
        ).scalar_one_or_none()
        if row is None or s.get(Asset, target.asset_id) is None:
            return  # the asset was deleted meanwhile
        for kind, (key, size) in outcome.files.items():
            upsert_media_file(
                s,
                asset_id=target.asset_id,
                project_id=target.project_id,
                kind=kind,
                storage_key=key,
                content_type=LAYOUT[kind][1],
                size_bytes=size,
                now=now,
                duration_sec=transcript.duration,
                meta={"cues": len(transcript.cues)} if kind != "transcript" else {},
            )
        row.status = TranscriptStatus.DONE.value
        row.engine = transcript.engine
        row.language = transcript.language
        row.language_probability = transcript.language_probability
        row.duration_sec = transcript.duration
        row.speech_sec = transcript.speech_seconds
        row.word_count = transcript.word_count
        row.segment_count = len(transcript.segments)
        row.engine_seconds = round(outcome.engine_seconds, 1)
        row.data = transcript.model_dump(mode="json")
        row.error = None
        row.finished_at = now
        language = (transcript.language or "?").upper()
        emit(
            s,
            project_id=target.project_id,
            type=EventType.TRANSCRIPT_READY,
            message=(
                f"{target.name}: nutq matnga o'girildi — {language} · {transcript.word_count} so'z · "
                f"{len(transcript.silences)} pauza"
            ),
            source="worker",
            data={"asset_id": str(target.asset_id), "language": transcript.language},
            job_id=ctx.job.id,
        )
        state, changed = refresh_transcription_stage(s, target.project_id, source="worker")
        if changed and state.status is StageStatus.DONE and ctx.settings.notify_telegram:
            done = s.execute(
                select(func.count()).where(
                    AssetTranscript.project_id == target.project_id,
                    AssetTranscript.status == TranscriptStatus.DONE.value,
                )
            ).scalar_one()
            detail = state.detail or ""
            notify_owner(
                s,
                target.project_id,
                text=lambda name: (
                    f"📝 <b>{name}</b>\nNutq matnga o'girildi: {escape(detail)}.\n"
                    "Transkript va subtitrlar tayyor."
                ),
                idempotency_key=f"notify.transcripts_done:{target.project_id}:{done}:{row.runs}",
            )
        commit_and_publish_sync(s, ctx.redis)
