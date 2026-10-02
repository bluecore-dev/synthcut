from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from synthcut_core.users import upsert_telegram_user
from synthcut_schemas.api import AuthResponse, ErrorResponse, MeOut, TelegramAuthRequest, UserOut

from ..deps import AppSettings, CurrentUser, DbSession, RedisClient, StorageClient, client_ip
from ..errors import ApiError
from ..ratelimit import rate_limit
from ..uploads.service import UploadService
from .telegram import InitDataError, validate_init_data
from .tokens import issue_access_token

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"], responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}})


@router.post("/auth/telegram", response_model=AuthResponse)
async def telegram_login(
    body: TelegramAuthRequest, request: Request, db: DbSession, settings: AppSettings, redis: RedisClient
) -> AuthResponse:
    """Exchange Mini App initData (validated server-side) for an access token."""
    await rate_limit(redis, f"auth:{client_ip(request)}", limit=30, window_seconds=60)
    try:
        init = validate_init_data(
            body.init_data,
            settings.telegram_bot_token.get_secret_value(),
            max_age_seconds=settings.init_data_max_age_seconds,
        )
    except InitDataError as exc:
        log.warning("initData rejected", extra={"reason": exc.code})
        raise ApiError(
            401, "invalid_init_data", "Telegram ma'lumotlari tasdiqlanmadi", {"reason": exc.code}
        ) from exc
    if init.user.id not in settings.allowed_telegram_ids:
        log.warning("telegram user not on allowlist", extra={"telegram_id": init.user.id})
        raise ApiError(
            403,
            "not_authorized",
            "Bu xususiy tizim — sizga ruxsat berilmagan",
            {"telegram_id": init.user.id},
        )
    user = await upsert_telegram_user(db, init.user)
    await db.commit()
    token, expires_at = issue_access_token(user.id, user.telegram_id, settings)
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserOut.model_validate(user))


@router.post("/auth/refresh", response_model=AuthResponse)
async def refresh(user: CurrentUser, settings: AppSettings) -> AuthResponse:
    """Sliding session: a valid token buys a fresh one while the app is open."""
    token, expires_at = issue_access_token(user.id, user.telegram_id, settings)
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut)
async def me(
    user: CurrentUser, db: DbSession, storage: StorageClient, settings: AppSettings, redis: RedisClient
) -> MeOut:
    limits = await UploadService(db, storage, settings, redis).limits()
    return MeOut(user=UserOut.model_validate(user), limits=limits)
