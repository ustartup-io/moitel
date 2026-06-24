"""Start router: /start (with/without deep-link), language selection, compliance gate.

Onboarding flow:
  /start -> language picker (new user) OR compliance gate (resumed) OR main menu
  Language pick -> compliance intro -> age -> jurisdiction -> RG -> terms -> marketing
"""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging_conf import get_logger
from db.base import ClickSource, Lang
from db.models import User
from db.repositories import UserRepository
from routers.callbacks import ComplianceCallback, LangCallback
from routers.keyboards import (
    continue_keyboard,
    jurisdiction_keyboard,
    language_keyboard,
    main_menu_keyboard,
    yes_no_keyboard,
)
from utils.compliance import is_user_compliant, user_has_any_compliance
from utils.i18n import Translator, make_translator

log = get_logger("app.router.start")

router = Router(name="start")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_payload(payload: str) -> str | None:
    """Validate a deep-link payload. Return cleaned payload or None."""
    if not payload:
        return None
    payload = payload.strip()
    if len(payload) > 64:
        return None
    if not all(c.isalnum() or c in "_-" for c in payload):
        return None
    return payload


async def _edit_or_answer(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    answer_text: str | None = None,
) -> None:
    """Edit a callback message (if accessible) and answer the callback query."""
    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=text,
            reply_markup=reply_markup,
        )
    await bot.answer_callback_query(callback.id, text=answer_text)


# --- /start -----------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(
    message: Message,
    command: CommandObject,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    """Entry point: parse deep-link, route by onboarding state."""
    if command.args:
        payload = _validate_payload(command.args)
        if payload:
            log.info("deep_link.received", payload=payload, user_id=user.id if user else None)
            # Record click attribution (source=telegram).
            from services.referral_service import ReferralService
            ref_service = ReferralService(session)
            referral = await ref_service.resolve_referral_code(payload)
            if referral:
                await ref_service.record_click(
                    referral=referral,
                    user=user,
                    source=ClickSource.telegram,
                )

    if is_user_compliant(user):
        await bot.send_message(
            chat_id=message.chat.id,
            text=t("menu.title"),
            reply_markup=main_menu_keyboard(t),
        )
    elif user_has_any_compliance(user):
        await bot.send_message(
            chat_id=message.chat.id,
            text=t("compliance.intro"),
            reply_markup=continue_keyboard(t),
        )
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=t("lang.choose"),
            reply_markup=language_keyboard(),
        )


# --- Language selection -----------------------------------------------------

@router.callback_query(LangCallback.filter(F.action == "set"))
async def handle_lang_pick(
    callback: CallbackQuery,
    callback_data: LangCallback,
    user: User | None,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Persist language choice, then show compliance intro."""
    lang_code = callback_data.code
    if lang_code not in ("en", "ru"):
        await bot.answer_callback_query(callback.id)
        return

    if user:
        repo = UserRepository(session)
        await repo.set_lang(user.id, Lang(lang_code))

    new_t = make_translator(lang_code)
    await _edit_or_answer(
        callback,
        bot,
        new_t("compliance.intro"),
        reply_markup=continue_keyboard(new_t),
        answer_text=new_t("lang.set"),
    )


# --- Compliance gate: start -> age -> jurisdiction -> RG -> terms -> marketing

@router.callback_query(ComplianceCallback.filter(F.step == "start"))
async def handle_compliance_start(callback: CallbackQuery, t: Translator, bot: Bot) -> None:
    await _edit_or_answer(callback, bot, t("compliance.age"), yes_no_keyboard("age", t))


@router.callback_query(ComplianceCallback.filter(F.step == "age"))
async def handle_compliance_age(
    callback: CallbackQuery,
    callback_data: ComplianceCallback,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    if callback_data.value == "no":
        await _edit_or_answer(callback, bot, t("compliance.blocked"))
        return
    if user:
        repo = UserRepository(session)
        await repo.set_compliance(telegram_id=user.id, age_confirmed=True)
    await _edit_or_answer(
        callback, bot, t("compliance.jurisdiction"), jurisdiction_keyboard(t)
    )


@router.callback_query(ComplianceCallback.filter(F.step == "jurisdiction"))
async def handle_compliance_jurisdiction(
    callback: CallbackQuery,
    callback_data: ComplianceCallback,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    code = callback_data.value
    if user:
        repo = UserRepository(session)
        await repo.set_compliance(telegram_id=user.id, jurisdiction_code=code)
    await _edit_or_answer(
        callback, bot, t("compliance.responsible_gambling"), yes_no_keyboard("rg", t)
    )


@router.callback_query(ComplianceCallback.filter(F.step == "rg"))
async def handle_compliance_rg(
    callback: CallbackQuery,
    callback_data: ComplianceCallback,
    settings: Settings,
    t: Translator,
    bot: Bot,
) -> None:
    if callback_data.value == "no":
        await _edit_or_answer(callback, bot, t("compliance.blocked"))
        return
    await _edit_or_answer(
        callback,
        bot,
        t("compliance.terms", landing_url=settings.landing_url),
        yes_no_keyboard("terms", t),
    )


@router.callback_query(ComplianceCallback.filter(F.step == "terms"))
async def handle_compliance_terms(
    callback: CallbackQuery,
    callback_data: ComplianceCallback,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    if callback_data.value == "no":
        await _edit_or_answer(callback, bot, t("compliance.blocked"))
        return
    if user:
        repo = UserRepository(session)
        await repo.set_compliance(telegram_id=user.id, terms_accepted=True)
    await _edit_or_answer(
        callback, bot, t("compliance.marketing"), yes_no_keyboard("marketing", t)
    )


@router.callback_query(ComplianceCallback.filter(F.step == "marketing"))
async def handle_compliance_marketing(
    callback: CallbackQuery,
    callback_data: ComplianceCallback,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    opt_in = callback_data.value == "yes"
    if user:
        repo = UserRepository(session)
        await repo.set_compliance(telegram_id=user.id, marketing_opt_in=opt_in)
    await _edit_or_answer(
        callback, bot, t("compliance.confirmed"), main_menu_keyboard(t)
    )
