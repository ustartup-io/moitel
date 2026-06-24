"""Single source of truth for bot startup.

Builds the Dispatcher, configures logging, and either:
- runs a boot smoke check (--check) that exits without polling, or
- starts long polling with graceful shutdown.

Handlers / routers are wired into the Dispatcher in later build steps.
"""
from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.logging_conf import get_logger, setup_logging

log = get_logger("app.main")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bot", description="Telegram affiliate/referral bot")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Boot smoke test: configure, log startup, and exit without polling.",
    )
    return parser.parse_args()


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

    # Imported lazily so the boot check never needs network access for aiogram.
    from aiogram import Dispatcher

    dp = Dispatcher()

    # Routers will be included here in later steps.
    log.info("dispatcher.ready", included_routers=[])

    if check:
        # Token-agnostic smoke: we only verify config + logging + Dispatcher build.
        log.info("boot.check.ok", message="Boot smoke check passed; not starting polling.")
        return

    from aiogram import Bot

    bot = Bot(token=settings.bot_token.get_secret_value())

    log.info("bot.polling.start")
    try:
        await dp.start_polling(bot)
    finally:
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
