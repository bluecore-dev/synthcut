"""Provider-independent model routing and cost accounting (spec §29, §33)."""

from .pricing import PRICES, ModelPrice, cost_usd
from .providers.anthropic import AnthropicProvider
from .providers.scripted import ScriptedProvider
from .router import (
    DEFAULT_ROUTES,
    ModelRouter,
    NoRouteError,
    Provider,
    ProviderError,
    RouteTable,
    Target,
)
from .types import (
    CompletionRequest,
    CompletionResponse,
    ContentBlock,
    ImageBlock,
    Message,
    ModelRole,
    ProviderBlock,
    StopReason,
    TextBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

__all__ = [
    "DEFAULT_ROUTES",
    "PRICES",
    "AnthropicProvider",
    "CompletionRequest",
    "CompletionResponse",
    "ContentBlock",
    "ImageBlock",
    "Message",
    "ModelPrice",
    "ModelRole",
    "ModelRouter",
    "NoRouteError",
    "Provider",
    "ProviderBlock",
    "ProviderError",
    "RouteTable",
    "ScriptedProvider",
    "StopReason",
    "Target",
    "TextBlock",
    "ToolDefinition",
    "ToolResultBlock",
    "ToolUseBlock",
    "Usage",
    "cost_usd",
]
