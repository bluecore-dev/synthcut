"""Typed agent tools with per-agent permissions (spec §28, rules 3-5).

* Every tool has a Pydantic input model (``extra="forbid"``) and output model;
  model-produced arguments are validated before anything runs.
* Tool inputs may not carry filesystem paths, shell commands or SQL: inputs
  are scanned at registration and a tool that asks for them is refused.
  Tools refer to things by id (asset, plan version, render), and the
  deterministic layer resolves ids to storage keys itself.
* An agent may call only the tools in its manifest; anything else comes back
  to the model as an error result, and is recorded.
"""

from __future__ import annotations

import json
import pathlib
import re
import time
import types
import typing
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError
from synthcut_model_router import ToolDefinition

if TYPE_CHECKING:
    from .agents import AgentSpec

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "path",
        "paths",
        "file",
        "file_path",
        "filepath",
        "filename",
        "dir",
        "directory",
        "folder",
        "command",
        "cmd",
        "shell",
        "script",
        "exec",
        "executable",
        "argv",
        "sql",
    }
)


class ToolScope(StrEnum):
    READ = "read"  # reads project state, no side effects
    PLAN = "plan"  # writes plans, proposals, memories (database only)
    MEDIA = "media"  # enqueues deterministic media / render jobs
    EXTERNAL = "external"  # leaves the system (e.g. web search)


class UnsafeToolError(TypeError):
    pass


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a tool handler may act on: one project, nothing else."""

    project_id: uuid.UUID
    run_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    services: Mapping[str, Any] = field(default_factory=dict)


Handler = Callable[[ToolContext, BaseModel], BaseModel]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    scope: ToolScope
    phase: int
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None
    handler: Handler | None = None

    @property
    def implemented(self) -> bool:
        return self.handler is not None and self.input_model is not None and self.output_model is not None

    def definition(self) -> ToolDefinition:
        assert self.input_model is not None
        return ToolDefinition(
            name=self.name, description=self.description, input_schema=self.input_model.model_json_schema()
        )


def _iter_annotation_types(annotation: Any):
    origin = typing.get_origin(annotation)
    if origin is None:
        yield annotation
        return
    if origin is typing.Annotated:
        yield from _iter_annotation_types(typing.get_args(annotation)[0])
        return
    for arg in typing.get_args(annotation):
        yield from _iter_annotation_types(arg)


def assert_safe_input_model(model: type[BaseModel], _seen: set[type] | None = None) -> None:
    seen = _seen if _seen is not None else set()
    if model in seen:
        return
    seen.add(model)
    if model.model_config.get("extra") != "forbid":
        raise UnsafeToolError(f"{model.__name__} must set extra='forbid'")
    for name, info in model.model_fields.items():
        lowered = (info.alias or name).lower()
        if lowered in FORBIDDEN_FIELD_NAMES or lowered.endswith(("_path", "_file", "_dir", "_command")):
            raise UnsafeToolError(f"{model.__name__}.{name}: tools take ids, not paths or commands")
        for tp in _iter_annotation_types(info.annotation):
            if tp in (types.NoneType, Any):
                continue
            if isinstance(tp, type) and issubclass(tp, pathlib.PurePath):
                raise UnsafeToolError(f"{model.__name__}.{name}: filesystem paths are not allowed")
            if isinstance(tp, type) and issubclass(tp, BaseModel):
                assert_safe_input_model(tp, seen)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def declare(self, spec: ToolSpec) -> ToolSpec:
        if not _NAME_RE.fullmatch(spec.name):
            raise ValueError(f"invalid tool name {spec.name!r}")
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} declared twice")
        if spec.input_model is not None:
            assert_safe_input_model(spec.input_model)
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def definitions_for(self, agent: AgentSpec) -> list[ToolDefinition]:
        # Deterministic order keeps the prompt prefix byte-stable (cache hits).
        return [
            self._tools[n].definition()
            for n in sorted(agent.tools)
            if n in self._tools and self._tools[n].implemented
        ]


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    agent: str
    tool: str
    input: dict[str, Any]
    ok: bool
    output: dict[str, Any] | None
    error_code: str | None
    error: str | None
    duration_ms: int

    def as_result_text(self) -> str:
        if self.ok:
            return json.dumps(self.output, ensure_ascii=False, default=str)
        return json.dumps({"error": self.error_code, "message": self.error}, ensure_ascii=False)


def invoke_tool(
    agent: AgentSpec, registry: ToolRegistry, ctx: ToolContext, name: str, raw_input: dict[str, Any]
) -> ToolCallRecord:
    started = time.monotonic()

    def record(ok: bool, output=None, code=None, error=None) -> ToolCallRecord:
        return ToolCallRecord(
            agent=agent.name,
            tool=name,
            input=raw_input,
            ok=ok,
            output=output,
            error_code=code,
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if name not in agent.tools:
        return record(False, code="permission_denied", error=f"{agent.name} may not use {name}")
    spec = registry.get(name)
    if spec is None or not spec.implemented:
        return record(False, code="not_available", error=f"{name} is not available yet")
    assert spec.input_model is not None and spec.output_model is not None and spec.handler is not None
    try:
        args = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        return record(False, code="invalid_input", error=str(exc.errors(include_url=False))[:1000])
    try:
        result = spec.handler(ctx, args)
        output = spec.output_model.model_validate(result).model_dump(mode="json")
    except ValidationError as exc:
        return record(False, code="invalid_output", error=str(exc.errors(include_url=False))[:1000])
    except Exception as exc:  # the model gets an error result; the run continues
        return record(False, code="tool_failed", error=f"{type(exc).__name__}: {exc}"[:1000])
    return record(True, output=output)
