"""Provider-neutral request/response types (spec §29, rules 11 and 18).

Agents speak only these types. Each provider adapter translates them to its
own API, so swapping Claude for another model — or running a local one — is a
routing-table change, not a code change.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelRole(StrEnum):
    """What an agent needs from a model; the router maps roles to models."""

    REASONING = "reasoning"  # master, director, QA, reflection
    PLANNING = "planning"  # editor, color, audio, motion, research
    VISION = "vision"  # frame / shot understanding
    FAST = "fast"  # captions, memory extraction, short classifications


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    PAUSE = "pause_turn"
    OTHER = "other"


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    """An image the model should look at, referenced by a short-lived URL the
    media layer produced (e.g. a proxy frame) — never by a filesystem path."""

    type: Literal["image"] = "image"
    url: str
    media_type: str = "image/jpeg"


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class CompletionRequest(BaseModel):
    system: str
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    max_tokens: int = Field(16_000, ge=1)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Tags for logs/costs, never sent as prompt"
    )


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )


class CompletionResponse(BaseModel):
    provider: str
    model: str
    content: list[ContentBlock]
    stop_reason: StopReason
    usage: Usage
    cost_usd: float = 0.0
    latency_ms: int = 0
    request_id: str | None = None

    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))
