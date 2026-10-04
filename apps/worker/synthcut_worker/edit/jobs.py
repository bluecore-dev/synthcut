"""Tez montaj (Phase 6 without a model): every ready video of the project,
its transcript, its shot analysis, a colour measurement of its proxy and a
voice measurement → the rule-based editor → a validated, versioned EditPlan
→ the final render is queued.

The Director stage is marked skipped — honestly: no agent decided this cut.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from synthcut_audio.measure import measure_voice
from synthcut_audio.plan import auto_mix
from synthcut_color.auto import input_transform_for, matched_grades, measure, sample_rgb
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import (
    Asset,
    AssetTranscript,
    ClipAnalysisRow,
    EditPlanRow,
    MediaFile,
    Project,
)
from synthcut_core.renders import next_version_stmt, request_render
from synthcut_core.stages import StageState, set_stage
from synthcut_media import MediaError
from synthcut_schemas.analysis import ClipAnalysis
from synthcut_schemas.enums import (
    PRESET_SPECS,
    AssetStatus,
    EventLevel,
    JobQueue,
    PlanSource,
    ProjectPreset,
    Stage,
    StageStatus,
    TranscriptStatus,
)
from synthcut_schemas.events import EventType
from synthcut_schemas.grade import AudioMeasure, ColorGrade, MixPlan
from synthcut_schemas.jobs import AutoEditPayload, JobKind
from synthcut_schemas.speech import Transcript
from synthcut_speech.audio import load_pcm
from synthcut_speech.vad import speech_spans
from synthcut_timeline import AssetFacts, CaptionTrack, EditPlan, validate_plan
from synthcut_timeline.autoedit import Options, Source, build_plan

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..registry import handler

INTERNAL_URL_TTL = 6 * 3600
SOURCE = "worker"
DENOISE_WORDS = {"off": "o'chiq", "light": "yengil", "medium": "o'rta", "strong": "kuchli"}


@dataclass
class Material:
    asset_id: uuid.UUID
    name: str
    duration: float
    width: int
    height: int
    has_audio: bool
    color_profile: str | None
    proxy_key: str
    speech_key: str | None
    lufs: float | None
    true_peak: float | None
    transcript: Transcript | None
    clips: list[ClipAnalysis] = field(default_factory=list)


@dataclass
class Brief:
    project_id: uuid.UUID
    preset: str
    width: int
    height: int
    fps: int
    target_duration: float | None
    language: str | None
    material: list[Material]


def _stage(s, project_id: uuid.UUID, stage: Stage, status: StageStatus, detail: str | None, progress=None):
    set_stage(s, project_id, stage, StageState(status, progress, detail), source=SOURCE)


def _gather(ctx: JobContext, payload: AutoEditPayload) -> Brief:
    with ctx.session() as s:
        project = s.get(Project, ctx.job.project_id)
        if project is None:
            raise PermanentError("project_missing")
        preset = payload.preset or project.preset
        spec = PRESET_SPECS[ProjectPreset(preset)]
        assets = list(
            s.scalars(
                select(Asset)
                .where(
                    Asset.project_id == project.id,
                    Asset.deleted_at.is_(None),
                    Asset.kind == "video",
                    Asset.status == AssetStatus.READY.value,
                )
                .order_by(Asset.sort_index, Asset.created_at)
            )
        )
        if not assets:
            raise PermanentError("Loyihada tayyor video yo'q")
        ids = [a.id for a in assets]
        files = {
            (m.asset_id, m.kind): m for m in s.scalars(select(MediaFile).where(MediaFile.asset_id.in_(ids)))
        }
        transcripts = {
            t.asset_id: Transcript.model_validate(t.data)
            for t in s.scalars(select(AssetTranscript).where(AssetTranscript.asset_id.in_(ids)))
            if t.status == TranscriptStatus.DONE.value and t.data
        }
        clips: dict[uuid.UUID, list[ClipAnalysis]] = {}
        for row in s.scalars(
            select(ClipAnalysisRow)
            .where(ClipAnalysisRow.asset_id.in_(ids))
            .order_by(ClipAnalysisRow.shot_index)
        ):
            clips.setdefault(row.asset_id, []).append(ClipAnalysis.model_validate(row.data))
        material: list[Material] = []
        for a in assets:
            proxy = files.get((a.id, "proxy_720p"))
            if proxy is None or not a.width or not a.height or not a.duration_sec:
                continue
            speech = files.get((a.id, "audio_speech"))
            loudness = (a.media_info or {}).get("loudness") or {}
            material.append(
                Material(
                    asset_id=a.id,
                    name=a.original_filename,
                    duration=float(a.duration_sec),
                    width=a.width,
                    height=a.height,
                    has_audio=bool(a.has_audio),
                    color_profile=a.color_profile,
                    proxy_key=proxy.storage_key,
                    speech_key=speech.storage_key if speech else None,
                    lufs=loudness.get("integrated_lufs"),
                    true_peak=loudness.get("true_peak_dbfs"),
                    transcript=transcripts.get(a.id),
                    clips=clips.get(a.id, []),
                )
            )
        if not material:
            raise PermanentError("Videolarning proxy fayli yo'q")
        target = payload.target_duration or (
            float(project.target_duration_sec) if project.target_duration_sec else None
        )
        _stage(
            s,
            project.id,
            Stage.DIRECTOR,
            StageStatus.SKIPPED,
            "Tez montaj — qoidalar asosida, AI rejissor ulanmagan",
        )
        _stage(s, project.id, Stage.EDITOR, StageStatus.RUNNING, "Material o'lchanmoqda", 0.0)
        commit_and_publish_sync(s, ctx.redis)
        return Brief(
            project_id=project.id,
            preset=preset,
            width=spec.width,
            height=spec.height,
            fps=project.fps,
            target_duration=target,
            language=project.language if project.language not in ("auto", None) else None,
            material=material,
        )


def _grades(ctx: JobContext, brief: Brief, payload: AutoEditPayload) -> list[ColorGrade]:
    measures, transforms = [], []
    for n, m in enumerate(brief.material):
        ctx.progress(0.05 + 0.5 * n / len(brief.material), "rang o'lchovi")
        transform = input_transform_for(m.color_profile, from_proxy=True)
        url = ctx.storage.internal_get_url(m.proxy_key, INTERNAL_URL_TTL)
        frames = sample_rgb(url, ctx.scratch_dir, duration=m.duration, max_frames=24, check=ctx.check)
        measures.append(measure(frames, transform))
        transforms.append(transform)
        del frames
    return matched_grades(
        measures, transform=transforms, profile=payload.profile, intensity=payload.intensity
    )


def _voice(ctx: JobContext, brief: Brief) -> tuple[AudioMeasure | None, Material | None]:
    """Measure the voice where there is the most speech: one person, one mic
    is the common case, and one chain must suit the whole timeline."""
    speaking = [m for m in brief.material if m.has_audio and m.speech_key]
    if not speaking:
        return None, None
    best = max(speaking, key=lambda m: (m.transcript.speech_seconds if m.transcript else 0.0, m.duration))
    ctx.progress(0.6, "ovoz o'lchovi")
    flac = ctx.scratch_dir / "speech.flac"
    ctx.storage.download_file(best.speech_key, flac)
    pcm = load_pcm(flac, ctx.scratch_dir, check=ctx.check)
    voice = measure_voice(pcm, speech_spans(pcm), integrated_lufs=best.lufs, true_peak_db=best.true_peak)
    del pcm
    return voice, best


def _plan(
    ctx: JobContext, brief: Brief, payload: AutoEditPayload, *, version: int
) -> tuple[EditPlan, MixPlan | None]:
    grades = _grades(ctx, brief, payload)
    voice, _ = _voice(ctx, brief)
    mix = (
        auto_mix(
            voice, target=payload.loudness, denoise=None if payload.denoise == "auto" else payload.denoise
        )
        if voice is not None
        else None
    )
    has_words = any(m.transcript and m.transcript.words for m in brief.material)
    captions = None
    if payload.captions != "off" and has_words:
        captions = CaptionTrack(
            style=payload.captions,
            position=payload.caption_position,
            max_words_per_line=3 if brief.height > brief.width else 4,
            language=brief.language,
        )
    ctx.progress(0.8, "montaj")
    sources = [
        Source(
            asset_id=m.asset_id,
            name=m.name,
            duration=m.duration,
            width=m.width,
            height=m.height,
            transcript=m.transcript,
            clips=m.clips,
            grade=g,
            has_audio=m.has_audio,
        )
        for m, g in zip(brief.material, grades, strict=True)
    ]
    opts = Options(
        width=brief.width,
        height=brief.height,
        fps=brief.fps,
        target_duration=brief.target_duration,
        remove_pauses=payload.remove_pauses,
        captions=captions,
        title=payload.title,
        cta=payload.cta,
    )
    try:
        plan = build_plan(
            project_id=brief.project_id,
            version=version,
            sources=sources,
            opts=opts,
            mix=mix,
            noise_floor_db=voice.noise_floor_db if voice else None,
        )
    except ValueError as exc:
        raise PermanentError(str(exc)) from exc
    facts = {
        m.asset_id: AssetFacts(kind="video", duration=m.duration, has_audio=m.has_audio)
        for m in brief.material
    }
    report = validate_plan(plan, assets=facts)  # plans are executed only after validation (spec rule 6)
    if not report.ok:
        raise PermanentError(
            "Reja tekshiruvdan o'tmadi: " + ", ".join(sorted({i.code for i in report.errors}))
        )
    return plan, mix


def _summaries(plan: EditPlan, mix: MixPlan | None, payload: AutoEditPayload) -> dict[Stage, StageState]:
    clips = plan.video_tracks[0].clips
    grades = [ColorGrade.model_validate(e.params) for c in clips for e in c.effects if e.type == "grade"]
    exposure = statistics.median([g.exposure for g in grades]) if grades else 0.0
    done = StageStatus.DONE
    out = {
        Stage.EDITOR: StageState(
            done, 1.0, f"v{plan.version} · {len(clips)} bo'lak · {plan.sequence.duration:.1f} s"
        ),
        Stage.COLOR: StageState(done, 1.0, f"{payload.profile} · {exposure:+.1f} EV"),
        Stage.AUDIO: (
            StageState(
                done,
                1.0,
                f"{mix.loudness.target_lufs:g} LUFS · shovqin tozalash: {DENOISE_WORDS[mix.voice.denoise]}",
            )
            if mix
            else StageState(StageStatus.SKIPPED, None, "Ovozli video yo'q")
        ),
        Stage.CAPTIONS: (
            StageState(done, 1.0, f"{plan.captions.style} · {plan.captions.position}")
            if plan.captions
            else StageState(
                StageStatus.SKIPPED, None, "O'chirilgan" if payload.captions == "off" else "Nutq yo'q"
            )
        ),
        Stage.MOTION: (
            StageState(done, 1.0, ", ".join(g.component for g in plan.graphics))
            if plan.graphics
            else StageState(StageStatus.SKIPPED, None, "Grafika so'ralmagan")
        ),
    }
    return out


def _save(
    ctx: JobContext, brief: Brief, plan: EditPlan, mix: MixPlan | None, payload: AutoEditPayload
) -> dict:
    with ctx.session() as s:
        row = EditPlanRow(
            project_id=brief.project_id,
            version=plan.version,
            source=PlanSource.RULES.value,
            plan=plan.model_dump(mode="json"),
            duration_sec=plan.sequence.duration,
            clip_count=len(plan.video_tracks[0].clips),
            notes=plan.notes,
            options={**payload.model_dump(mode="json"), "preset": brief.preset},
        )
        s.add(row)
        s.flush()
        for stage, state in _summaries(plan, mix, payload).items():
            set_stage(s, brief.project_id, stage, state, source=SOURCE)
        emit(
            s,
            project_id=brief.project_id,
            type=EventType.PLAN_READY,
            message=f"Tez montaj v{plan.version}: {row.clip_count} bo'lak, {plan.sequence.duration:.1f} s",
            source=SOURCE,
            data={"version": plan.version, "plan_id": str(row.id)},
            job_id=ctx.job.id,
        )
        render_id = None
        if payload.render:
            render, _ = request_render(s, row, preset=brief.preset, deliver=payload.deliver, force=True)
            render_id = str(render.id)
            set_stage(
                s,
                brief.project_id,
                Stage.RENDER,
                StageState(StageStatus.QUEUED, None, "Navbatda"),
                source=SOURCE,
            )
            for stage in (Stage.QA, Stage.DELIVERY):
                set_stage(
                    s, brief.project_id, stage, StageState(StageStatus.PENDING, None, None), source=SOURCE
                )
        commit_and_publish_sync(s, ctx.redis)
        return {"version": plan.version, "plan_id": str(row.id), "render_id": render_id}


def _fail(ctx: JobContext, message: str) -> None:
    if ctx.job.project_id is None:
        return
    with ctx.session() as s:
        _stage(s, ctx.job.project_id, Stage.EDITOR, StageStatus.FAILED, message[:200])
        emit(
            s,
            project_id=ctx.job.project_id,
            type=EventType.PLAN_FAILED,
            level=EventLevel.ERROR,
            message=f"Tez montaj bajarilmadi — {message[:200]}",
            source=SOURCE,
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)


@handler(JobKind.EDIT_AUTO, queue=JobQueue.CPU)
def auto_edit(ctx: JobContext, payload: AutoEditPayload) -> dict[str, Any]:
    try:
        brief = _gather(ctx, payload)
        plan, mix = _plan(ctx, brief, payload, version=1)
        for attempt in range(3):  # a plan saved meanwhile (another tab) takes the number
            with ctx.session() as s:
                version = int(s.execute(next_version_stmt(brief.project_id)).scalar_one())
            plan = plan.model_copy(update={"version": version})
            try:
                return _save(ctx, brief, plan, mix, payload)
            except IntegrityError:
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")
    except (LeaseLost, JobInterrupted, JobCancelled):
        raise
    except PermanentError as exc:
        _fail(ctx, str(exc))
        raise
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, str(exc))
            raise PermanentError(str(exc)) from exc
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        if ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, f"{type(exc).__name__}: {exc}")
        raise
