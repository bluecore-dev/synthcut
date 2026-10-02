"""Job handler registry. A worker claims only the kinds registered here for
its queues, so jobs for phases not yet deployed wait instead of failing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from synthcut_schemas.enums import JobQueue
from synthcut_schemas.jobs import PAYLOAD_MODELS

if TYPE_CHECKING:
    from .context import JobContext

HandlerFn = Callable[["JobContext", Any], dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class HandlerSpec:
    kind: str
    queue: JobQueue
    payload_model: type[BaseModel]
    fn: HandlerFn


HANDLERS: dict[str, HandlerSpec] = {}


def handler(kind: str, *, queue: JobQueue) -> Callable[[HandlerFn], HandlerFn]:
    def register(fn: HandlerFn) -> HandlerFn:
        if kind in HANDLERS:
            raise ValueError(f"handler for {kind} registered twice")
        HANDLERS[kind] = HandlerSpec(kind=kind, queue=queue, payload_model=PAYLOAD_MODELS[kind], fn=fn)
        return fn

    return register


def load_handlers() -> dict[str, HandlerSpec]:
    # Importing a module registers its handlers.
    from .maintenance import jobs as _maintenance  # noqa: F401

    return HANDLERS
