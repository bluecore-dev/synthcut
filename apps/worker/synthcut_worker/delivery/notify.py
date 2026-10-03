"""Telegram notifications (spec §5): the worker talks to the Bot API directly;
the bot process only receives updates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from synthcut_schemas.enums import JobQueue
from synthcut_schemas.jobs import JobKind, NotifyTelegramPayload

from ..context import JobContext, PermanentError, RetryableError
from ..registry import handler

# Replaced in tests with a client on httpx.MockTransport.
client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=15)  # noqa: E731


@handler(JobKind.NOTIFY_TELEGRAM, queue=JobQueue.IO)
def notify_telegram(ctx: JobContext, payload: NotifyTelegramPayload) -> dict[str, Any]:
    settings = ctx.settings
    token = settings.telegram_bot_token.get_secret_value()
    if not settings.notify_telegram or not token:
        return {"skipped": "notifications disabled"}
    body: dict[str, Any] = {
        "chat_id": payload.chat_id,
        "text": payload.text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if payload.open_project_id and settings.mini_app_url.startswith("https://"):
        url = f"{settings.mini_app_url}?p={payload.open_project_id}"
        body["reply_markup"] = {
            "inline_keyboard": [[{"text": "📂 Loyihani ochish", "web_app": {"url": url}}]]
        }
    with client_factory() as client:
        try:
            resp = client.post(f"{settings.telegram_api_base}/bot{token}/sendMessage", json=body)
        except httpx.HTTPError as exc:  # the URL holds the token: never put it in the error
            raise RetryableError(f"Telegram unreachable: {type(exc).__name__}") from None
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code == 200 and data.get("ok"):
        return {"message_id": data["result"]["message_id"]}
    description = str(data.get("description", ""))[:200]
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryableError(f"Telegram {resp.status_code}: {description}")
    raise PermanentError(f"Telegram {resp.status_code}: {description}")
