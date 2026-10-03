"""Queue a Telegram message to a project's owner from inside a stage's
transaction — it is sent only if that transaction commits."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session
from synthcut_core.jobs import enqueue
from synthcut_core.models import Project, User
from synthcut_schemas.enums import JobPriority, JobQueue
from synthcut_schemas.jobs import JobKind


def notify_owner(
    s: Session,
    project_id: uuid.UUID,
    *,
    text: Callable[[str], str],
    idempotency_key: str,
) -> None:
    """``text`` gets the HTML-escaped project name and returns the message."""
    row = s.execute(
        select(Project.name, User.telegram_id)
        .join(User, User.id == Project.owner_id)
        .where(Project.id == project_id)
    ).one_or_none()
    if row is None:
        return
    enqueue(
        s,
        kind=JobKind.NOTIFY_TELEGRAM,
        queue=JobQueue.IO,
        priority=JobPriority.HIGH,
        payload={
            "chat_id": row.telegram_id,
            "text": text(escape(row.name)),
            "open_project_id": str(project_id),
        },
        project_id=project_id,
        idempotency_key=idempotency_key,
        max_attempts=4,
    )
