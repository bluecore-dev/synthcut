"""Schema versioning (spec §23: EditPlan v1, v2, ...).

Stored plans keep the ``schema_version`` they were written with. Loading
always upgrades step by step to the current version, so old timeline versions
remain restorable (spec §34) after the schema evolves.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import SCHEMA_VERSION, EditPlan

# "editplan/1" -> function returning the "editplan/2" dict, and so on.
UPGRADERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class UnknownSchemaVersionError(ValueError):
    pass


def load_plan(data: dict[str, Any]) -> EditPlan:
    version = data.get("schema_version", SCHEMA_VERSION)
    steps = 0
    while version != SCHEMA_VERSION:
        upgrade = UPGRADERS.get(version)
        if upgrade is None or steps > 20:
            raise UnknownSchemaVersionError(f"cannot upgrade EditPlan from {version!r}")
        data = upgrade(data)
        version = data.get("schema_version")
        steps += 1
    return EditPlan.model_validate(data)
