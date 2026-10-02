"""Which source files SynthCut accepts. The extension decides the kind; the
real format is established later by ffprobe during ingestion."""

from __future__ import annotations

from synthcut_schemas.enums import AssetKind
from synthcut_storage import normalize_extension

VIDEO_EXTENSIONS = frozenset(
    {
        "mp4",
        "mov",
        "m4v",
        "mkv",
        "mxf",
        "avi",
        "webm",
        "mts",
        "m2ts",
        "ts",
        "3gp",
        "hevc",
        "braw",
        "r3d",
        "crm",
    }
)
AUDIO_EXTENSIONS = frozenset({"wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "aif", "aiff", "caf"})
IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "heic", "heif", "webp", "tif", "tiff", "dng"})


class UnsupportedMediaError(ValueError):
    pass


def classify(filename: str, content_type: str) -> tuple[AssetKind, str]:
    ext = normalize_extension(filename)
    if ext in VIDEO_EXTENSIONS:
        return AssetKind.VIDEO, ext
    if ext in AUDIO_EXTENSIONS:
        return AssetKind.AUDIO, ext
    if ext in IMAGE_EXTENSIONS:
        return AssetKind.IMAGE, ext
    major = content_type.split("/", 1)[0].lower()
    if major in ("video", "audio", "image"):
        return AssetKind(major), ext
    raise UnsupportedMediaError(f"unsupported file type: .{ext} ({content_type})")


def safe_display_name(filename: str) -> str:
    """The user's name for the file, for display only — it never reaches a path."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:255] or "untitled"
