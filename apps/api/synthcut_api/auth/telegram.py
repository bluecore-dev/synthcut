"""Telegram Mini App ``initData`` validation (spec §39).

The raw ``initData`` string is verified server-side with the bot token:
``secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`` and
``hash = HMAC_SHA256(key=secret, msg=data_check_string)`` where the data-check
string is every received field except ``hash``, sorted and joined by ``\\n``.
``initDataUnsafe`` from the client is never trusted.

Since Bot API 8.0 initData also carries an Ed25519 ``signature`` field for
third-party validation. Telegram's documents are ambiguous about whether it is
part of the HMAC'd string, so both canonical forms are accepted — that is safe
because forging either still requires the bot token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl

from synthcut_core.users import TelegramIdentity

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_CLOCK_SKEW_SECONDS = 300


class InitDataError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class InitData:
    user: TelegramIdentity
    auth_date: datetime
    query_id: str | None
    start_param: str | None
    chat_type: str | None


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def _check_hash(secret: bytes, fields: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    return hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a valid initData string (tests and local tooling)."""
    from urllib.parse import urlencode

    digest = _check_hash(_secret_key(bot_token), fields)
    return urlencode({**fields, "hash": digest})


def validate_init_data(
    raw: str, bot_token: str, *, max_age_seconds: int, now: float | None = None
) -> InitData:
    if not bot_token:
        raise InitDataError("not_configured", "bot token is not configured")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("malformed", "initData is not a query string") from exc
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InitDataError("malformed", "duplicate keys in initData")

    received = fields.pop("hash", "")
    if not _HASH_RE.fullmatch(received):
        raise InitDataError("missing_hash", "initData has no valid hash")

    secret = _secret_key(bot_token)
    valid = hmac.compare_digest(_check_hash(secret, fields), received)
    if not valid and "signature" in fields:
        without_signature = {k: v for k, v in fields.items() if k != "signature"}
        valid = hmac.compare_digest(_check_hash(secret, without_signature), received)
    if not valid:
        raise InitDataError("bad_hash", "initData hash does not match")

    try:
        auth_ts = int(fields["auth_date"])
    except (KeyError, ValueError) as exc:
        raise InitDataError("malformed", "auth_date missing") from exc
    current = time.time() if now is None else now
    if current - auth_ts > max_age_seconds:
        raise InitDataError("expired", "initData is too old; reopen the Mini App")
    if auth_ts - current > MAX_CLOCK_SKEW_SECONDS:
        raise InitDataError("expired", "initData is from the future")

    try:
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InitDataError("malformed", "user missing from initData") from exc

    return InitData(
        user=TelegramIdentity(
            id=user_id,
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            language_code=user.get("language_code"),
            photo_url=user.get("photo_url"),
        ),
        auth_date=datetime.fromtimestamp(auth_ts, UTC),
        query_id=fields.get("query_id"),
        start_param=fields.get("start_param"),
        chat_type=fields.get("chat_type"),
    )
