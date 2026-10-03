"""JSON Schema of everything the Remotion app consumes: ``overlay/1`` and the
props of every registered component. ``make motion-types`` turns it into
TypeScript, so the React widgets and the Python registry cannot drift.

    python -m synthcut_timeline.schema > apps/remotion/src/generated/schema.json
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import create_model

from .overlay import OverlayProps
from .registry import GRAPHICS_REGISTRY


def _strip_field_titles(node: Any) -> Any:
    """Pydantic titles every field; TypeScript generators turn each title into
    a named alias (``Accent6``). Only model titles are kept."""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for field in props.values():
                if isinstance(field, dict):
                    field.pop("title", None)
        return {k: _strip_field_titles(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strip_field_titles(v) for v in node]
    return node


def motion_schema() -> dict[str, Any]:
    components = create_model(  # type: ignore[call-overload]
        "ComponentProps",
        **{name: (spec.props_model, ...) for name, spec in GRAPHICS_REGISTRY.items() if spec.props_model},
    )
    root = create_model("MotionSchema", overlay=(OverlayProps, ...), components=(components, ...))
    return _strip_field_titles(root.model_json_schema(mode="serialization"))


if __name__ == "__main__":
    json.dump(motion_schema(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
