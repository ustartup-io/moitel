"""Referral router: user sees their referral link + simple stats."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from db.models import User
from routers.callbacks import MenuCallback
from routers.keyboards import main_menu_keyboard
from services.referral_service import ReferralService
from utils.i18n import Translator

log = get_logger("app.router.referral")

router = Router(name="referral")


@router.callback_query(MenuCallback.filter(F.action == "referral"))
async def handle_referral_menu(
    callback: CallbackQuery,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    """Show the user's referral link and stats."""
    if user is None:
        await bot.answer_callback_query(callback.id)
        return

    ref_service = ReferralService(session)
    referral = await ref_service.get_or_create_for_user(user)
    link = ref_service.build_deep_link(referral)
    stats = await ref_service.get_user_stats(user)

    text = (
        t("referral.your_link", link=link)
        + "\n\n"
        + t(
            "referral.stats",
            referrals=stats["referrals"],
            clicks=stats["clicks"],
            conversions=stats["conversions"],
        )
    )

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=text,
            reply_markup=main_menu_keyboard(t),
        )
    await bot.answer_callback_query(callback.id)
