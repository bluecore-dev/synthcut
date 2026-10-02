"""Token prices for cost telemetry (spec §33), USD per million tokens.

Cost tracking is provider-independent: every provider reports a ``Usage`` and
the price comes from this table, keyed ``provider:model``. Prices change —
verify against the provider's pricing page when adding or updating a model
(Anthropic rates below as published 2026-06; cache writes are the 5-minute
TTL rate). An unknown model costs 0.0 and is logged, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Usage


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float
    cache_write: float


PRICES: dict[str, ModelPrice] = {
    "anthropic:claude-opus-5": ModelPrice(input=5.00, output=25.00, cache_read=0.50, cache_write=6.25),
    "anthropic:claude-opus-5-5": ModelPrice(input=4.00, output=20.00, cache_read=0.20, cache_write=5.00),
    "anthropic:claude-fable-5-1": ModelPrice(input=10.00, output=50.00, cache_read=0.25, cache_write=12.50),
    "anthropic:claude-sonnet-5": ModelPrice(input=2.00, output=10.00, cache_read=0.20, cache_write=2.50),
    "anthropic:claude-haiku-4-5": ModelPrice(input=1.00, output=5.00, cache_read=0.10, cache_write=1.25),
}


def cost_usd(target: str, usage: Usage) -> float | None:
    price = PRICES.get(target)
    if price is None:
        return None
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * price.cache_read
        + usage.cache_creation_input_tokens * price.cache_write
    )
    return round(total / 1_000_000, 6)
