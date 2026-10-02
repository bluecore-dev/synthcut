"""Object key layout (spec §7) — the only place storage keys are built.

    projects/<project_id>/originals/<asset_id>/source.<ext>
    projects/<project_id>/<area>/<owner_id>/<name>

Every component is either a UUID, a member of a fixed enum, or matches a strict
pattern, so user input (file names, LLM output) can never become a path. Keys
under ``originals/`` are immutable: only the multipart upload path may create
them and nothing may overwrite or delete them (spec §52 rules 1, 3, 15).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

PROJECTS_PREFIX = "projects"
ORIGINAL_BASENAME = "source"

_EXT_RE = re.compile(r"^[a-z0-9]{1,8}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")
_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class Area(StrEnum):
    ORIGINALS = "originals"
    PROXIES = "proxies"
    AUDIO = "audio"
    THUMBNAILS = "thumbnails"
    ANALYSIS = "analysis"
    TIMELINE = "timeline"
    PREVIEWS = "previews"
    RENDERS = "renders"
    EXPORTS = "exports"


_KEY_RE = re.compile(
    rf"^{PROJECTS_PREFIX}/(?P<project>{_UUID_RE})/(?P<area>[a-z]+)/(?P<owner>{_UUID_RE})/(?P<name>[^/]+)$"
)


class InvalidKeyError(ValueError):
    pass


class ImmutableOriginalError(PermissionError):
    """Raised when code tries to write or delete an original source asset."""


@dataclass(frozen=True, slots=True)
class ParsedKey:
    project_id: UUID
    area: Area
    owner_id: UUID
    name: str

    @property
    def is_original(self) -> bool:
        return self.area is Area.ORIGINALS


def _uuid(value: UUID | str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise InvalidKeyError(f"not a UUID: {value!r}") from exc


def normalize_extension(filename: str) -> str:
    """Extension used in the original's key; falls back to ``bin``.

    Only the suffix of the user's file name is looked at, and only if it is a
    short alphanumeric token — the name itself never reaches storage.
    """
    _, dot, ext = filename.rpartition(".")
    ext = ext.lower() if dot else ""
    return ext if _EXT_RE.fullmatch(ext) else "bin"


def original_key(project_id: UUID | str, asset_id: UUID | str, extension: str) -> str:
    if not _EXT_RE.fullmatch(extension):
        raise InvalidKeyError(f"invalid extension: {extension!r}")
    return (
        f"{PROJECTS_PREFIX}/{_uuid(project_id)}/{Area.ORIGINALS}/{_uuid(asset_id)}/"
        f"{ORIGINAL_BASENAME}.{extension}"
    )


def derived_key(project_id: UUID | str, area: Area | str, owner_id: UUID | str, name: str) -> str:
    """Key for a derived file (proxy, thumbnail, analysis json, render...)."""
    area = Area(area)
    if area is Area.ORIGINALS:
        raise ImmutableOriginalError("derived files cannot be written into originals/")
    if not _NAME_RE.fullmatch(name) or ".." in name:
        raise InvalidKeyError(f"invalid derived file name: {name!r}")
    return f"{PROJECTS_PREFIX}/{_uuid(project_id)}/{area}/{_uuid(owner_id)}/{name}"


def project_prefix(project_id: UUID | str) -> str:
    return f"{PROJECTS_PREFIX}/{_uuid(project_id)}/"


def parse_key(key: str) -> ParsedKey:
    m = _KEY_RE.fullmatch(key)
    if not m:
        raise InvalidKeyError(f"not a SynthCut key: {key!r}")
    try:
        area = Area(m["area"])
    except ValueError as exc:
        raise InvalidKeyError(f"unknown area in key: {key!r}") from exc
    name = m["name"]
    if area is Area.ORIGINALS:
        base, _, ext = name.partition(".")
        if base != ORIGINAL_BASENAME or not _EXT_RE.fullmatch(ext):
            raise InvalidKeyError(f"invalid original name: {key!r}")
    elif not _NAME_RE.fullmatch(name) or ".." in name:
        raise InvalidKeyError(f"invalid derived name: {key!r}")
    return ParsedKey(UUID(m["project"]), area, UUID(m["owner"]), name)


def is_original(key: str) -> bool:
    try:
        return parse_key(key).is_original
    except InvalidKeyError:
        # Anything that does not parse is treated as protected: refusing a
        # write is recoverable, destroying an original is not.
        return True


def assert_writable(key: str) -> ParsedKey:
    """Validate a key for a derived write/delete; refuse originals."""
    parsed = parse_key(key)
    if parsed.is_original:
        raise ImmutableOriginalError(f"original media is immutable: {key}")
    return parsed
