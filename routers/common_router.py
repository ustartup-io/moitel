"""Common router: /help command, main menu callback entries (stubs for later steps)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.logging_conf import get_logger
from routers.callbacks import MenuCallback
from routers.keyboards import main_menu_keyboard
from utils.i18n import Translator

log = get_logger("app.router.common")

router = Router(name="common")


@router.message(Command("help"))
async def cmd_help(
    message: Message,
    settings: Settings,
    t: Translator,
    bot: Bot,
) -> None:
    """Show help text with landing-page link."""
    await bot.send_message(
        chat_id=message.chat.id,
        text=t("help.body", landing_url=settings.landing_url),
        reply_markup=main_menu_keyboard(t),
    )


@router.callback_query(MenuCallback.filter(F.action == "catalog"))
async def handle_menu_catalog(
    callback: CallbackQuery,
    t: Translator,
    bot: Bot,
) -> None:
    """Catalog entry point (stub — full logic in Step 5)."""
    await bot.answer_callback_query(callback.id, text=t("stub.not_ready"))


@router.callback_query(MenuCallback.filter(F.action == "referral"))
async def handle_menu_referral(
    callback: CallbackQuery,
    t: Translator,
    bot: Bot,
) -> None:
    """Referral entry point (stub — full logic in Step 4)."""
    await bot.answer_callback_query(callback.id, text=t("stub.not_ready"))


@router.callback_query(MenuCallback.filter(F.action == "support"))
async def handle_menu_support(
    callback: CallbackQuery,
    t: Translator,
    bot: Bot,
) -> None:
    """Support entry point (stub — full logic in Step 6)."""
    await bot.answer_callback_query(callback.id, text=t("stub.not_ready"))
