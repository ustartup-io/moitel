"""Admin router: stats, offer management, manual confirms, broadcasts, health.

All commands guarded by chat_id == ADMIN_CHAT_ID.
Every state-changing action writes admin_audit_logs.
"""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging_conf import get_logger
from db.base import ConversionStatus, OfferKind
from services.admin_service import AdminService
from services.broadcast_service import BroadcastService

log = get_logger("app.router.admin")

router = Router(name="admin")


def _is_admin(message: Message, settings: Settings) -> bool:
    """Guard: only the admin chat can use these commands."""
    return message.chat.id == settings.admin_chat_id


# --- /stats ------------------------------------------------------------------

@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Show dashboard stats."""
    if not _is_admin(message, settings):
        return

    svc = AdminService(session)
    stats = await svc.get_dashboard_stats()

    text = (
        f"📊 <b>Dashboard Stats</b>\n\n"
        f"👥 Users: {stats['users']}\n"
        f"🖱 Clicks: {stats['clicks']}\n"
        f"🔄 Conversions: {stats['conversions']['total']}\n"
        f"   ✅ Approved: {stats['conversions']['approved']}\n"
        f"   ⏳ Pending: {stats['conversions']['pending']}\n"
        f"💸 Paid payments: {stats['paid_payments']}\n"
        f"📦 Delivered: {stats['delivered']}\n"
        f"📋 Active offers: {stats['active_offers']}\n"
    )
    await bot.send_message(chat_id=message.chat.id, text=text)


# --- /offers -----------------------------------------------------------------

@router.message(Command("offers"))
async def cmd_offers(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """List all offers."""
    if not _is_admin(message, settings):
        return

    svc = AdminService(session)
    offers = await svc.list_offers()

    if not offers:
        await bot.send_message(chat_id=message.chat.id, text="No offers yet.")
        return

    lines = ["📋 <b>Offers</b>\n"]
    for o in offers:
        status = "✅" if o.is_active else "⛔"
        kind = "paid" if o.requires_payment else "free"
        price = f" {o.price_amount} {o.price_currency}" if o.price_amount else ""
        lines.append(
            f"{status} <b>{o.code}</b> (id:{o.id}) [{kind}{price}]\n"
            f"   {o.base_url}"
        )
    await bot.send_message(chat_id=message.chat.id, text="\n".join(lines))


# --- /offer_add --------------------------------------------------------------

@router.message(Command("offer_add"))
async def cmd_offer_add(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Add an offer: /offer_add <code> <title_key> <base_url> [paid] [amount] [currency]."""
    if not _is_admin(message, settings):
        return

    parts = (message.text or "").split()
    if len(parts) < 4:
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "Usage: /offer_add <code> <title_key> <base_url> [paid] [amount] [currency]\n"
                "Example: /offer_add WELCOME offer.welcome https://x.com\n"
                "Example: /offer_add PRO offer.pro https://x.com paid 1000 USDT"
            ),
        )
        return

    code = parts[1]
    title_key = parts[2]
    base_url = parts[3]
    requires_payment = len(parts) > 4 and parts[4].lower() == "paid"
    price_amount = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else None
    price_currency = parts[6] if len(parts) > 6 else "USDT"

    svc = AdminService(session)
    try:
        kind = OfferKind.paid_access if requires_payment else OfferKind.affiliate_link
        offer = await svc.add_offer(
            admin_id=settings.admin_chat_id,
            code=code,
            title_key=title_key,
            base_url=base_url,
            kind=kind,
            requires_payment=requires_payment,
            price_amount=price_amount,
            price_currency=price_currency,
        )
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Offer added: {offer.code} (id:{offer.id})",
        )
    except Exception as exc:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"❌ Error: {exc}",
        )


# --- /offer_toggle -----------------------------------------------------------

@router.message(Command("offer_toggle"))
async def cmd_offer_toggle(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Toggle an offer's active status: /offer_toggle <id>."""
    if not _is_admin(message, settings):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await bot.send_message(
            chat_id=message.chat.id,
            text="Usage: /offer_toggle <offer_id>",
        )
        return

    try:
        offer_id = int(parts[1])
    except ValueError:
        await bot.send_message(chat_id=message.chat.id, text="Invalid ID.")
        return

    svc = AdminService(session)
    offer = await svc.toggle_offer(admin_id=settings.admin_chat_id, offer_id=offer_id)
    if offer is None:
        await bot.send_message(chat_id=message.chat.id, text="Offer not found.")
    else:
        status = "active" if offer.is_active else "disabled"
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Offer {offer.code} is now {status}.",
        )


# --- /confirm_payment --------------------------------------------------------

@router.message(Command("confirm_payment"))
async def cmd_confirm_payment(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Manually confirm a payment: /confirm_payment <id>."""
    if not _is_admin(message, settings):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await bot.send_message(
            chat_id=message.chat.id,
            text="Usage: /confirm_payment <payment_id>",
        )
        return

    try:
        payment_id = int(parts[1])
    except ValueError:
        await bot.send_message(chat_id=message.chat.id, text="Invalid ID.")
        return

    svc = AdminService(session)
    payment = await svc.manual_confirm_payment(
        admin_id=settings.admin_chat_id, payment_id=payment_id
    )
    if payment is None:
        await bot.send_message(chat_id=message.chat.id, text="Payment not found.")
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Payment {payment.id} confirmed (status: {payment.status}).",
        )


# --- /confirm_conversion -----------------------------------------------------

@router.message(Command("confirm_conversion"))
async def cmd_confirm_conversion(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Manually approve/reject a conversion: /confirm_conversion <id> [approve|reject]."""
    if not _is_admin(message, settings):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await bot.send_message(
            chat_id=message.chat.id,
            text="Usage: /confirm_conversion <id> [approve|reject]",
        )
        return

    try:
        conversion_id = int(parts[1])
    except ValueError:
        await bot.send_message(chat_id=message.chat.id, text="Invalid ID.")
        return

    action = parts[2] if len(parts) > 2 else "approve"
    status = ConversionStatus.approved if action != "reject" else ConversionStatus.rejected

    svc = AdminService(session)
    conversion = await svc.manual_confirm_conversion(
        admin_id=settings.admin_chat_id,
        conversion_id=conversion_id,
        status=status,
    )
    if conversion is None:
        await bot.send_message(chat_id=message.chat.id, text="Conversion not found.")
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Conversion {conversion.id} {status}.",
        )


# --- /health -----------------------------------------------------------------

@router.message(Command("health"))
async def cmd_health(
    message: Message,
    settings: Settings,
    bot: Bot,
) -> None:
    """Show system health: jobs, DB ping, webhook status."""
    if not _is_admin(message, settings):
        return

    # DB ping.
    from sqlalchemy import text as sa_text

    from db.session import get_engine

    db_ok = False
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    # Job status.
    from services.jobs import job_manager

    job_statuses = job_manager.job_statuses

    text = (
        f"🩺 <b>Health Check</b>\n\n"
        f"Database: {'✅ OK' if db_ok else '❌ FAIL'}\n"
        f"Jobs running: {job_statuses['jobs_running']}\n"
        f"Shutting down: {job_statuses['is_shutting_down']}\n"
        f"Job errors: {job_statuses['error_counts'] or 'none'}\n"
        f"Webhook: {'✅ enabled' if settings.webhook_enabled else '⬅️ long polling'}\n"
        f"Payments: {'✅ enabled' if settings.payments_enabled else '⛔ disabled'}\n"
    )
    await bot.send_message(chat_id=message.chat.id, text=text)


# --- /broadcast --------------------------------------------------------------

@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Start a broadcast: /broadcast <segment> <message text>.

    Segments: all, marketing (opt-in only).
    """
    if not _is_admin(message, settings):
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "Usage: /broadcast <segment> <message>\n"
                "Segments: all, marketing\n"
                "Example: /broadcast all 🎉 New offer available!"
            ),
        )
        return

    segment = parts[1]
    body_text = parts[2]
    marketing_only = segment == "marketing"

    svc = BroadcastService(session)
    result = await svc.enqueue(
        admin_id=settings.admin_chat_id,
        body_text=body_text,
        segment=segment,
        marketing_only=marketing_only,
    )
    await session.commit()

    if result.status == "empty":
        await bot.send_message(chat_id=message.chat.id, text="No recipients found.")
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                f"📤 Broadcast #{result.broadcast_id} queued.\n"
                f"Recipients: {result.recipient_count}\n"
                f"Segment: {segment}\n"
                f"Sending will start shortly."
            ),
        )


# --- /export -----------------------------------------------------------------

@router.message(Command("export"))
async def cmd_export(
    message: Message,
    settings: Settings,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Export conversions/payments as CSV: /export [conversions|payments]."""
    if not _is_admin(message, settings):
        return

    parts = (message.text or "").split()
    export_type = parts[1] if len(parts) > 1 else "conversions"

    svc = AdminService(session)
    if export_type == "payments":
        csv_data = await svc.export_payments_csv()
    else:
        csv_data = await svc.export_conversions_csv()

    if not csv_data.strip():
        await bot.send_message(chat_id=message.chat.id, text="No data to export.")
        return

    # Send as a document (inline text since we can't create files in the bot easily).
    max_len = 3500
    if len(csv_data) > max_len:
        csv_data = csv_data[:max_len] + "\n... (truncated)"
    await bot.send_message(
        chat_id=message.chat.id,
        text=f"```\n{csv_data}\n```",
    )
