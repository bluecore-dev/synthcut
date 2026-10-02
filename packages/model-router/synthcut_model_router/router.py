"""Model Router (spec §29).

Agents ask for a *role*; the routing table names an ordered chain of
``provider:model`` targets for that role. The router tries them in order,
moving on only for errors a different target can fix (rate limits, outages,
unknown model) — never for a bad request, which would fail everywhere.

The routing table comes from configuration (``MODEL_ROUTES`` JSON), so no
agent hard-codes a model and no single provider is a hard dependency.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .pricing import cost_usd
from .types import CompletionRequest, CompletionResponse, ModelRole

log = logging.getLogger(__name__)

DEFAULT_ROUTES: dict[ModelRole, tuple[str, ...]] = {
    ModelRole.REASONING: ("anthropic:claude-opus-5",),
    ModelRole.PLANNING: ("anthropic:claude-opus-5",),
    ModelRole.VISION: ("anthropic:claude-opus-5",),
    ModelRole.FAST: ("anthropic:claude-opus-5",),
}


class ProviderError(RuntimeError):
    """A provider call failed. ``failover`` means another target may succeed."""

    def __init__(self, message: str, *, failover: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.failover = failover
        self.retry_after = retry_after


class NoRouteError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete(self, model: str, request: CompletionRequest) -> CompletionResponse: ...


@dataclass(frozen=True, slots=True)
class Target:
    provider: str
    model: str

    @classmethod
    def parse(cls, spec: str) -> Target:
        provider, sep, model = spec.partition(":")
        if not sep or not provider or not model:
            raise ValueError(f"route target must be 'provider:model', got {spec!r}")
        return cls(provider, model)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


class RouteTable:
    def __init__(self, routes: Mapping[ModelRole, tuple[str, ...]]) -> None:
        self._routes = {
            ModelRole(role): tuple(Target.parse(t) for t in targets) for role, targets in routes.items()
        }

    @classmethod
    def from_json(cls, raw: str | None) -> RouteTable:
        routes: dict[ModelRole, tuple[str, ...]] = dict(DEFAULT_ROUTES)
        if raw:
            for role, targets in json.loads(raw).items():
                routes[ModelRole(role)] = tuple(targets)
        return cls(routes)

    def targets(self, role: ModelRole) -> tuple[Target, ...]:
        targets = self._routes.get(role, ())
        if not targets:
            raise NoRouteError(f"no model configured for role {role}")
        return targets


UsageSink = Callable[[ModelRole, CompletionResponse], None]


class ModelRouter:
    def __init__(
        self, table: RouteTable, providers: Mapping[str, Provider], *, on_usage: UsageSink | None = None
    ):
        self.table = table
        self.providers = dict(providers)
        self.on_usage = on_usage

    def complete(self, role: ModelRole, request: CompletionRequest) -> CompletionResponse:
        errors: list[str] = []
        for target in self.table.targets(role):
            provider = self.providers.get(target.provider)
            if provider is None:
                errors.append(f"{target}: provider not configured")
                continue
            started = time.monotonic()
            try:
                response = provider.complete(target.model, request)
            except ProviderError as exc:
                errors.append(f"{target}: {exc}")
                if not exc.failover:
                    raise
                log.warning("model target failed, trying next", extra={"target": str(target), "role": role})
                continue
            price = cost_usd(str(target), response.usage)
            if price is None:
                log.warning("no price for model; cost recorded as 0", extra={"target": str(target)})
            response = response.model_copy(
                update={
                    "cost_usd": price or 0.0,
                    "latency_ms": response.latency_ms or int((time.monotonic() - started) * 1000),
                }
            )
            if self.on_usage:
                self.on_usage(role, response)
            return response
        raise NoRouteError(f"all targets failed for role {role}: " + "; ".join(errors))
