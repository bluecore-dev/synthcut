"""Claude through the official Anthropic SDK (spec §29).

Translation between the router's neutral types and the Messages API:

* requests are **streamed** and read with ``get_final_message()`` — agent
  turns can be long (whole plan patches), and streaming avoids HTTP
  timeouts; client tools carry ``eager_input_streaming`` because every tool
  input is validated by its Pydantic model before anything runs anyway
  (``synthcut_agent_sdk.invoke_tool``);
* **adaptive thinking**; thinking blocks come back as ``ProviderBlock`` and
  are sent back verbatim with the tool results they led to, as the API
  requires;
* **prompt caching**: the system prompt and the tool list are a stable
  prefix (tools are sorted by the registry), cached automatically;
* errors map to ``ProviderError`` with ``failover`` only where another
  target could succeed (rate limit, overload, outage, unknown model).
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from ..router import ProviderError
from ..types import (
    CompletionRequest,
    CompletionResponse,
    ContentBlock,
    ImageBlock,
    Message,
    ProviderBlock,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

NAME = "anthropic"
STOP = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
    "pause_turn": StopReason.PAUSE,
}
KEPT_PROVIDER_BLOCKS = {"thinking", "redacted_thinking"}
JSON_RETRIES = 2


def to_api_block(block: ContentBlock) -> dict[str, Any] | None:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ImageBlock):
        return {"type": "image", "source": {"type": "url", "url": block.url}}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, ProviderBlock) and block.provider == NAME:
        return dict(block.data)
    return None  # another provider's block


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        content = [b for b in (to_api_block(x) for x in m.content) if b is not None]
        if content:
            out.append({"role": m.role, "content": content})
    return out


def from_api_block(block: Any) -> ContentBlock | None:
    kind = getattr(block, "type", None)
    if kind == "text":
        return TextBlock(text=block.text)
    if kind == "tool_use":
        return ToolUseBlock(id=block.id, name=block.name, input=dict(block.input or {}))
    if kind in KEPT_PROVIDER_BLOCKS:
        return ProviderBlock(provider=NAME, data=block.to_dict())
    return None


def build_params(model: str, request: CompletionRequest) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": request.max_tokens,
        "system": request.system,
        "messages": to_api_messages(request.messages),
        "thinking": {"type": "adaptive"},
        "cache_control": {"type": "ephemeral"},  # the stable prefix: system + tools
    }
    if request.tools:
        params["tools"] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "eager_input_streaming": True,
            }
            for t in request.tools
        ]
    if request.effort:
        params["output_config"] = {"effort": request.effort}
    return params


def from_api_message(message: Any, model: str, latency_ms: int) -> CompletionResponse:
    usage = message.usage
    return CompletionResponse(
        provider=NAME,
        model=model,
        content=[b for b in (from_api_block(x) for x in message.content) if b is not None],
        stop_reason=STOP.get(message.stop_reason or "", StopReason.OTHER),
        usage=Usage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        ),
        latency_ms=latency_ms,
        request_id=getattr(message, "_request_id", None),
    )


def _provider_error(exc: Exception) -> ProviderError:
    failover = isinstance(
        exc,
        (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.NotFoundError,  # unknown model on this account: another target may have it
        ),
    ) or getattr(exc, "status_code", 0) in (429, 500, 502, 503, 504, 529)
    retry_after = None
    response = getattr(exc, "response", None)
    if response is not None and response.headers.get("retry-after", "").isdigit():
        retry_after = float(response.headers["retry-after"])
    # The message carries no credentials: the SDK never puts the key in errors.
    return ProviderError(
        f"{type(exc).__name__}: {str(exc)[:300]}", failover=failover, retry_after=retry_after
    )


class AnthropicProvider:
    name = NAME

    def __init__(
        self, api_key: str | None = None, *, client: Any | None = None, max_retries: int = 2
    ) -> None:
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=max_retries)

    def complete(self, model: str, request: CompletionRequest) -> CompletionResponse:
        params = build_params(model, request)
        started = time.monotonic()
        for attempt in range(JSON_RETRIES + 1):
            try:
                with self.client.messages.stream(**params) as stream:
                    message = stream.get_final_message()
                break
            except ValueError as exc:  # tool input the SDK could not parse at all: ask again
                if attempt == JSON_RETRIES:
                    raise ProviderError(f"unparseable tool input: {exc}"[:300], failover=False) from None
            except anthropic.APIError as exc:
                raise _provider_error(exc) from None
        return from_api_message(message, model, int((time.monotonic() - started) * 1000))
