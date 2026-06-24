"""Tests for i18n: parity check, lookup, fallback, format, invalid lang."""
from __future__ import annotations

import json

from app.config import TEXTS_DIR
from utils.i18n import SUPPORTED_LANGS, I18n


def test_en_ru_parity() -> None:
    """Every key in en.json must exist in ru.json and vice versa."""
    en = json.loads((TEXTS_DIR / "en.json").read_text(encoding="utf-8"))
    ru = json.loads((TEXTS_DIR / "ru.json").read_text(encoding="utf-8"))
    en_keys = set(en.keys())
    ru_keys = set(ru.keys())
    missing_in_ru = en_keys - ru_keys
    missing_in_en = ru_keys - en_keys
    assert not missing_in_ru, f"Keys in en but missing in ru: {missing_in_ru}"
    assert not missing_in_en, f"Keys in ru but missing in en: {missing_in_en}"


def test_supported_langs() -> None:
    assert set(SUPPORTED_LANGS) == {"en", "ru"}


def test_lookup_known_key() -> None:
    i18n = I18n(TEXTS_DIR)
    assert "Welcome" in i18n.t("start.welcome", "en", first_name="Test")


def test_lookup_ru() -> None:
    i18n = I18n(TEXTS_DIR)
    assert "Добро пожаловать" in i18n.t("start.welcome", "ru", first_name="Тест")


def test_fallback_to_en() -> None:
    """If a key is missing in ru, fall back to en."""
    i18n = I18n(TEXTS_DIR)
    # Temporarily remove a key from ru to test fallback.
    i18n.load()
    original = i18n._texts["ru"].pop("help.body", None)
    try:
        result = i18n.t("help.body", "ru", landing_url="https://x.com")
        assert "help" in result.lower() or "visit" in result.lower()
    finally:
        if original is not None:
            i18n._texts["ru"]["help.body"] = original


def test_missing_key_returns_key() -> None:
    """Unknown key returns the key string itself."""
    i18n = I18n(TEXTS_DIR)
    result = i18n.t("nonexistent.key.xyz", "en")
    assert result == "nonexistent.key.xyz"


def test_invalid_lang_falls_back_to_en() -> None:
    i18n = I18n(TEXTS_DIR)
    result = i18n.t("start.welcome", "fr", first_name="Test")
    assert "Welcome" in result  # English fallback


def test_format_with_kwargs() -> None:
    i18n = I18n(TEXTS_DIR)
    result = i18n.t("help.body", "en", landing_url="https://mylink.com")
    assert "https://mylink.com" in result


def test_format_missing_kwarg_returns_template() -> None:
    """If a kwarg is missing, return the unformatted template (no crash)."""
    i18n = I18n(TEXTS_DIR)
    result = i18n.t("help.body", "en")  # missing landing_url
    assert isinstance(result, str)
    assert len(result) > 0
