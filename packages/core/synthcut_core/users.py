"""Users are Telegram identities (spec §39-40). The allowlist decides who may
use this private deployment; the table is already multi-user (spec rule 17)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User, utcnow


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


def is_authorized(telegram_id: int, allowlist: frozenset[int]) -> bool:
    return telegram_id in allowlist


async def upsert_telegram_user(session: AsyncSession, identity: TelegramIdentity) -> User:
    user = (
        await session.execute(select(User).where(User.telegram_id == identity.id).with_for_update())
    ).scalar_one_or_none()
    now = utcnow()
    if user is None:
        user = User(telegram_id=identity.id, created_at=now, updated_at=now)
        session.add(user)
    user.username = identity.username
    user.first_name = identity.first_name
    user.last_name = identity.last_name
    user.language_code = identity.language_code
    if identity.photo_url:
        user.photo_url = identity.photo_url
    user.last_seen_at = now
    await session.flush()
    return user
