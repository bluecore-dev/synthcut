"""Live tool handlers (spec §28): what the agents can read and change.

Every handler acts on ``ctx.project_id`` only and refers to things by id.
Services come in ``ctx.services``: ``sessions`` (a sync sessionmaker),
``storage`` and ``findings`` (a list the QA agent's reports go to). Plans
are never saved unless ``validate_plan`` passes; the issues go back to the
agent instead.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from synthcut_agent_sdk import ToolContext, ToolRegistry, ToolSpec
from synthcut_core.models import (
    Asset,
    AssetAnalysis,
    AssetTranscript,
    ClipAnalysisRow,
    EditPlanRow,
    Preference,
    Project,
    Render,
    User,
)
from synthcut_core.preferences import EDIT_KEYS, overlay
from synthcut_core.renders import request_render
from synthcut_schemas.enums import PRESET_SPECS, ProjectPreset, TranscriptStatus
from synthcut_schemas.grade import ColorGrade
from synthcut_schemas.speech import Transcript
from synthcut_timeline import AssetFacts, load_plan, validate_plan
from synthcut_timeline.registry import GRAPHICS_REGISTRY

from ..catalog import TOOL_CATALOG
from .planedit import GraphicIn, PlanEdit, apply_edit, summary


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


def _session(ctx: ToolContext):
    return ctx.services["sessions"]()


def _project(s, ctx: ToolContext) -> Project:
    project = s.get(Project, ctx.project_id)
    if project is None:
        raise LookupError("project not found")
    return project


def _asset(s, ctx: ToolContext, asset_id: uuid.UUID) -> Asset:
    asset = s.get(Asset, asset_id)
    if asset is None or asset.project_id != ctx.project_id or asset.deleted_at is not None:
        raise LookupError(f"asset {asset_id} is not in this project")
    return asset


def _plan_row(s, ctx: ToolContext, version: int | None) -> EditPlanRow:
    stmt = select(EditPlanRow).where(EditPlanRow.project_id == ctx.project_id)
    stmt = (
        stmt.where(EditPlanRow.version == version) if version else stmt.order_by(EditPlanRow.version.desc())
    )
    row = s.scalars(stmt.limit(1)).first()
    if row is None:
        raise LookupError("no plan yet" if version is None else f"plan version {version} not found")
    return row


def _facts(
    s, project_id: uuid.UUID
) -> tuple[dict[uuid.UUID, AssetFacts], dict[uuid.UUID, float], dict[uuid.UUID, str]]:
    assets = list(s.scalars(select(Asset).where(Asset.project_id == project_id, Asset.deleted_at.is_(None))))
    facts = {
        a.id: AssetFacts(kind=a.kind, duration=a.duration_sec, has_audio=bool(a.has_audio)) for a in assets
    }
    durations = {a.id: float(a.duration_sec) for a in assets if a.duration_sec}
    return facts, durations, {a.id: a.original_filename for a in assets}


# --------------------------------------------------------------------------- read


class Nothing(_In):
    pass


def get_project_context(ctx: ToolContext, _: Nothing) -> _Out:
    with _session(ctx) as s:
        project = _project(s, ctx)
        spec = PRESET_SPECS[ProjectPreset(project.preset)]
        speech = {
            t.asset_id: t
            for t in s.scalars(select(AssetTranscript).where(AssetTranscript.project_id == project.id))
        }
        shots = dict(
            s.execute(
                select(AssetAnalysis.asset_id, AssetAnalysis.clip_count).where(
                    AssetAnalysis.project_id == project.id
                )
            ).all()
        )
        assets = []
        for a in s.scalars(
            select(Asset)
            .where(Asset.project_id == project.id, Asset.deleted_at.is_(None))
            .order_by(Asset.sort_index)
        ):
            t = speech.get(a.id)
            assets.append(
                {
                    "asset_id": str(a.id),
                    "kind": a.kind,
                    "name": a.original_filename,
                    "status": a.status,
                    "duration": a.duration_sec,
                    "size": f"{a.width}x{a.height}" if a.width else None,
                    "fps": a.fps,
                    "has_audio": a.has_audio,
                    "color": a.color_profile,
                    "speech_seconds": t.speech_sec
                    if t is not None and t.status == TranscriptStatus.DONE.value
                    else None,
                    "words": t.word_count if t is not None else None,
                    "shots": shots.get(a.id),
                }
            )
        latest = s.scalar(select(func.max(EditPlanRow.version)).where(EditPlanRow.project_id == project.id))
        return _Out(
            name=project.name,
            preset=project.preset,
            frame=f"{spec.width}x{spec.height} ({spec.aspect})",
            fps=project.fps,
            target_duration=project.target_duration_sec,
            language=project.language,
            brief=project.brief,
            mode=project.mode,
            assets=assets,
            latest_plan_version=latest,
        )


class AssetIn(_In):
    asset_id: uuid.UUID


class TranscriptIn(_In):
    asset_id: uuid.UUID
    start: float | None = Field(None, ge=0, description="Only this part (source seconds)")
    end: float | None = Field(None, gt=0)
    words: bool = Field(False, description="Word timings too (use with a range; long)")


def get_transcript(ctx: ToolContext, args: TranscriptIn) -> _Out:
    with _session(ctx) as s:
        _asset(s, ctx, args.asset_id)
        row = s.scalar(select(AssetTranscript).where(AssetTranscript.asset_id == args.asset_id))
        if row is None or row.status != TranscriptStatus.DONE.value or not row.data:
            return _Out(asset_id=str(args.asset_id), available=False, segments=[])
        t = Transcript.model_validate(row.data)
    lo, hi = args.start or 0.0, args.end or float("inf")
    segments = [
        {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
        for seg in t.segments
        if seg.end > lo and seg.start < hi
    ]
    out: dict[str, Any] = {
        "asset_id": str(args.asset_id),
        "available": True,
        "language": t.language,
        "duration": t.duration,
        "segments": segments,
        "pauses_over_0_6s": [
            {"start": round(sl.start, 2), "end": round(sl.end, 2)} for sl in t.silences if sl.duration >= 0.6
        ][:200],
    }
    if args.words:
        out["words"] = [
            {"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
            for w in t.words
            if w.end > lo and w.start < hi
        ][:1500]
    return _Out(**out)


def get_video_analysis(ctx: ToolContext, args: AssetIn) -> _Out:
    with _session(ctx) as s:
        _asset(s, ctx, args.asset_id)
        rows = list(
            s.scalars(
                select(ClipAnalysisRow)
                .where(ClipAnalysisRow.asset_id == args.asset_id)
                .order_by(ClipAnalysisRow.shot_index)
            )
        )
    shots = []
    for r in rows:
        d = r.data
        faces = d.get("faces") or []
        shots.append(
            {
                "shot": r.shot_index,
                "start": round(r.start_sec, 2),
                "end": round(r.end_sec, 2),
                "type": r.shot_type,
                "camera": r.camera_motion,
                "faces": len(faces),
                "face_x": round(faces[0]["x"], 2) if faces else None,
                "usable": round(r.usable_score, 2),
                "flags": r.flags,
                "speech_ratio": round(d.get("speech_ratio", 0.0), 2),
                "sharpness": round(d.get("sharpness", 0.0), 2),
            }
        )
    return _Out(asset_id=str(args.asset_id), shots=shots)


def get_media_metadata(ctx: ToolContext, args: AssetIn) -> _Out:
    with _session(ctx) as s:
        a = _asset(s, ctx, args.asset_id)
        info = a.media_info or {}
    color = info.get("color") or {}
    return _Out(
        asset_id=str(a.id),
        kind=a.kind,
        duration=a.duration_sec,
        size=f"{a.width}x{a.height}" if a.width else None,
        fps=a.fps,
        video_codec=a.video_codec,
        bit_depth=a.bit_depth,
        color={"profile": color.get("profile"), "hdr": color.get("hdr"), "log": color.get("log")},
        loudness=info.get("loudness"),
        has_audio=a.has_audio,
    )


class VersionIn(_In):
    version: int | None = Field(None, ge=1, description="Latest if omitted")


def get_edit_plan(ctx: ToolContext, args: VersionIn) -> _Out:
    with _session(ctx) as s:
        row = _plan_row(s, ctx, args.version)
        return _Out(version=row.version, source=row.source, notes=row.notes, plan=row.plan)


def validate_plan_tool(ctx: ToolContext, args: VersionIn) -> _Out:
    with _session(ctx) as s:
        row = _plan_row(s, ctx, args.version)
        facts, _, _ = _facts(s, ctx.project_id)
    report = validate_plan(load_plan(row.plan), assets=facts)
    return _Out(
        version=row.version,
        ok=report.ok,
        issues=[
            {"code": i.code, "severity": i.severity.value, "path": i.path, "message": i.message}
            for i in report.issues
        ],
    )


def list_motion_components(ctx: ToolContext, _: Nothing) -> _Out:
    return _Out(
        components=[
            {
                "component": name,
                "description": spec.description,
                "min_duration": spec.min_duration,
                "props": spec.props_model.model_json_schema().get("properties", {})
                if spec.props_model
                else {},
            }
            for name, spec in sorted(GRAPHICS_REGISTRY.items())
        ]
    )


def get_user_preferences(ctx: ToolContext, _: Nothing) -> _Out:
    with _session(ctx) as s:
        owner = s.scalar(select(Project.owner_id).where(Project.id == ctx.project_id))
        rows = s.scalars(
            select(Preference).where(
                Preference.user_id == owner, Preference.project_id.is_(None), Preference.key.in_(EDIT_KEYS)
            )
        )
        values, sources = overlay(rows)
        user = s.get(User, owner)
    return _Out(
        values=values.model_dump(mode="json"),
        set_by_user=sources,
        language=user.language_code if user else None,
    )


# --------------------------------------------------------------------------- plan


def _save(ctx: ToolContext, edit: PlanEdit, agent: str) -> _Out:
    with _session(ctx) as s:
        base_row = _plan_row(s, ctx, edit.base_version)
        base = load_plan(base_row.plan)
        facts, durations, names = _facts(s, ctx.project_id)
        version = (
            int(
                s.scalar(
                    select(func.max(EditPlanRow.version)).where(EditPlanRow.project_id == ctx.project_id)
                )
                or 0
            )
            + 1
        )
        try:
            plan = apply_edit(base, edit, version=version, durations=durations, names=names, agent=agent)
        except ValueError as exc:
            return _Out(
                ok=False, version=None, issues=[{"code": "E_EDIT", "path": "", "message": str(exc)[:500]}]
            )
        report = validate_plan(plan, assets=facts)
        if not report.ok:
            return _Out(
                ok=False,
                version=None,
                issues=[{"code": i.code, "path": i.path, "message": i.message} for i in report.errors][:30],
                hint="Nothing was saved. Fix these and call again with the same base_version.",
            )
        row = EditPlanRow(
            project_id=ctx.project_id,
            version=version,
            source="director",
            plan=plan.model_dump(mode="json"),
            duration_sec=plan.sequence.duration,
            clip_count=len(plan.video_tracks[0].clips),
            notes=plan.notes,
            options={**(base_row.options or {}), "agent": agent, "base_version": base_row.version},
        )
        s.add(row)
        s.commit()
        ctx.services.setdefault("versions", []).append(version)
        return _Out(
            ok=True,
            version=version,
            summary=summary(plan),
            warnings=[i.message for i in report.warnings][:10],
        )


def create_edit_plan(ctx: ToolContext, args: PlanEdit) -> _Out:
    if args.main is None:
        return _Out(
            ok=False, version=None, issues=[{"code": "E_EDIT", "path": "main", "message": "main is required"}]
        )
    return _save(ctx, args, "director")


def update_edit_plan(ctx: ToolContext, args: PlanEdit) -> _Out:
    return _save(ctx, args, ctx.services.get("agent", "editor"))


class GraphicsEdit(_In):
    base_version: int | None = None
    graphics: list[GraphicIn] = Field(
        max_length=100, description="Full list of graphics (replaces the current ones)"
    )
    notes: str = Field(min_length=3, max_length=1000)


def place_graphics(ctx: ToolContext, args: GraphicsEdit) -> _Out:
    edit = PlanEdit(base_version=args.base_version, graphics=args.graphics, notes=args.notes)
    return _save(ctx, edit, "motion")


class CaptionsEdit(_In):
    base_version: int | None = None
    enabled: bool = True
    style: Literal["dynamic", "karaoke", "minimal", "bold"] = "dynamic"
    position: Literal["bottom", "center", "top"] = "bottom"
    max_words_per_line: int = Field(3, ge=1, le=8)
    notes: str = Field(min_length=3, max_length=500)


def generate_captions(ctx: ToolContext, args: CaptionsEdit) -> _Out:
    edit = PlanEdit.model_validate(
        {
            "base_version": args.base_version,
            "captions": args.model_dump(include={"enabled", "style", "position", "max_words_per_line"}),
            "notes": args.notes,
        }
    )
    return _save(ctx, edit, "caption")


class GradeEdit(_In):
    base_version: int | None = None
    asset_id: uuid.UUID
    exposure: float = Field(0.0, ge=-2, le=2)
    temperature: float = Field(0.0, ge=-40, le=40)
    tint: float = Field(0.0, ge=-40, le=40)
    contrast: float = Field(1.0, ge=0.6, le=1.5)
    saturation: float = Field(1.0, ge=0.0, le=1.8)
    creative_profile: Literal[
        "neutral", "cinematic_clean", "warm_film", "cool_teal", "vivid_social", "bw_classic"
    ] = "cinematic_clean"
    intensity: float = Field(0.8, ge=0, le=1)
    notes: str = Field(min_length=3, max_length=500)


def generate_grade(ctx: ToolContext, args: GradeEdit) -> _Out:
    with _session(ctx) as s:
        _asset(s, ctx, args.asset_id)
        row = _plan_row(s, ctx, args.base_version)
    plan = load_plan(row.plan)
    old = next(
        (
            e.params
            for t in plan.video_tracks
            for c in t.clips
            if c.asset_id == args.asset_id
            for e in c.effects
            if e.type == "grade"
        ),
        {},
    )
    grade = ColorGrade.model_validate(
        {**old, **args.model_dump(exclude={"base_version", "asset_id", "notes"}), "notes": [args.notes]}
    )
    data = plan.model_dump(mode="json")
    for track in data["video_tracks"]:
        for clip in track["clips"]:
            if clip["asset_id"] == str(args.asset_id):
                clip["effects"] = [e for e in clip["effects"] if e["type"] != "grade"] + [
                    {"type": "grade", "params": grade.model_dump(mode="json")}
                ]
    return _store_whole(ctx, row, data, args.notes, "color")


class MixEdit(_In):
    base_version: int | None = None
    loudness: Literal["social", "youtube", "podcast", "broadcast"] = "social"
    denoise: Literal["off", "light", "medium", "strong"] | None = None
    music_gain_db: float | None = Field(None, ge=-40, le=-6)
    notes: str = Field(min_length=3, max_length=500)


TARGETS = {
    "social": (-14.0, -1.0),
    "youtube": (-14.0, -1.0),
    "podcast": (-16.0, -1.0),
    "broadcast": (-23.0, -2.0),
}


def generate_mix_plan(ctx: ToolContext, args: MixEdit) -> _Out:
    with _session(ctx) as s:
        row = _plan_row(s, ctx, args.base_version)
    data = load_plan(row.plan).model_dump(mode="json")
    mix = dict(data["metadata"].get("mix") or {"schema_version": "mix/1"})
    lufs, peak = TARGETS[args.loudness]
    mix["loudness"] = {**(mix.get("loudness") or {}), "target_lufs": lufs, "true_peak_db": peak}
    if args.denoise is not None:
        mix["voice"] = {**(mix.get("voice") or {}), "denoise": args.denoise}
    data["metadata"]["mix"] = mix
    if args.music_gain_db is not None:
        for track in data["audio_tracks"]:
            if track["role"] == "music":
                for clip in track["clips"]:
                    clip["gain_db"] = args.music_gain_db
    return _store_whole(ctx, row, data, args.notes, "audio")


def _store_whole(ctx: ToolContext, base_row: EditPlanRow, data: dict, notes: str, agent: str) -> _Out:
    with _session(ctx) as s:
        facts, _, _ = _facts(s, ctx.project_id)
        version = (
            int(
                s.scalar(
                    select(func.max(EditPlanRow.version)).where(EditPlanRow.project_id == ctx.project_id)
                )
                or 0
            )
            + 1
        )
        data = {
            **data,
            "version": version,
            "notes": notes,
            "metadata": {**data["metadata"], "created_by": agent, "base_version": base_row.version},
        }
        plan = load_plan(data)
        report = validate_plan(plan, assets=facts)
        if not report.ok:
            return _Out(
                ok=False,
                version=None,
                issues=[{"code": i.code, "path": i.path, "message": i.message} for i in report.errors][:30],
            )
        s.add(
            EditPlanRow(
                project_id=ctx.project_id, version=version, source="director", plan=plan.model_dump(mode="json"),
                duration_sec=plan.sequence.duration, clip_count=len(plan.video_tracks[0].clips), notes=notes,
                options={**(base_row.options or {}), "agent": agent, "base_version": base_row.version},
            )
        )  # fmt: skip
        s.commit()
    ctx.services.setdefault("versions", []).append(version)
    return _Out(ok=True, version=version, summary=summary(plan))


class Finding(_In):
    severity: Literal["error", "warning", "note"]
    message: str = Field(min_length=3, max_length=500)
    at: float | None = Field(None, ge=0, description="Timeline second, if it is about a moment")


class FindingsIn(_In):
    findings: list[Finding] = Field(max_length=30)


def report_issues(ctx: ToolContext, args: FindingsIn) -> _Out:
    ctx.services.setdefault("findings", []).extend(f.model_dump() for f in args.findings)
    return _Out(recorded=len(args.findings))


# --------------------------------------------------------------------------- media


class RenderIn(_In):
    version: int | None = Field(None, ge=1)
    deliver: bool = False


def render_ffmpeg(ctx: ToolContext, args: RenderIn) -> _Out:
    with _session(ctx) as s:
        row = _plan_row(s, ctx, args.version)
        preset = (row.options or {}).get("preset") or _project(s, ctx).preset
        render, queued = request_render(s, row, preset=preset, deliver=args.deliver)
        s.commit()
        return _Out(render_id=str(render.id), status=render.status, queued=queued)


class RenderRef(_In):
    render_id: uuid.UUID


def inspect_render(ctx: ToolContext, args: RenderRef) -> _Out:
    with _session(ctx) as s:
        r = s.get(Render, args.render_id)
        if r is None or r.project_id != ctx.project_id:
            raise LookupError("render not found")
        return _Out(
            status=r.status,
            step=r.step,
            qa_status=r.qa_status,
            qa=r.qa,
            error=r.error,
            duration=r.duration_sec,
        )


# --------------------------------------------------------------------------- registry

HANDLERS: dict[str, tuple[type[BaseModel], Any]] = {
    "get_project_context": (Nothing, get_project_context),
    "get_transcript": (TranscriptIn, get_transcript),
    "get_video_analysis": (AssetIn, get_video_analysis),
    "get_shot_list": (AssetIn, get_video_analysis),
    "get_media_metadata": (AssetIn, get_media_metadata),
    "get_edit_plan": (VersionIn, get_edit_plan),
    "validate_plan": (VersionIn, validate_plan_tool),
    "list_motion_components": (Nothing, list_motion_components),
    "get_user_preferences": (Nothing, get_user_preferences),
    "create_edit_plan": (PlanEdit, create_edit_plan),
    "update_edit_plan": (PlanEdit, update_edit_plan),
    "place_graphics": (GraphicsEdit, place_graphics),
    "generate_captions": (CaptionsEdit, generate_captions),
    "generate_grade": (GradeEdit, generate_grade),
    "generate_mix_plan": (MixEdit, generate_mix_plan),
    "report_issues": (FindingsIn, report_issues),
    "render_ffmpeg": (RenderIn, render_ffmpeg),
    "inspect_render": (RenderRef, inspect_render),
    "get_qa_report": (RenderRef, inspect_render),
}


def build_live_registry() -> ToolRegistry:
    """Every catalog tool; the ones with a handler are callable."""
    registry = ToolRegistry()
    for name, (scope, phase, description) in TOOL_CATALOG.items():
        if name in HANDLERS:
            model, fn = HANDLERS[name]
            registry.declare(ToolSpec(name, description, scope, phase, model, _Out, fn))
        else:
            registry.declare(ToolSpec(name=name, description=description, scope=scope, phase=phase))
    return registry
