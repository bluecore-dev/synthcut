"""Quality control of a rendered file (spec §26, Phase 9): what the QA agent
will read, measured on the actual output — never on the plan's intentions.

One decode of the final file measures black frames, frozen picture,
loudness, true peak and silences; ffprobe checks the container. Each check
is ``pass`` / ``warn`` / ``fail``; the report's status is the worst of them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["pass", "warn", "fail"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class QaSpan(_Contract):
    start: float
    end: float


class QaCheck(_Contract):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    status: Verdict
    message: str  # Uzbek, for the owner
    value: float | str | None = None


class QaReport(_Contract):
    schema_version: Literal["qa/1"] = "qa/1"
    status: Verdict
    checks: list[QaCheck]
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    duration: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    integrated_lufs: float | None = None
    true_peak_db: float | None = None
    black: list[QaSpan] = Field(default_factory=list)
    frozen: list[QaSpan] = Field(default_factory=list)
    silence: list[QaSpan] = Field(default_factory=list)
