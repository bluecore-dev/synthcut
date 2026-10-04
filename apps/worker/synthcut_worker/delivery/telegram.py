"""Delivery (spec §29, Phase 12): the finished video to the owner's chat.

The video itself goes up with ``sendVideo`` when it fits the bot upload limit
(the render job made a chat-sized copy when the master is larger). A video
too long even for that gets a message with a button to the Mini App, where
the full-quality file is downloadable. The bot process is not involved —
the worker talks to the Bot API directly, like notifications do.
"""

from __future__ import annotations

import json
import tempfile
from html import escape
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from synthcut_core.events import commit_and_publish_sync, emit
from synthcut_core.models import Project, Render, User, utcnow
from synthcut_core.stages import StageState, set_stage
from synthcut_media.final import TELEGRAM_LIMIT
from synthcut_schemas.enums import (
    PRESET_SPECS,
    DeliveryStatus,
    EventLevel,
    JobQueue,
    ProjectPreset,
    RenderStatus,
    Stage,
    StageStatus,
)
from synthcut_schemas.events import EventType
from synthcut_schemas.jobs import DeliverTelegramPayload, JobKind

from ..context import JobContext, PermanentError, RetryableError
from ..registry import handler
from . import notify

SOURCE = "worker"
QA_LINE = {"pass": "✅ QA: hammasi joyida", "warn": "⚠️ QA: ogohlantirish bor", "fail": "❌ QA: xato topildi"}


def caption(project_name: str, row: Render) -> str:
    spec = PRESET_SPECS.get(ProjectPreset(row.preset))
    parts = [f"🎬 <b>{escape(project_name)}</b> — v{row.plan_version}"]
    details = [f"{(row.duration_sec or 0):.0f} s"]
    if spec:
        details.append(spec.label)
    if row.size_bytes:
        details.append(f"{row.size_bytes / 1024**2:.0f} MB")
    parts.append(" · ".join(details))
    if row.qa_status:
        parts.append(QA_LINE[row.qa_status])
    if row.telegram_key:
        parts.append("Chatda siqilgan nusxa; asl sifatdagisi Mini App'da.")
    return "\n".join(parts)


def _markup(ctx: JobContext, project_id) -> dict[str, Any] | None:
    if not ctx.settings.mini_app_url.startswith("https://"):
        return None
    url = f"{ctx.settings.mini_app_url}?p={project_id}"
    return {"inline_keyboard": [[{"text": "📂 Loyihani ochish", "web_app": {"url": url}}]]}


def _result(resp: httpx.Response) -> int:
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code == 200 and data.get("ok"):
        return int(data["result"]["message_id"])
    description = str(data.get("description", ""))[:200]
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryableError(f"Telegram {resp.status_code}: {description}")
    raise PermanentError(f"Telegram {resp.status_code}: {description}")


def _send(ctx: JobContext, chat_id: int, text: str, key: str | None, row: Render) -> int:
    token = ctx.settings.telegram_bot_token.get_secret_value()
    base = f"{ctx.settings.telegram_api_base}/bot{token}"
    markup = _markup(ctx, row.project_id)
    with notify.client_factory() as client:
        try:
            if key is None:
                body: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
                if markup:
                    body["reply_markup"] = markup
                return _result(client.post(f"{base}/sendMessage", json=body))
            with tempfile.TemporaryDirectory(prefix="synthcut-deliver-") as tmp:
                path = Path(tmp) / "video.mp4"
                ctx.storage.download_file(key, path)
                if path.stat().st_size > TELEGRAM_LIMIT:
                    raise PermanentError("Fayl Telegram chegarasidan katta")
                data: dict[str, Any] = {
                    "chat_id": str(chat_id),
                    "caption": text,
                    "parse_mode": "HTML",
                    "supports_streaming": "true",
                    "duration": str(round(row.duration_sec or 0)),
                }
                if markup:
                    data["reply_markup"] = json.dumps(markup)
                with path.open("rb") as fh:
                    resp = client.post(
                        f"{base}/sendVideo",
                        data=data,
                        files={"video": ("video.mp4", fh, "video/mp4")},
                        timeout=httpx.Timeout(30, write=600, read=300),
                    )
                return _result(resp)
        except httpx.HTTPError as exc:  # the URL holds the token: never put it in the error
            raise RetryableError(f"Telegram unreachable: {type(exc).__name__}") from None


def _finish(ctx: JobContext, render_id, *, message_id: int | None, error: str | None) -> None:
    with ctx.session() as s:
        row = s.get(Render, render_id, with_for_update=True)
        if row is None:
            return
        if error is None:
            row.delivery_status = DeliveryStatus.SENT.value
            row.telegram_message_id = message_id
            row.delivered_at = utcnow()
            row.delivery_error = None
            state = StageState(StageStatus.DONE, 1.0, "Telegram chatiga yuborildi")
            event, level, text = (
                EventType.DELIVERY_SENT,
                EventLevel.INFO,
                f"v{row.plan_version} Telegramga yuborildi",
            )
        else:
            row.delivery_status = DeliveryStatus.FAILED.value
            row.delivery_error = error[:300]
            state = StageState(StageStatus.FAILED, None, error[:200])
            event, level, text = (
                EventType.DELIVERY_FAILED,
                EventLevel.ERROR,
                f"Telegramga yuborilmadi — {error[:200]}",
            )
        set_stage(s, row.project_id, Stage.DELIVERY, state, source=SOURCE)
        emit(
            s,
            project_id=row.project_id,
            type=event,
            level=level,
            message=text,
            source=SOURCE,
            data={"render_id": str(row.id)},
            job_id=ctx.job.id,
        )
        commit_and_publish_sync(s, ctx.redis)


@handler(JobKind.DELIVER_TELEGRAM, queue=JobQueue.IO)
def deliver_telegram(ctx: JobContext, payload: DeliverTelegramPayload) -> dict[str, Any]:
    with ctx.session() as s:
        found = s.execute(
            select(Render, Project.name, User.telegram_id)
            .join(Project, Project.id == Render.project_id)
            .join(User, User.id == Project.owner_id)
            .where(Render.id == payload.render_id)
        ).one_or_none()
        if found is None:
            raise PermanentError("render_missing")
        row, name, chat_id = found
        if row.project_id != ctx.job.project_id:
            raise PermanentError("render belongs to another project")
        if row.status != RenderStatus.DONE.value or row.output_key is None:
            raise PermanentError("Render hali tayyor emas")
        s.expunge(row)
    if not ctx.settings.telegram_bot_token.get_secret_value():
        _finish(ctx, row.id, message_id=None, error="Bot tokeni sozlanmagan")
        return {"skipped": "no token"}
    small = row.size_bytes is not None and row.size_bytes <= TELEGRAM_LIMIT * 0.95
    key = row.telegram_key or (row.output_key if small else None)
    text = (
        caption(name, row)
        if key
        else caption(name, row) + "\nVideo chat uchun juda uzun — Mini App'dan yuklab oling."
    )
    try:
        message_id = _send(ctx, chat_id, text, key, row)
    except PermanentError as exc:
        _finish(ctx, row.id, message_id=None, error=str(exc))
        raise
    except RetryableError as exc:
        if ctx.job.attempts >= ctx.job.max_attempts:
            _finish(ctx, row.id, message_id=None, error=str(exc))
        raise
    _finish(ctx, row.id, message_id=message_id, error=None)
    return {"message_id": message_id, "video": key is not None}
