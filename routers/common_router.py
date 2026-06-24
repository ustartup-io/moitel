"""Common router: /help, catalog (with compliance gate), menu:back handler."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging_conf import get_logger
from db.models import Offer, User
from routers.callbacks import MenuCallback, OfferCallback
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
    user: User | None,
    is_compliant: bool,
    session: AsyncSession,
    t: Translator,
    bot: Bot,
) -> None:
    """Show the offer catalog — only if user passed the compliance gate."""
    if not is_compliant:
        # DEFECT FIX 2: compliance gate precedes any offer access.
        msg = callback.message
        if msg is not None:
            await bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text=t("catalog.not_compliant"),
                reply_markup=main_menu_keyboard(t),
            )
        await bot.answer_callback_query(callback.id)
        return

    # Fetch active offers.
    from db.repositories import OfferRepository
    offer_repo = OfferRepository(session)
    offers = await offer_repo.get_active()

    msg = callback.message
    if not offers:
        if msg is not None:
            await bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text=t("catalog.empty"),
                reply_markup=main_menu_keyboard(t),
            )
        await bot.answer_callback_query(callback.id)
        return

    # Display first active offer (MVP: one offer at a time).
    offer = offers[0]
    if offer.requires_payment and offer.price_amount:
        text = t(
            "catalog.paid_offer",
            title=offer.title_key,
            amount=offer.price_amount,
            currency=offer.price_currency or "USDT",
        )
    else:
        text = t("catalog.offer_item", title=offer.title_key, url=offer.base_url)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("catalog.view_offer"),
        callback_data=OfferCallback(action="view", offer_id=str(offer.id)),
    )
    kb.button(text=t("common.back"), callback_data=MenuCallback(action="back"))
    kb.adjust(1)

    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=text,
            reply_markup=kb.as_markup(),
        )
    await bot.answer_callback_query(callback.id)


@router.callback_query(OfferCallback.filter(F.action == "view"))
async def handle_offer_view(
    callback: CallbackQuery,
    callback_data: OfferCallback,
    user: User | None,
    is_compliant: bool,
    session: AsyncSession,
    settings: Settings,
    t: Translator,
    bot: Bot,
) -> None:
    """Handle offer view: record click, show link or trigger payment."""
    if not is_compliant:
        await bot.answer_callback_query(callback.id, text=t("catalog.not_compliant"))
        return

    from db.repositories import OfferRepository
    offer_repo = OfferRepository(session)
    offer = await offer_repo.get_by_code(callback_data.offer_id) or await session.get(
        Offer, int(callback_data.offer_id)
    )
    if offer is None:
        await bot.answer_callback_query(callback.id, text=t("stub.not_ready"))
        return

    if offer.requires_payment:
        # Paid path: trigger payment flow.
        if user is None:
            await bot.answer_callback_query(callback.id)
            return
        from services.payment_service import PaymentService
        from services.xrocket_client import MockXRocketClient
        pay_service = PaymentService(session, xrocket_client=MockXRocketClient())
        result = await pay_service.create_invoice(user=user, offer=offer)
        if result.status == "error":
            await bot.answer_callback_query(callback.id, text=result.reason)
            return
        pay_url = result.pay_url or settings.landing_url
        text = t(
            "payment.invoice_created",
            pay_url=pay_url,
            amount=offer.price_amount or 0,
            currency=offer.price_currency or "USDT",
        )
        msg = callback.message
        if msg is not None:
            await bot.edit_message_text(
                chat_id=msg.chat.id, message_id=msg.message_id, text=text,
                reply_markup=main_menu_keyboard(t),
            )
    else:
        # Affiliate path: record click + show link.
        from db.base import ClickSource
        from db.repositories import ClickRepository
        click_repo = ClickRepository(session)
        await click_repo.create(
            offer_id=offer.id, user_id=user.id if user else None,
            source=ClickSource.telegram,
        )
        text = t("offer.view", url=offer.base_url)
        msg = callback.message
        if msg is not None:
            await bot.edit_message_text(
                chat_id=msg.chat.id, message_id=msg.message_id, text=text,
                reply_markup=main_menu_keyboard(t),
            )
    await bot.answer_callback_query(callback.id)


@router.callback_query(MenuCallback.filter(F.action == "referral"))
async def handle_menu_referral(
    callback: CallbackQuery,
    t: Translator,
    bot: Bot,
) -> None:
    """Referral entry point (handled by referral_router — this is a fallback)."""
    await bot.answer_callback_query(callback.id, text=t("stub.not_ready"))


@router.callback_query(MenuCallback.filter(F.action == "support"))
async def handle_menu_support(
    callback: CallbackQuery,
    t: Translator,
    bot: Bot,
) -> None:
    """Support entry point (handled by support_router — this is a fallback)."""
    await bot.answer_callback_query(callback.id, text=t("stub.not_ready"))


# DEFECT FIX 5: menu:back handler
@router.callback_query(MenuCallback.filter(F.action == "back"))
async def handle_menu_back(
    callback: CallbackQuery,
    t: Translator,
    bot: Bot,
) -> None:
    """Back button returns to main menu."""
    msg = callback.message
    if msg is not None:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=t("menu.title"),
            reply_markup=main_menu_keyboard(t),
        )
    await bot.answer_callback_query(callback.id)
