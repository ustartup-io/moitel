"""Tests for app.logging_conf setup & correlation helpers."""
from __future__ import annotations

import logging

from app.logging_conf import (
    CORRELATION_KEYS,
    bind_correlation,
    clear_correlation,
    setup_logging,
)


def test_setup_logging_configures_root() -> None:
    setup_logging(level="DEBUG", json_logs=True)
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert root.handlers, "root logger must have at least one handler"


def test_correlation_keys_contract() -> None:
    assert set(CORRELATION_KEYS) == {
        "user_id",
        "update_id",
        "payment_id",
        "referral_code",
        "webhook_event_id",
    }


def test_bind_and_clear_correlation_does_not_raise() -> None:
    clear_correlation()
    bind_correlation(user_id=42, referral_code="ABC", ignored_key="x")
    clear_correlation()
