"""The tool catalog: every tool any agent may ever be granted (spec §28).

Phase 0 fixes names, scopes and the phase that implements each tool. A tool
becomes callable only when its phase attaches input/output models and a
handler; until then an agent asking for it gets ``not_available``.
"""

from __future__ import annotations

from synthcut_agent_sdk import ToolScope

R, P, M, X = ToolScope.READ, ToolScope.PLAN, ToolScope.MEDIA, ToolScope.EXTERNAL

# name: (scope, phase, description)
TOOL_CATALOG: dict[str, tuple[ToolScope, int, str]] = {
    # read ------------------------------------------------------------------------
    "get_project_context": (R, 1, "Project settings, brief, output preset and mode"),
    "get_pipeline_state": (R, 1, "Stage statuses and recent jobs of the project"),
    "get_media_metadata": (R, 3, "Normalized technical metadata of one asset (ffprobe, color, audio)"),
    "get_shot_list": (R, 3, "Detected shots and scene cuts of one asset"),
    "get_transcript": (R, 4, "Word-level transcript with timestamps for an asset or the project"),
    "get_clip_frames": (R, 5, "Sampled frames of a clip as short-lived image references"),
    "get_video_analysis": (R, 5, "Per-clip analysis records (framing, quality, semantics, usability)"),
    "get_edit_plan": (R, 6, "The current or a specific EditPlan version"),
    "validate_plan": (R, 6, "Validate an EditPlan against the timeline rules and project assets"),
    "list_motion_components": (R, 7, "The registered motion-graphics components and their props"),
    "get_qa_report": (R, 9, "QA findings for a plan or render"),
    "get_user_preferences": (R, 10, "Structured user and project style preferences"),
    "search_knowledge": (R, 10, "Retrieve verified research notes"),
    "get_render_logs": (R, 11, "Logs and probe results of a render"),
    # plan (database writes only) ---------------------------------------------------
    "save_clip_analysis": (P, 5, "Store the analysis of one clip"),
    "create_edit_plan": (P, 6, "Store a new EditPlan version (validated before it is saved)"),
    "update_edit_plan": (P, 6, "Apply patch operations to an EditPlan, creating a new version"),
    "request_user_confirmation": (P, 6, "Ask the user to approve a decision (Assisted mode)"),
    "place_graphics": (P, 7, "Add or move registry motion components on the timeline"),
    "generate_captions": (P, 7, "Build the caption track from the transcript"),
    "generate_grade": (P, 8, "Store color decisions (input transform, exposure, WB, creative look)"),
    "generate_mix_plan": (P, 8, "Store audio decisions (cleanup chain, music, ducking, loudness target)"),
    "report_issues": (P, 9, "Record QA findings"),
    "propose_patch": (P, 9, "Propose a patch that fixes classified QA failures"),
    "record_feedback": (P, 10, "Record a user correction as structured feedback"),
    "update_preference": (P, 10, "Update a structured preference (e.g. transition_density=lower)"),
    "save_research_note": (P, 10, "Store an extracted, verified research note with its sources"),
    # compute (enqueues deterministic jobs) ---------------------------------------------
    "dispatch_agent": (M, 6, "Start a specialist agent run as a background job"),
    "analyze_color": (M, 8, "Measure exposure, white balance and skin tones of clips"),
    "analyze_audio": (M, 8, "Measure loudness, noise floor and clipping of audio"),
    "render_remotion": (M, 7, "Render a motion-graphics layer from a validated plan"),
    "inspect_render": (M, 9, "Technical probes of a render: black frames, loudness, fps, aspect"),
    "render_ffmpeg": (M, 11, "Render preview or final video from a validated plan"),
    # external -------------------------------------------------------------------------
    "web_search": (X, 10, "Search the web; results go through extract → verify → store"),
}
