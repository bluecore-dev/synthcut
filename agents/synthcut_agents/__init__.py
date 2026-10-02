"""SynthCut specialist agents: manifests now, implementations per phase."""

from .catalog import TOOL_CATALOG
from .team import TEAM, build_registry

__all__ = ["TEAM", "TOOL_CATALOG", "build_registry"]
