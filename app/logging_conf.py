"""Structured logging: unified structlog + stdlib JSON output to stdout.

Everything (our structlog calls AND third-party stdlib logs like aiogram /
uvicorn) is rendered through one ProcessorFormatter, so all lines share the
same JSON shape and correlation fields.

Public helpers:
- setup_logging(): configure once at startup.
- get_logger(): factory bound to the global config.
- bind_correlation() / clear_correlation(): stable per-update correlation keys.
- alert_admin(): stub notifier (logs ERROR now; real Telegram send wired later).
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

# Canonical correlation keys attached to every log line when present.
# Keep this list stable so log consumers can rely on a fixed event shape.
CORRELATION_KEYS: tuple[str, ...] = (
    "user_id",
    "update_id",
    "payment_id",
    "referral_code",
    "webhook_event_id",
)


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure unified structlog + stdlib logging to stdout."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Processors shared by structlog-originated AND stdlib (foreign) records.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # Hand records to stdlib so a single formatter renders everything.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()  # reset so repeated setup (tests/reloads) doesn't duplicate
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet noisy libs but keep them visible when debugging.
    for noisy in ("aiogram.event", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger bound to the global config."""
    return structlog.get_logger(name)


def bind_correlation(**kwargs: Any) -> None:
    """Bind standardized correlation fields into the current logging context.

    Only keys in CORRELATION_KEYS are accepted (others ignored) so the event
    shape stays stable. Call clear_correlation() at the start of each update to
    avoid leakage between requests.
    """
    allowed = {k: v for k, v in kwargs.items() if k in CORRELATION_KEYS}
    if allowed:
        structlog.contextvars.bind_contextvars(**allowed)


def clear_correlation() -> None:
    """Reset the per-update correlation context."""
    structlog.contextvars.clear_contextvars()


def alert_admin(message: str, **context: Any) -> None:
    """Stub admin alert: logs an ERROR now.

    The real implementation will forward to the admin chat via the bot in a
    later step. Call sites can rely on this signature from day one.
    """
    log = structlog.get_logger("app.admin_alert")
    log.error("admin.alert", message=message, **context)
