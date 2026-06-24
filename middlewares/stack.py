"""Middleware pipeline registered on the Dispatcher in a fixed order.

Order (outer to inner):
  1. ErrorMiddleware      — catch unhandled, log + alert admin + show error text
  2. ContextMiddleware    — inject settings/logger, bind correlation fields
  3. DbSessionMiddleware  — open async session per update, commit/rollback
  4. UserUpsertMiddleware — upsert user by telegram_id
  5. LanguageMiddleware   — resolve lang, expose t()
  6. ThrottleMiddleware   — per-user token-bucket rate limit
  7. AdminMiddleware      — flag is_admin
  8. ComplianceMiddleware — flag is_compliant (soft-redirect handled in routers)

Middlewares are registered on dp.update.outer_middleware so they wrap the
entire update-processing chain (routing + handler).
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject, Update

from app.config import Settings, get_settings
from app.logging_conf import alert_admin, bind_correlation, clear_correlation, get_logger
from db.base import Lang
from db.models import User
from db.repositories import UserRepository
from db.session import get_session
from utils.compliance import is_user_compliant
from utils.i18n import SUPPORTED_LANGS, i18n, make_translator

log = get_logger("app.middleware")

# Type alias for the handler callable.
Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


# ---------------------------------------------------------------------------
# Helpers — extract user/chat info from a raw Update
# ---------------------------------------------------------------------------

def _get_tg_user(update: Update) -> Any:
    """Extract the telegram User object from an Update, or None."""
    obj = (
        update.message
        or update.edited_message
        or update.callback_query
        or update.channel_post
        or update.edited_channel_post
    )
    if obj is None:
        return None
    return getattr(obj, "from_user", None)


def _get_chat_id(update: Update) -> int | None:
    """Extract the chat_id from an Update, or None."""
    obj = (
        update.message
        or update.edited_message
        or update.callback_query
        or update.channel_post
        or update.edited_channel_post
    )
    if obj is None:
        return None
    chat = getattr(obj, "chat", None)
    return chat.id if chat else None


# ---------------------------------------------------------------------------
# 1. ErrorMiddleware
# ---------------------------------------------------------------------------

class ErrorMiddleware(BaseMiddleware):
    """Outermost: catch all unhandled exceptions."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            update = event if isinstance(event, Update) else None
            chat_id = _get_chat_id(update) if update else None
            tg_user = _get_tg_user(update) if update else None
            log.error(
                "unhandled.error",
                error=str(exc),
                chat_id=chat_id,
                tg_user_id=getattr(tg_user, "id", None),
                exc_info=True,
            )
            alert_admin("Unhandled error", error=str(exc), chat_id=chat_id)
            # Best-effort user notification.
            bot = data.get("bot")
            if bot and chat_id:
                lang = data.get("lang", "en")
                with suppress(Exception):
                    await bot.send_message(chat_id, i18n.t("error.generic", lang))
            return None


# ---------------------------------------------------------------------------
# 2. ContextMiddleware
# ---------------------------------------------------------------------------

class ContextMiddleware(BaseMiddleware):
    """Inject settings + logger; bind correlation fields."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        clear_correlation()
        settings = get_settings()
        update = event if isinstance(event, Update) else None
        update_id = getattr(update, "update_id", None) if update else None
        tg_user = _get_tg_user(update) if update else None
        user_id = getattr(tg_user, "id", None) if tg_user else None

        bind_correlation(update_id=update_id, user_id=user_id)
        data["settings"] = settings
        data["logger"] = get_logger("app.handler").bind(update_id=update_id, user_id=user_id)
        return await handler(event, data)


# ---------------------------------------------------------------------------
# 3. DbSessionMiddleware
# ---------------------------------------------------------------------------

class DbSessionMiddleware(BaseMiddleware):
    """Open an async session per update; commit on success, rollback on error."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with get_session() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


# ---------------------------------------------------------------------------
# 4. UserUpsertMiddleware
# ---------------------------------------------------------------------------

class UserUpsertMiddleware(BaseMiddleware):
    """Upsert user by telegram_id; attach DB user + telegram user to data."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        session = data.get("session")
        tg_user = _get_tg_user(event) if isinstance(event, Update) else None
        if tg_user and session:
            repo = UserRepository(session)
            user = await repo.get_by_telegram_id(tg_user.id)
            is_new = user is None
            if is_new:
                settings = data.get("settings") or get_settings()
                user = await repo.create(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    lang=Lang(settings.default_lang),
                )
            data["user"] = user
            data["is_new_user"] = is_new
            data["from_user"] = tg_user
        else:
            data["user"] = None
            data["is_new_user"] = False
        return await handler(event, data)


# ---------------------------------------------------------------------------
# 5. LanguageMiddleware
# ---------------------------------------------------------------------------

class LanguageMiddleware(BaseMiddleware):
    """Resolve lang from user (fallback DEFAULT_LANG); expose t()."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("user")
        settings: Settings = data.get("settings") or get_settings()
        lang = str(user.lang) if user else settings.default_lang
        if lang not in SUPPORTED_LANGS:
            lang = "en"
        data["lang"] = lang
        data["t"] = make_translator(lang)
        return await handler(event, data)


# ---------------------------------------------------------------------------
# 6. ThrottleMiddleware
# ---------------------------------------------------------------------------

class ThrottleMiddleware(BaseMiddleware):
    """Simple per-user token-bucket rate limiter."""

    def __init__(self, rate: float = 0.5, burst: int = 10) -> None:
        self._rate = rate
        self._burst = burst
        self._buckets: dict[int, tuple[float, float]] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        update = event if isinstance(event, Update) else None
        tg_user = _get_tg_user(update) if update else None
        if tg_user is None:
            return await handler(event, data)

        uid = tg_user.id
        now = time.monotonic()
        tokens, last = self._buckets.get(uid, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)

        if tokens < 1.0:
            bot = data.get("bot")
            chat_id = _get_chat_id(update) if update else None
            lang = data.get("lang", "en")
            if bot and chat_id:
                with suppress(Exception):
                    await bot.send_message(chat_id, i18n.t("throttle.slow_down", lang))
            return None

        self._buckets[uid] = (tokens - 1.0, now)
        return await handler(event, data)


# ---------------------------------------------------------------------------
# 7. AdminMiddleware
# ---------------------------------------------------------------------------

class AdminMiddleware(BaseMiddleware):
    """Flag is_admin when chat_id == ADMIN_CHAT_ID."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        settings: Settings = data.get("settings") or get_settings()
        update = event if isinstance(event, Update) else None
        chat_id = _get_chat_id(update) if update else None
        data["is_admin"] = chat_id == settings.admin_chat_id
        return await handler(event, data)


# ---------------------------------------------------------------------------
# 8. ComplianceMiddleware
# ---------------------------------------------------------------------------

class ComplianceMiddleware(BaseMiddleware):
    """Flag is_compliant. Soft-redirect logic is handled in routers."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("user")
        data["is_compliant"] = is_user_compliant(user)
        return await handler(event, data)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_middlewares(dp: Dispatcher) -> None:
    """Register all middlewares on the Dispatcher in the required order."""
    dp.update.outer_middleware(ErrorMiddleware())
    dp.update.outer_middleware(ContextMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserUpsertMiddleware())
    dp.update.outer_middleware(LanguageMiddleware())
    dp.update.outer_middleware(ThrottleMiddleware())
    dp.update.outer_middleware(AdminMiddleware())
    dp.update.outer_middleware(ComplianceMiddleware())
