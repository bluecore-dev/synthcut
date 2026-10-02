"""S3-compatible object storage for SynthCut (spec §6-8)."""

from .client import (
    MultipartUploadRef,
    NoSuchUploadError,
    ObjectInfo,
    Storage,
    StorageConfig,
    StorageError,
    UploadedPart,
    md5_b64_to_hex,
)
from .keys import (
    Area,
    ImmutableOriginalError,
    InvalidKeyError,
    ParsedKey,
    assert_writable,
    derived_key,
    is_original,
    normalize_extension,
    original_key,
    parse_key,
    project_prefix,
)
from .parts import MAX_PARTS, MIB, MIN_PART_SIZE, PartPlan, expected_part_size, plan_parts

__all__ = [
    "MAX_PARTS",
    "MIB",
    "MIN_PART_SIZE",
    "Area",
    "ImmutableOriginalError",
    "InvalidKeyError",
    "MultipartUploadRef",
    "NoSuchUploadError",
    "ObjectInfo",
    "ParsedKey",
    "PartPlan",
    "Storage",
    "StorageConfig",
    "StorageError",
    "UploadedPart",
    "assert_writable",
    "derived_key",
    "expected_part_size",
    "is_original",
    "md5_b64_to_hex",
    "normalize_extension",
    "original_key",
    "parse_key",
    "plan_parts",
    "project_prefix",
]
