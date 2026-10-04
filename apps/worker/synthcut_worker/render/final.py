"""Final render (Phase 11) and its quality control (Phase 9): a validated
EditPlan executed from the originals.

segments (seek, colour → Rec.709, placement, grade LUT, exact frames) →
motion layer (Remotion PNG frames) → loudness measured over the joined
timeline → master (overlay, voice chain, SFX, loudnorm, preset encode) →
QA on the actual file → poster, a chat-sized copy if the file is over the
bot upload limit → storage → the owner's chat (Phase 12, its own job).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from synthcut_audio.filters import loudnorm_apply, loudnorm_measure, parse_loudnorm, voice_filters
from synthcut_color.grade import bake, is_identity, write_cube
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Asset, AssetTranscript, EditPlanRow, Render, utcnow
from synthcut_core.renders import request_delivery
from synthcut_core.stages import StageState, set_stage
from synthcut_media import MediaError, has_filter, normalize, run_ffmpeg, run_ffprobe
from synthcut_media.final import (
    TELEGRAM_LIMIT,
    OverlayLayer,
    SegmentSpec,
    SfxInput,
    concat_list,
    loudness_pass,
    master_command,
    overlay_fps,
    overlay_size,
    poster_command,
    segment_command,
    telegram_copy_command,
)
from synthcut_media.qa import Expected, judge, parse_qa_log, qa_command
from synthcut_schemas.enums import EventLevel, JobQueue, RenderStatus, Stage, StageStatus, TranscriptStatus
from synthcut_schemas.events import EventType
from synthcut_schemas.grade import ColorGrade, MixPlan
from synthcut_schemas.jobs import JobKind, RenderFinalPayload
from synthcut_schemas.qa import QaReport
from synthcut_schemas.speech import Transcript
from synthcut_storage import Area, derived_key
from synthcut_timeline import AssetFacts, EditPlan, load_plan, validate_plan
from synthcut_timeline.overlay import build_overlay, sfx_cues

from ..context import JobCancelled, JobContext, JobInterrupted, LeaseLost, PermanentError, RetryableError
from ..registry import handler
from .remotion import RemotionUnavailable, render_overlay

INTERNAL_URL_TTL = 12 * 3600
SOURCE = "worker"
QA_WORDS = {"pass": "QA: hammasi joyida", "warn": "QA: ogohlantirish bor", "fail": "QA: xato topildi"}


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    width: int
    height: int
    has_audio: bool
    color_profile: str | None
    bit_depth: int | None


@dataclass
class Work:
    render_id: uuid.UUID
    project_id: uuid.UUID
    preset: str
    plan: EditPlan
    sources: dict[uuid.UUID, Source]
    transcripts: dict[uuid.UUID, Transcript]


@dataclass
class Output:
    final: Path
    poster: Path
    telegram: Path | None
    qa: QaReport


def _set_row(ctx: JobContext, render_id: uuid.UUID, **fields: Any) -> None:
    with ctx.session() as s:
        row = s.get(Render, render_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


def _start(ctx: JobContext, payload: RenderFinalPayload) -> Work | None:
    with ctx.session() as s:
        row = s.get(Render, payload.render_id, with_for_update=True)
        if row is None:
            raise PermanentError("render_missing")
        if row.project_id != ctx.job.project_id:
            raise PermanentError("render belongs to another project")  # worker sandbox (spec §39)
        if row.status == RenderStatus.DONE.value:
            return None
        plan_row = s.get(EditPlanRow, row.plan_id)
        if plan_row is None:
            raise PermanentError("plan_missing")
        plan = load_plan(plan_row.plan)
        ids = {c.asset_id for t in plan.video_tracks for c in t.clips}
        assets = {
            a.id: a for a in s.scalars(select(Asset).where(Asset.id.in_(ids), Asset.deleted_at.is_(None)))
        }
        facts = {
            a.id: AssetFacts(kind=a.kind, duration=a.duration_sec, has_audio=bool(a.has_audio))
            for a in assets.values()
        }
        report = validate_plan(plan, assets=facts)  # the material may have changed since the plan was made
        if not report.ok:
            codes = ", ".join(sorted({i.code for i in report.errors}))
            raise PermanentError(f"Reja endi bajarib bo'lmaydi ({codes}) — fayl o'chirilgan bo'lishi mumkin")
        unsupported = _unsupported(plan)
        if unsupported:
            raise PermanentError(unsupported)
        transcripts = {
            t.asset_id: Transcript.model_validate(t.data)
            for t in s.scalars(select(AssetTranscript).where(AssetTranscript.asset_id.in_(ids)))
            if t.status == TranscriptStatus.DONE.value and t.data
        }
        row.status = RenderStatus.RUNNING.value
        row.started_at = utcnow()
        row.finished_at = None
        row.step = "tayyorlanmoqda"
        row.progress = 0.0
        set_stage(
            s, row.project_id, Stage.RENDER, StageState(StageStatus.RUNNING, 0.0, "Boshlandi"), source=SOURCE
        )
        set_stage(s, row.project_id, Stage.QA, StageState(StageStatus.PENDING, None, None), source=SOURCE)
        commit_and_publish_sync(s, ctx.redis)
        return Work(
            render_id=row.id,
            project_id=row.project_id,
            preset=row.preset,
            plan=plan,
            sources={
                a.id: Source(
                    key=a.storage_key,
                    width=a.width or 0,
                    height=a.height or 0,
                    has_audio=bool(a.has_audio),
                    color_profile=a.color_profile,
                    bit_depth=a.bit_depth,
                )
                for a in assets.values()
            },
            transcripts=transcripts,
        )


def _unsupported(plan: EditPlan) -> str | None:
    """What this renderer does not execute yet — refused, never silently dropped."""
    main = [t for t in plan.video_tracks if t.role == "main"]
    if len(plan.video_tracks) > 1 and any(t.clips for t in plan.video_tracks if t not in main[:1]):
        return "Qo'shimcha video treklar (B-roll ustma-ust) hali render qilinmaydi"
    if any(t.clips for t in plan.audio_tracks):
        return "Musiqa va alohida audio treklar hali render qilinmaydi"
    for c in main[0].clips:
        if c.speed != 1.0:
            return "Tezlikni o'zgartirish hali render qilinmaydi"
        if c.transition_in and c.transition_in.type != "cut":
            return "O'tish effektlari hali render qilinmaydi"
        if c.keyframes:
            return "Keyframe animatsiyasi hali render qilinmaydi"
    return None


class _Progress:
    """Maps each step's 0..1 onto its share of the whole render."""

    def __init__(self, ctx: JobContext, render_id: uuid.UUID, weights: dict[str, float]) -> None:
        self.ctx = ctx
        self.tag = {"render_id": str(render_id)}
        total = sum(weights.values())
        self.spans: dict[str, tuple[float, float]] = {}
        at = 0.0
        for name, w in weights.items():
            self.spans[name] = (at / total, (at + w) / total)
            at += w

    def step(self, name: str, label: str):
        a, b = self.spans[name]
        self.ctx.progress(a, label, data=self.tag)
        _set_row(self.ctx, uuid.UUID(self.tag["render_id"]), step=label, progress=round(a, 3))
        return lambda f: self.ctx.progress(a + (b - a) * max(0.0, min(1.0, f)), label, data=self.tag)


def _digest(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


def _luts(plan: EditPlan, work: Path) -> dict[str, Path]:
    """One baked LUT per distinct grade (most clips of one file share it)."""
    out: dict[str, Path] = {}
    for c in plan.video_tracks[0].clips:
        for e in c.effects:
            if e.type != "grade":
                continue
            grade = ColorGrade.model_validate(e.params)
            if is_identity(grade):
                continue
            digest = _digest(e.params)
            if digest not in out:
                out[digest] = write_cube(bake(grade), work / f"grade-{digest}.cube")
    return out


def _lut_for(clip, luts: dict[str, Path]) -> Path | None:
    for e in clip.effects:
        if e.type == "grade":
            digest = _digest(e.params)
            return luts.get(digest)
    return None


def _render(ctx: JobContext, job: Work) -> Output:
    plan, seq = job.plan, job.plan.sequence
    work = ctx.scratch_dir
    clips = sorted(plan.video_tracks[0].clips, key=lambda c: c.timeline_start)
    has_overlay = bool(plan.graphics) or bool(plan.captions and plan.captions.enabled and job.transcripts)
    audio_any = any(job.sources[c.asset_id].has_audio and not c.mute_source_audio for c in clips)
    weights = {
        "segments": 40.0,
        "overlay": 35.0 if has_overlay else 0.0,
        "loudness": 3.0,
        "master": 15.0,
        "qa": 4.0,
        "copy": 3.0,
    }
    progress = _Progress(ctx, job.render_id, {k: v for k, v in weights.items() if v})

    # 1. Segments from the originals --------------------------------------------------
    on = progress.step("segments", "kesish va rang")
    luts = _luts(plan, work)
    zscale = has_filter("zscale")
    total = sum(c.timeline_duration for c in clips) or 1.0
    done = 0.0
    segments: list[tuple[Path, float]] = []
    for n, clip in enumerate(clips):
        src = job.sources[clip.asset_id]
        fill = next(
            (str(e.params.get("fill", "black")) for e in clip.effects if e.type == "background"), "black"
        )
        spec = SegmentSpec(
            source=ctx.storage.internal_get_url(src.key, INTERNAL_URL_TTL),
            start=clip.source_in,
            duration=clip.timeline_duration,
            src_w=src.width,
            src_h=src.height,
            color_profile=src.color_profile,
            bit_depth=src.bit_depth,
            scale=clip.transform.scale,
            x=clip.transform.x,
            y=clip.transform.y,
            lut=_lut_for(clip, luts),
            audio=src.has_audio and not clip.mute_source_audio,
            fill=fill,
        )
        out = work / f"seg-{n:04d}.mkv"
        base = done
        run_ffmpeg(
            segment_command(
                spec, out, width=seq.width, height=seq.height, fps=seq.fps, zscale=zscale,
                threads=ctx.settings.media_threads,
            ),
            duration=clip.timeline_duration,
            on_progress=lambda f, base=base, d=clip.timeline_duration: on((base + f * d) / total),
            check=ctx.check,
            timeout=600 + clip.timeline_duration * 30,
        )  # fmt: skip
        done += clip.timeline_duration
        segments.append((out, clip.timeline_duration))
    joined = concat_list(segments, work / "timeline.ffconcat", seq.fps)

    # 2. Motion layer ------------------------------------------------------------------
    layer: OverlayLayer | None = None
    if has_overlay:
        on = progress.step("overlay", "subtitr va grafika")
        o_w, o_h = overlay_size(seq.width, seq.height)
        props = build_overlay(plan, job.transcripts, fps=overlay_fps(seq.fps), size=(o_w, o_h))
        frames = render_overlay(
            props,
            work,
            remotion_dir=Path(ctx.settings.remotion_dir),
            concurrency=ctx.settings.remotion_concurrency,
            on_progress=on,
            check=ctx.check,
        )
        layer = OverlayLayer(pattern=Path(frames.pattern), fps=frames.fps, width=o_w, height=o_h)

    # 3. Sound: voice chain + effects, loudness measured over the whole timeline -----------
    on = progress.step("loudness", "ovoz balandligi")
    mix = MixPlan.model_validate(plan.metadata["mix"]) if plan.metadata.get("mix") else MixPlan()
    voice = voice_filters(mix, noise_floor_db=plan.metadata.get("noise_floor_db")) if audio_any else []
    sfx_dir = Path(ctx.settings.sfx_dir)
    sfx = [
        SfxInput(path=sfx_dir / f"{name.removeprefix('sfx/')}.flac", at=at)
        for at, name in sfx_cues(plan)
        if (sfx_dir / f"{name.removeprefix('sfx/')}.flac").exists()
    ]
    tail = "anull"
    if audio_any or sfx:
        log = run_ffmpeg(
            loudness_pass(joined, sfx, voice, loudnorm_measure(mix)),
            check=ctx.check,
            timeout=600 + seq.duration * 3,
        )
        measured = parse_loudnorm(log)
        if measured.get("input_i") not in ("-inf", "inf", None):
            tail = loudnorm_apply(mix, measured)
    on(1.0)

    # 4. Master -------------------------------------------------------------------------
    on = progress.step("master", "yakuniy kodlash")
    final = work / "final.mp4"
    run_ffmpeg(
        master_command(
            joined, final, width=seq.width, height=seq.height, fps=seq.fps, duration=seq.duration,
            overlay=layer, voice=voice, loudness=tail, sfx=sfx, threads=ctx.settings.media_threads,
        ),
        duration=seq.duration,
        on_progress=on,
        check=ctx.check,
        timeout=900 + seq.duration * 30,
    )  # fmt: skip
    for path, _ in segments:
        path.unlink(missing_ok=True)
    if layer is not None:
        shutil.rmtree(layer.pattern.parent, ignore_errors=True)

    # 5. QA on the actual file ------------------------------------------------------------
    on = progress.step("qa", "sifat nazorati")
    info = normalize(run_ffprobe(str(final)), size_bytes=final.stat().st_size)
    qa_log = run_ffmpeg(
        qa_command(str(final), threads=ctx.settings.media_threads),
        check=ctx.check,
        timeout=600 + seq.duration * 5,
    )
    report = judge(
        info,
        parse_qa_log(qa_log, duration=info.duration),
        Expected(
            width=seq.width,
            height=seq.height,
            fps=seq.fps,
            duration=round(round(seq.duration * seq.fps) / seq.fps, 6),
            audio=audio_any,
            target_lufs=mix.loudness.target_lufs if tail != "anull" else None,
            true_peak_db=mix.loudness.true_peak_db,
        ),
    )
    on(1.0)

    # 6. Poster and a chat-sized copy ----------------------------------------------------
    poster = work / "poster.jpg"
    run_ffmpeg(poster_command(final, poster, at=seq.duration * 0.3), check=ctx.check, timeout=120)
    telegram: Path | None = None
    if final.stat().st_size > TELEGRAM_LIMIT * 0.95:
        on = progress.step("copy", "Telegram nusxasi")
        telegram = work / "telegram.mp4"
        run_ffmpeg(
            telegram_copy_command(final, telegram, duration=seq.duration, width=seq.width, height=seq.height),
            duration=seq.duration,
            on_progress=on,
            check=ctx.check,
            timeout=900 + seq.duration * 10,
        )
        if telegram.stat().st_size > TELEGRAM_LIMIT:
            telegram = None  # very long video: the chat gets a link instead
    return Output(final=final, poster=poster, telegram=telegram, qa=report)


def _fail(ctx: JobContext, render_id: uuid.UUID, message: str, *, retrying: bool = False) -> None:
    with ctx.session() as s:
        row = s.get(Render, render_id)
        if row is None:
            return
        if retrying:
            row.status = RenderStatus.QUEUED.value
            row.error = f"qayta urinish: {message[:300]}"
            s.commit()
            return
        row.status = RenderStatus.FAILED.value
        row.error = message[:500]
        row.finished_at = utcnow()
        set_stage(
            s,
            row.project_id,
            Stage.RENDER,
            StageState(StageStatus.FAILED, None, message[:200]),
            source=SOURCE,
        )
        emit(
            s,
            project_id=row.project_id,
            type=EventType.RENDER_FAILED,
            level=EventLevel.ERROR,
            message=f"Render v{row.plan_version} bajarilmadi — {message[:200]}",
            source=SOURCE,
            data={"render_id": str(row.id)},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)


def _store(ctx: JobContext, job: Work, out: Output) -> dict[str, Any]:
    keys = {
        "final": derived_key(job.project_id, Area.RENDERS, job.render_id, "final.mp4"),
        "poster": derived_key(job.project_id, Area.RENDERS, job.render_id, "poster.jpg"),
    }
    ctx.storage.put_derived_file(keys["final"], out.final, "video/mp4")
    ctx.storage.put_derived_file(keys["poster"], out.poster, "image/jpeg")
    if out.telegram is not None:
        keys["telegram"] = derived_key(job.project_id, Area.RENDERS, job.render_id, "telegram.mp4")
        ctx.storage.put_derived_file(keys["telegram"], out.telegram, "video/mp4")
    ctx.storage.put_derived_bytes(
        derived_key(job.project_id, Area.RENDERS, job.render_id, "qa.json"),
        out.qa.model_dump_json().encode(),
        "application/json",
    )
    seq = job.plan.sequence
    size = out.final.stat().st_size
    with ctx.session() as s:
        row = s.get(Render, job.render_id, with_for_update=True)
        if row is None:
            return {"skipped": "render_deleted"}
        row.status = RenderStatus.DONE.value
        row.progress = 1.0
        row.step = None
        row.error = None
        row.output_key = keys["final"]
        row.poster_key = keys["poster"]
        row.telegram_key = keys.get("telegram")
        row.size_bytes = size
        row.duration_sec = out.qa.duration or seq.duration
        row.width, row.height, row.fps = seq.width, seq.height, seq.fps
        row.qa = out.qa.model_dump(mode="json")
        row.qa_status = out.qa.status
        row.finished_at = utcnow()
        mb = size / 1024**2
        set_stage(
            s,
            row.project_id,
            Stage.RENDER,
            StageState(StageStatus.DONE, 1.0, f"v{row.plan_version} · {mb:.0f} MB"),
            source=SOURCE,
        )
        problems = [c.message for c in out.qa.checks if c.status != "pass"]
        qa_state = StageStatus.FAILED if out.qa.status == "fail" else StageStatus.DONE
        set_stage(
            s,
            row.project_id,
            Stage.QA,
            StageState(qa_state, 1.0, "; ".join(problems[:2]) if problems else "Hammasi joyida"),
            source=SOURCE,
        )
        if row.deliver and out.qa.status != "fail":
            request_delivery(s, row)
            set_stage(
                s,
                row.project_id,
                Stage.DELIVERY,
                StageState(StageStatus.QUEUED, None, "Telegramga"),
                source=SOURCE,
            )
        elif row.deliver:
            set_stage(
                s,
                row.project_id,
                Stage.DELIVERY,
                StageState(StageStatus.BLOCKED, None, "QA xatosi sababli yuborilmadi"),
                source=SOURCE,
            )
        emit(
            s,
            project_id=row.project_id,
            type=EventType.RENDER_READY,
            message=f"Video tayyor: v{row.plan_version}, {seq.duration:.0f} s, {mb:.0f} MB · {QA_WORDS[out.qa.status]}",
            source=SOURCE,
            data={"render_id": str(row.id), "qa": out.qa.status},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)
    return {"size": size, "qa": out.qa.status, "duration": seq.duration}


@handler(JobKind.RENDER_FINAL, queue=JobQueue.RENDER)
def render_final(ctx: JobContext, payload: RenderFinalPayload) -> dict[str, Any]:
    job: Work | None = None
    try:
        job = _start(ctx, payload)
        if job is None:
            return {"skipped": "already_done"}
        out = _render(ctx, job)
    except LeaseLost:
        raise
    except JobInterrupted:
        _fail(ctx, payload.render_id, "to'xtatildi", retrying=True)
        raise
    except JobCancelled:
        _fail(ctx, payload.render_id, "bekor qilindi")
        raise
    except PermanentError as exc:
        _fail(ctx, payload.render_id, str(exc))
        raise
    except RemotionUnavailable as exc:
        _fail(ctx, payload.render_id, "Motion dvigateli o'rnatilmagan")
        raise PermanentError(f"Motion dvigateli o'rnatilmagan ({exc})") from exc
    except MediaError as exc:
        if exc.permanent or ctx.job.attempts >= ctx.job.max_attempts:
            _fail(ctx, payload.render_id, str(exc))
            raise PermanentError(str(exc)) from exc
        _fail(ctx, payload.render_id, str(exc), retrying=True)
        raise RetryableError(str(exc)) from exc
    except Exception as exc:
        last = ctx.job.attempts >= ctx.job.max_attempts
        _fail(ctx, payload.render_id, f"{type(exc).__name__}: {exc}", retrying=not last)
        raise
    return _store(ctx, job, out)
