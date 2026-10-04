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
    from .analysis import jobs as _analysis  # noqa: F401
    from .delivery import notify as _notify  # noqa: F401
    from .ingestion import jobs as _ingestion  # noqa: F401
    from .maintenance import jobs as _maintenance  # noqa: F401
    from .render import enhance as _enhance  # noqa: F401
    from .render import jobs as _render  # noqa: F401
    from .speech import jobs as _speech  # noqa: F401

    return HANDLERS
