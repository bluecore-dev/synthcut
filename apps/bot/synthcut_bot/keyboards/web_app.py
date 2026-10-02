from __future__ import annotations

import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from ..texts import OPEN_APP, OPEN_PROJECT


def web_app_available(base_url: str) -> bool:
    # Telegram rejects web_app buttons whose URL is not HTTPS — and then the
    # whole message fails, so the bot would not answer at all.
    return base_url.startswith("https://")


def open_app_keyboard(base_url: str, project_id: uuid.UUID | None = None) -> InlineKeyboardMarkup | None:
    if not web_app_available(base_url):
        return None
    url = base_url if project_id is None else f"{base_url}?p={project_id}"
    text = OPEN_APP if project_id is None else OPEN_PROJECT
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )
