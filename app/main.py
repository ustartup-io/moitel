"""Single source of truth for bot startup.

Builds the Dispatcher, registers middleware + routers, configures logging,
and either runs a boot smoke check (--check) or starts long polling.

Handlers / routers are included here. Middleware registration order is defined
in middlewares/stack.py::register_middlewares.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from app.config import get_settings
from app.logging_conf import get_logger, setup_logging

if TYPE_CHECKING:
    from aiogram import Dispatcher

log = get_logger("app.main")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bot", description="Telegram affiliate/referral bot")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Boot smoke test: configure, log startup, and exit without polling.",
    )
    return parser.parse_args()


def build_dispatcher() -> Dispatcher:
    """Build a fully wired Dispatcher (middleware + routers).

    Imported lazily so the boot check never needs aiogram internals.
    """
    from aiogram import Dispatcher

    from middlewares import register_middlewares
    from routers.common_router import router as common_router
    from routers.referral_router import router as referral_router
    from routers.start_router import router as start_router
    from routers.support_router import router as support_router
    from utils.faq import faq_matcher
    from utils.i18n import i18n

    # Preload texts + FAQ at startup.
    i18n.load()
    faq_matcher.load()

    dp = Dispatcher()
    register_middlewares(dp)

    # Routers: start first, then referral, support, common.
    dp.include_router(start_router)
    dp.include_router(referral_router)
    dp.include_router(support_router)
    dp.include_router(common_router)

    return dp


async def amain(*, check: bool = False) -> None:
    settings = get_settings()
    setup_logging(level=settings.log_level, json_logs=settings.environment == "prod")
    log.info(
        "bot.starting",
        environment=settings.environment,
        default_lang=settings.default_lang,
        payments_enabled=settings.payments_enabled,
        webhook_enabled=settings.webhook_enabled,
    )

    dp = build_dispatcher()
    log.info("dispatcher.ready", routers=["start", "referral", "support", "common"])

    if check:
        log.info("boot.check.ok", message="Boot smoke check passed; not starting polling.")
        return

    from aiogram import Bot

    bot = Bot(token=settings.bot_token.get_secret_value())

    # Start background jobs if payments are enabled.
    job_mgr = None
    if settings.payments_enabled:
        from services.jobs import job_manager
        job_mgr = job_manager
        await job_mgr.start_all()

    log.info("bot.polling.start")
    try:
        await dp.start_polling(bot)
    finally:
        if job_mgr is not None:
            await job_mgr.stop_all()
        await bot.session.close()
        log.info("bot.stopped")


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(amain(check=args.check))
    except KeyboardInterrupt:
        log.info("bot.interrupted")


if __name__ == "__main__":
    main()
