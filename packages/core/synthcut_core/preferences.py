"""Preferences and feedback (spec §26, Phase 10).

* ``effective_defaults`` — built-in defaults overlaid by the user's stored
  preferences: what the next Tez montaj starts from.
* ``remember_choice`` — the options of a Tez montaj request become the
  user's defaults ("start from what I chose last time").
* ``apply_feedback`` — each quick correction is a fixed rule on one or two
  preferences, returned as explained changes; nothing is hidden.

Stored one row per (user, key); project-scoped rows are reserved for the
Memory agent (``scope``), and never written here yet.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_schemas.preferences import EDIT_KEYS, EditDefaults, FeedbackCode

from .models import Preference, utcnow

DENOISE_STEPS = ["off", "light", "medium", "strong"]
LOUDNESS_STEPS = ["broadcast", "podcast", "social"]  # quiet → loud (youtube = social level)

KEY_LABELS: dict[str, str] = {
    "remove_pauses": "Pauzalarni kesish",
    "min_pause": "Kesiladigan pauza",
    "captions": "Subtitr",
    "caption_position": "Subtitr joyi",
    "profile": "Ko'rinish",
    "intensity": "Rang kuchi",
    "loudness": "Ovoz balandligi",
    "denoise": "Shovqin tozalash",
    "music": "Fon musiqasi",
    "music_gain_db": "Musiqa balandligi",
    "deliver": "Telegramga yuborish",
}

VALUE_WORDS: dict[str, str] = {
    "off": "o'chiq",
    "auto": "avto",
    "light": "yengil",
    "medium": "o'rta",
    "strong": "kuchli",
    "dynamic": "dinamik",
    "karaoke": "karaoke",
    "minimal": "oddiy",
    "bold": "qalin",
    "social": "ijtimoiy tarmoq (−14)",
    "youtube": "YouTube (−14)",
    "podcast": "podkast (−16)",
    "broadcast": "TV (−23)",
}


def describe(key: str, value: Any) -> str:
    if key == "min_pause":
        return f"{value:g} s dan uzun"
    if key == "intensity":
        return f"{round(value * 100)}%"
    if key == "music_gain_db":
        return f"{value:g} dB"
    if isinstance(value, bool):
        return "ha" if value else "yo'q"
    return VALUE_WORDS.get(str(value), str(value))


@dataclass(frozen=True, slots=True)
class Change:
    key: str
    before: Any
    after: Any

    @property
    def label(self) -> str:
        return f"{KEY_LABELS.get(self.key, self.key)}: {describe(self.key, self.before)} → {describe(self.key, self.after)}"


def _denoise_down(v: str) -> str:
    if v == "auto":
        return "light"
    return DENOISE_STEPS[max(0, DENOISE_STEPS.index(v) - 1)]


def _denoise_up(v: str) -> str:
    if v == "auto":
        return "medium"
    return DENOISE_STEPS[min(len(DENOISE_STEPS) - 1, DENOISE_STEPS.index(v) + 1)]


def _louder(v: str) -> str:
    i = LOUDNESS_STEPS.index("social" if v == "youtube" else v)
    return v if i == len(LOUDNESS_STEPS) - 1 else LOUDNESS_STEPS[i + 1]


def _quieter(v: str) -> str:
    i = LOUDNESS_STEPS.index("social" if v == "youtube" else v)
    return LOUDNESS_STEPS[max(0, i - 1)]


Rule = Callable[[EditDefaults], dict[str, Any]]

# code → (what the user says, what changes)
FEEDBACK_RULES: dict[str, tuple[str, Rule]] = {
    "cut_too_much": (
        "Pauzalar ko'p kesilgan, nafas yo'q",
        lambda p: {"min_pause": round(min(2.0, p.min_pause + 0.3), 2)},
    ),
    "cut_too_little": (
        "Pauzalar qolib ketgan",
        lambda p: {"min_pause": round(max(0.3, p.min_pause - 0.15), 2), "remove_pauses": True},
    ),
    "no_captions": ("Subtitr kerak emas", lambda p: {"captions": "off"}),
    "want_captions": (
        "Subtitr kerak",
        lambda p: {"captions": "dynamic" if p.captions == "off" else p.captions},
    ),
    "colour_too_strong": ("Rang juda kuchli", lambda p: {"intensity": round(max(0.0, p.intensity - 0.2), 2)}),
    "colour_too_weak": ("Rang sust", lambda p: {"intensity": round(min(1.0, p.intensity + 0.2), 2)}),
    "voice_robotic": ("Ovoz metalldek, sun'iy", lambda p: {"denoise": _denoise_down(p.denoise)}),
    "noise_left": ("Shovqin qolgan", lambda p: {"denoise": _denoise_up(p.denoise)}),
    "too_quiet": ("Ovoz past", lambda p: {"loudness": _louder(p.loudness)}),
    "too_loud": ("Ovoz baland", lambda p: {"loudness": _quieter(p.loudness)}),
    "music_too_loud": ("Musiqa baland", lambda p: {"music_gain_db": max(-40.0, p.music_gain_db - 4)}),
    "music_too_quiet": (
        "Musiqa past",
        lambda p: {"music_gain_db": min(-6.0, p.music_gain_db + 4), "music": True},
    ),
    "no_music": ("Musiqa kerak emas", lambda p: {"music": False}),
}

assert set(FEEDBACK_RULES) == set(FeedbackCode.__args__)  # type: ignore[attr-defined]


def apply_feedback(prefs: EditDefaults, codes: Iterable[FeedbackCode]) -> tuple[EditDefaults, list[Change]]:
    """Rules in the order given; a code that changes nothing (already at the
    limit) is simply not listed."""
    current = prefs
    for code in codes:
        current = current.model_copy(update=FEEDBACK_RULES[code][1](current))
    changes = [
        Change(key, getattr(prefs, key), getattr(current, key))
        for key in EDIT_KEYS
        if getattr(prefs, key) != getattr(current, key)
    ]
    return EditDefaults.model_validate(current.model_dump()), changes


# --------------------------------------------------------------------------- storage


def _user_rows_stmt(user_id: uuid.UUID):
    return select(Preference).where(
        Preference.user_id == user_id, Preference.project_id.is_(None), Preference.key.in_(EDIT_KEYS)
    )


def overlay(rows: Iterable[Preference]) -> tuple[EditDefaults, dict[str, str]]:
    values = EditDefaults().model_dump()
    sources: dict[str, str] = {}
    for row in rows:
        candidate = {**values, row.key: row.value}
        try:  # a stored value a newer release no longer accepts falls back to the default
            EditDefaults.model_validate(candidate)
        except ValueError:
            continue
        values, sources[row.key] = candidate, row.source
    return EditDefaults.model_validate(values), sources


async def effective_defaults(s: AsyncSession, user_id: uuid.UUID) -> tuple[EditDefaults, dict[str, str]]:
    return overlay((await s.execute(_user_rows_stmt(user_id))).scalars())


async def store(
    s: AsyncSession,
    user_id: uuid.UUID,
    values: dict[str, Any],
    *,
    source: str,
    feedback_id: uuid.UUID | None = None,
) -> None:
    now = utcnow()
    for key, value in values.items():
        if key not in EDIT_KEYS:
            continue
        stmt = pg_insert(Preference).values(
            id=uuid.uuid4(),
            user_id=user_id,
            project_id=None,
            scope="user",
            key=key,
            value=value,
            source=source,
            feedback_id=feedback_id,
            created_at=now,
            updated_at=now,
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[Preference.user_id, Preference.key],
                index_where=Preference.project_id.is_(None),
                set_={
                    "value": stmt.excluded.value,
                    "source": stmt.excluded.source,
                    "feedback_id": stmt.excluded.feedback_id,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )


async def remember_choice(s: AsyncSession, user_id: uuid.UUID, options: EditDefaults) -> None:
    """Only the keys that differ from what is already effective are written,
    so a feedback-made preference keeps its source until the user changes it."""
    current, _ = await effective_defaults(s, user_id)
    chosen = {k: getattr(options, k) for k in EDIT_KEYS if getattr(options, k) != getattr(current, k)}
    await store(s, user_id, chosen, source="choice")
