"""Short-lived access tokens issued after initData validation.

initData is exchanged once; afterwards requests carry a signed token. This
keeps multi-hour uploads working after the initData's freshness window has
passed, and the token is refreshed while the Mini App stays open.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from synthcut_core.settings import Settings

ISSUER = "synthcut"
ALGORITHM = "HS256"


class TokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    telegram_id: int
    expires_at: datetime


def _secret(settings: Settings) -> str:
    secret = settings.session_secret.get_secret_value()
    if len(secret) < 32:
        raise TokenError("SESSION_SECRET must be at least 32 characters")
    return secret


def issue_access_token(user_id: uuid.UUID, telegram_id: int, settings: Settings) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=settings.access_token_ttl_seconds)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "tg": telegram_id,
            "typ": "access",
            "iss": ISSUER,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": uuid.uuid4().hex,
        },
        _secret(settings),
        algorithm=ALGORITHM,
    )
    return token, expires


def verify_access_token(token: str, settings: Settings) -> AccessClaims:
    try:
        claims = jwt.decode(
            token,
            _secret(settings),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims.get("typ") != "access":
        raise TokenError("not an access token")
    try:
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            telegram_id=int(claims["tg"]),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed claims") from exc
