"""FastAPI dependencies: database session, clients and the current user."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from synthcut_core.models import User
from synthcut_core.settings import Settings
from synthcut_storage import Storage

from .auth.tokens import TokenError, verify_access_token
from .errors import ApiError


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


DbSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]
StorageClient = Annotated[Storage, Depends(get_storage)]


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "unauthenticated", "Avtorizatsiya talab qilinadi")
    return token.strip()


async def get_current_user(request: Request, session: DbSession, settings: AppSettings) -> User:
    try:
        claims = verify_access_token(_bearer(request), settings)
    except TokenError as exc:
        raise ApiError(401, "invalid_token", "Sessiya tugagan — ilovani qayta oching") from exc
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.telegram_id != claims.telegram_id:
        raise ApiError(401, "invalid_token", "Sessiya yaroqsiz")
    # The allowlist is checked on every request so removing an id takes effect
    # immediately, not when the token expires.
    if user.telegram_id not in settings.allowed_telegram_ids:
        raise ApiError(403, "not_authorized", "Bu xususiy tizim — sizga ruxsat berilmagan")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
