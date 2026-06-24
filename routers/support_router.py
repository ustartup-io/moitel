"""Support router: FAQ navigation, keyword matching, escalation to admin.

Flow:
  1. User opens Support -> show FAQ categories.
  2. User picks category OR types free-text question.
  3. Bot matches FAQ -> shows answer + "Did this solve it? Yes/No".
  4. Yes -> close request. No / no match after 2 attempts -> escalate.
  5. Admin receives escalation card, can reply or close.
"""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging_conf import get_logger
from db.base import SupportState
from db.models import SupportRequest, User
from routers.callbacks import AdminCallback, MenuCallback, SupportCallback
from routers.keyboards import (
    admin_escalation_keyboard,
    main_menu_keyboard,
    support_answer_keyboard,
    support_category_keyboard,
)
from services.support_service import SupportService
from states.support import SupportStates
from utils.faq import faq_matcher
from utils.i18n import Translator

log = get_logger("app.router.support")

router = Router(name="support")


def _faq_categories(t: Translator, lang: str) -> list[str]:
    """Get localized FAQ categories."""
    faq_matcher.load()
    return faq_matcher.get_categories(lang)


# --- Menu entry: open support center ----------------------------------------

@router.callback_query(MenuCallback.filter(F.action == "support"))
async def handle_support_menu(
    callback: CallbackQuery,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
    state: FSMContext,
) -> None:
    """Open the support center with FAQ categories."""
    if user is None:
        await bot.answer_callback_query(callback.id)
        return

    await state.set_state(SupportStates.browsing)

    # Create / get support request.
    svc = SupportService(session, faq_matcher)
    await svc.get_or_create_request(user)

    categories = _faq_categories(t, str(user.lang))

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=t("support.intro"),
            reply_markup=support_category_keyboard(t, categories),
        )
    await bot.answer_callback_query(callback.id)


# --- Category selection -> show items in that category -----------------------

@router.callback_query(SupportCallback.filter(F.action == "category"))
async def handle_support_category(
    callback: CallbackQuery,
    callback_data: SupportCallback,
    user: User | None,
    t: Translator,
    bot: Bot,
    state: FSMContext,
) -> None:
    """User picked a category — show matching FAQ items as free-text prompt."""
    if user is None:
        await bot.answer_callback_query(callback.id)
        return

    await state.set_state(SupportStates.asking)
    await state.update_data(category=callback_data.category)

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=t("support.ask_question"),
        )
    await bot.answer_callback_query(callback.id)


# --- Free-text question -> FAQ match -----------------------------------------

@router.message(SupportStates.asking)
async def handle_support_question(
    message: Message,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
    state: FSMContext,
) -> None:
    """Process a free-text support question via FAQ matcher."""
    if user is None or message.text is None:
        return

    data = await state.get_data()
    category = data.get("category")

    svc = SupportService(session, faq_matcher)
    result = await svc.process_message(user, message.text, category=category)

    if result.action == "answered":
        # FAQ match found — show answer + solved? keyboard.
        await state.set_state(SupportStates.answered)
        request_id = result.request.id if result.request else 0
        await bot.send_message(
            chat_id=message.chat.id,
            text=t("support.answer_found") + "\n\n" + result.answer,
            reply_markup=support_answer_keyboard(t, request_id),
        )
    elif result.action == "escalate":
        # Threshold exceeded — escalate to admin.
        await state.set_state(SupportStates.escalated)
        await _send_admin_escalation(bot, user, result.request, t, message)
        await bot.send_message(
            chat_id=message.chat.id,
            text=t("support.escalated_to_admin", request_id=result.request.id if result.request else 0),
            reply_markup=main_menu_keyboard(t),
        )
    else:
        # No match but under threshold — ask again.
        await bot.send_message(
            chat_id=message.chat.id,
            text=t("support.no_match"),
            reply_markup=support_answer_keyboard(t, result.request.id if result.request else 0),
        )


# --- "Did this solve it?" callbacks ------------------------------------------

@router.callback_query(SupportCallback.filter(F.action == "solved"))
async def handle_support_solved(
    callback: CallbackQuery,
    callback_data: SupportCallback,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
    state: FSMContext,
) -> None:
    """User confirmed the FAQ answer solved their question."""
    request_id = int(callback_data.request_id) if callback_data.request_id else 0
    if request_id:
        svc = SupportService(session, faq_matcher)
        await svc.close_request(request_id)

    await state.clear()

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=t("support.resolved"),
            reply_markup=main_menu_keyboard(t),
        )
    await bot.answer_callback_query(callback.id)


@router.callback_query(SupportCallback.filter(F.action == "not_solved"))
async def handle_support_not_solved(
    callback: CallbackQuery,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
    state: FSMContext,
) -> None:
    """FAQ answer did not solve the question — escalate."""
    if user is None:
        await bot.answer_callback_query(callback.id)
        return

    svc = SupportService(session, faq_matcher)
    result = await svc.escalate_now(user, reason="faq_not_solved")

    await state.set_state(SupportStates.escalated)
    await _send_admin_escalation(bot, user, result.request, t, callback.message)

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=t("support.escalated_to_admin", request_id=result.request.id if result.request else 0),
            reply_markup=main_menu_keyboard(t),
        )
    await bot.answer_callback_query(callback.id)


# --- Explicit escalate -------------------------------------------------------

@router.callback_query(SupportCallback.filter(F.action == "escalate"))
async def handle_support_escalate(
    callback: CallbackQuery,
    user: User | None,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
    state: FSMContext,
) -> None:
    """User explicitly requested admin contact."""
    if user is None:
        await bot.answer_callback_query(callback.id)
        return

    svc = SupportService(session, faq_matcher)
    result = await svc.escalate_now(user, reason="user_requested")

    await state.set_state(SupportStates.escalated)
    await _send_admin_escalation(bot, user, result.request, t, callback.message)

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=t("support.escalated_to_admin", request_id=result.request.id if result.request else 0),
            reply_markup=main_menu_keyboard(t),
        )
    await bot.answer_callback_query(callback.id)


# --- Admin: close request ----------------------------------------------------

@router.callback_query(AdminCallback.filter(F.action == "close"))
async def handle_admin_close(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    session: AsyncSession,
    settings: Settings,
    t: Translator,
    bot: Bot,
) -> None:
    """Admin closes a support request."""
    request_id = int(callback_data.request_id) if callback_data.request_id else 0
    svc = SupportService(session, faq_matcher)
    request = await svc.close_request(request_id)

    if request:
        # Notify the user.
        await bot.send_message(
            chat_id=request.user_id,
            text=t("support.closed_notice"),
        )

    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=f"✅ Request #{request_id} closed.",
        )
    await bot.answer_callback_query(callback.id, text="Closed")


# --- Admin: reply to escalation (via reply to bot message) -------------------

@router.message(Command("reply"))
async def handle_admin_reply(
    message: Message,
    settings: Settings,
    bot: Bot,
    state: FSMContext,
) -> None:
    """Admin replies to a user via /reply <request_id> <message>.

    Only the admin chat can use this.
    """
    if message.chat.id != settings.admin_chat_id:
        return

    # Parse /reply <request_id> <message text>
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await bot.send_message(
            chat_id=message.chat.id,
            text="Usage: /reply <request_id> <message>",
        )
        return

    try:
        request_id = int(parts[1])
    except ValueError:
        await bot.send_message(chat_id=message.chat.id, text="Invalid request ID.")
        return

    reply_text = parts[2]

    from db.session import get_session
    from services.support_service import SupportService as Svc
    async with get_session() as session:
        svc = Svc(session, faq_matcher)
        request = await svc.get_by_id(request_id)
        if request is None:
            await bot.send_message(
                chat_id=message.chat.id, text=f"Request #{request_id} not found."
            )
            return

        # Relay the reply to the user.
        await bot.send_message(
            chat_id=request.user_id,
            text=f"💬 Admin: {reply_text}",
        )
        request.last_message = reply_text[:500]
        request.state = SupportState.answered
        await session.commit()

    await bot.send_message(
        chat_id=message.chat.id,
        text=f"✅ Reply sent to user (request #{request_id}).",
    )


# --- Helper: send admin escalation card --------------------------------------

async def _send_admin_escalation(
    bot: Bot,
    user: User,
    request: SupportRequest | None,
    t: Translator,
    original_msg: object,
) -> None:
    """Send a structured escalation card to the admin chat."""
    if request is None:
        return

    from app.config import get_settings
    settings = get_settings()

    card_text = (
        f"🔔 New escalation\n"
        f"User: {user.id}\n"
        f"Lang: {user.lang}\n"
        f"Request: #{request.id}\n"
        f"State: {request.state}\n"
        f"Message: {request.last_message or '(none)'}\n"
    )

    try:
        await bot.send_message(
            chat_id=settings.admin_chat_id,
            text=card_text,
            reply_markup=admin_escalation_keyboard(request.id),
        )
    except Exception:
        log.error("support.admin_notify_failed", exc_info=True)
