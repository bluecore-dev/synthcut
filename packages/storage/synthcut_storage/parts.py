"""Multipart part sizing.

S3 allows at most 10 000 parts of at least 5 MiB (the last part may be
smaller). We keep a margin under the part limit and grow the part size in whole
MiB so that 4–50 GB projects (spec §6) stay well inside it:

    5 GB   -> 16 MiB × 299 parts
    50 GB  -> 16 MiB × 2 981 parts
    200 GB -> 22 MiB × 8 670 parts
"""

from __future__ import annotations

from dataclasses import dataclass

MIB = 1024 * 1024
MIN_PART_SIZE = 5 * MIB
MAX_PARTS = 10_000
_TARGET_MAX_PARTS = 9_000


@dataclass(frozen=True, slots=True)
class PartPlan:
    part_size: int
    part_count: int

    def size_of(self, number: int, total_size: int) -> int:
        return expected_part_size(number, total_size, self.part_size, self.part_count)


def plan_parts(total_size: int, preferred_part_size: int = 16 * MIB) -> PartPlan:
    if total_size <= 0:
        raise ValueError("total_size must be positive")
    part_size = max(preferred_part_size, MIN_PART_SIZE)
    minimum_for_limit = -(-total_size // _TARGET_MAX_PARTS)  # ceil division
    if part_size < minimum_for_limit:
        part_size = -(-minimum_for_limit // MIB) * MIB
    part_count = -(-total_size // part_size)
    if part_count > MAX_PARTS:  # pragma: no cover - guarded by the sizing above
        raise ValueError("file too large for multipart upload")
    return PartPlan(part_size=part_size, part_count=part_count)


def expected_part_size(number: int, total_size: int, part_size: int, part_count: int) -> int:
    if not 1 <= number <= part_count:
        raise ValueError(f"part number {number} out of range 1..{part_count}")
    if number < part_count:
        return part_size
    return total_size - part_size * (part_count - 1)
