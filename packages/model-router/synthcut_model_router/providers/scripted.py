"""A deterministic provider that replays queued responses — for tests and for
exercising agent loops without spending money or needing an API key."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from ..router import ProviderError
from ..types import CompletionRequest, CompletionResponse


class ScriptedProvider:
    def __init__(self, name: str, responses: Iterable[CompletionResponse | ProviderError] = ()) -> None:
        self.name = name
        self._queue: deque[CompletionResponse | ProviderError] = deque(responses)
        self.requests: list[tuple[str, CompletionRequest]] = []

    def push(self, item: CompletionResponse | ProviderError) -> None:
        self._queue.append(item)

    def complete(self, model: str, request: CompletionRequest) -> CompletionResponse:
        self.requests.append((model, request))
        if not self._queue:
            raise ProviderError("script exhausted", failover=False)
        item = self._queue.popleft()
        if isinstance(item, ProviderError):
            raise item
        return item.model_copy(update={"provider": self.name, "model": model})
