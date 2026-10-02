"""Bot commands (spec §5): start, project creation, status, opening the Mini App.
Everything heavier happens in the Mini App."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthcut_core.events import commit_and_publish
from synthcut_core.models import User
from synthcut_core.projects import create_project, get_owned_project, list_project_summaries, project_detail
from synthcut_core.settings import Settings
from synthcut_core.users import TelegramIdentity, upsert_telegram_user
from synthcut_schemas.api import ProjectCreate

from .. import texts
from ..keyboards.web_app import open_app_keyboard, web_app_available

router = Router(name="commands")
log = logging.getLogger("synthcut.bot")


async def _authorized_user(message: Message, settings: Settings, session: AsyncSession) -> User | None:
    sender = message.from_user
    if sender is None:
        return None
    allowed = sender.id in settings.allowed_telegram_ids
    command = (message.text or "").split(maxsplit=1)[0][:32]
    log.info("command", extra={"telegram_id": sender.id, "command": command, "allowed": allowed})
    if not allowed:
        await message.answer(texts.denied(sender.id))
        return None
    user = await upsert_telegram_user(
        session,
        TelegramIdentity(
            id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
            language_code=sender.language_code,
        ),
    )
    await session.commit()
    return user


@router.message(CommandStart())
async def start(message: Message, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        if await _authorized_user(message, settings, session) is None:
            return
    text = texts.WELCOME + ("" if web_app_available(settings.mini_app_url) else texts.HTTPS_REQUIRED)
    await message.answer(text, reply_markup=open_app_keyboard(settings.mini_app_url))


@router.message(Command("help"))
async def help_(message: Message, settings: Settings) -> None:
    await message.answer(texts.HELP, reply_markup=open_app_keyboard(settings.mini_app_url))


@router.message(Command("new"))
async def new_project(
    message: Message,
    command: CommandObject,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis,
) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer(texts.NEW_USAGE)
        return
    async with sessionmaker() as session:
        user = await _authorized_user(message, settings, session)
        if user is None:
            return
        project = await create_project(session, user.id, ProjectCreate(name=name[:120]), source="bot")
        await commit_and_publish(session, redis)
        detail = await project_detail(session, project)
    await message.answer(
        texts.project_created(detail), reply_markup=open_app_keyboard(settings.mini_app_url, project.id)
    )


@router.message(Command("projects"))
async def projects(
    message: Message, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as session:
        user = await _authorized_user(message, settings, session)
        if user is None:
            return
        items = await list_project_summaries(session, user.id, limit=10)
    if not items:
        await message.answer(texts.NO_PROJECTS, reply_markup=open_app_keyboard(settings.mini_app_url))
        return
    await message.answer(
        "<b>Loyihalar</b>\n\n" + "\n\n".join(texts.project_line(p) for p in items),
        reply_markup=open_app_keyboard(settings.mini_app_url),
    )


@router.message(Command("status"))
async def status(
    message: Message, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as session:
        user = await _authorized_user(message, settings, session)
        if user is None:
            return
        items = await list_project_summaries(session, user.id, limit=1)
        if not items:
            await message.answer(texts.NO_PROJECTS, reply_markup=open_app_keyboard(settings.mini_app_url))
            return
        project = await get_owned_project(session, user.id, items[0].id)
        assert project is not None
        detail = await project_detail(session, project)
    await message.answer(
        texts.project_status(detail), reply_markup=open_app_keyboard(settings.mini_app_url, project.id)
    )
