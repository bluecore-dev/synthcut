"""Agent specification (spec §14-28)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from synthcut_model_router import ModelRole

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Who an agent is and what it may touch. The mission becomes the stable
    head of its system prompt; ``tools`` is a closed allowlist."""

    name: str
    title: str
    mission: str
    model_role: ModelRole
    tools: frozenset[str]
    phase: int
    max_steps: int = 12
    max_cost_usd: float = 1.0

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.name):
            raise ValueError(f"invalid agent name {self.name!r}")
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
