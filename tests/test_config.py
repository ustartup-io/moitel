"""Tests for app.config.Settings loading & validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

SAMPLE_ENV = {
    "BOT_TOKEN": "123456:ABCdummytoken",
    "ADMIN_CHAT_ID": "42424242",
    "LANDING_URL": "https://offer.example.com/landing",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_settings_loads_required(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, SAMPLE_ENV)
    settings = Settings(_env_file=None)
    assert settings.bot_token.get_secret_value() == "123456:ABCdummytoken"
    assert settings.admin_chat_id == 42424242
    assert settings.landing_url == "https://offer.example.com/landing"


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, SAMPLE_ENV)
    monkeypatch.setenv("PAYMENTS_ENABLED", "false")
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.log_level == "INFO"
    assert settings.default_lang == "en"
    assert settings.database_url.startswith("sqlite")
    assert settings.payments_enabled is False
    assert settings.webhook_enabled is False
    assert settings.xrocket_base_url == "https://pay.xrocket.tg/"
    assert settings.xrocket_mode == "testnet"


def test_settings_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SAMPLE_ENV:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_lang_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, SAMPLE_ENV)
    monkeypatch.setenv("DEFAULT_LANG", "ru")
    settings = Settings(_env_file=None)
    assert settings.default_lang == "ru"

    monkeypatch.setenv("DEFAULT_LANG", "fr")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_fail_fast_prod_passes_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, SAMPLE_ENV)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("PAYMENTS_ENABLED", "false")
    settings = Settings(_env_file=None)
    settings.fail_fast_prod()  # no payments/webhook enabled -> no error


def test_fail_fast_prod_rejects_payments_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, SAMPLE_ENV)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("PAYMENTS_ENABLED", "true")
    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="XROCKET_API_KEY"):
        settings.fail_fast_prod()
