"""Single source of truth for text localization.

Loads texts/{en,ru}.json at startup (lazily on first use). Lookup t(key, lang)
falls back to English, logs a WARNING for missing keys, and returns the key
string as a last resort.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import TEXTS_DIR
from app.logging_conf import get_logger

log = get_logger("app.i18n")

SUPPORTED_LANGS: tuple[str, ...] = ("en", "ru")

Translator = Callable[..., str]


class I18n:
    """Lazy-loading i18n singleton."""

    def __init__(self, texts_dir: Path) -> None:
        self._texts_dir = texts_dir
        self._texts: dict[str, dict[str, str]] = {}
        self._loaded = False

    def load(self) -> None:
        """Load all text files from disk."""
        if self._loaded:
            return
        for lang in SUPPORTED_LANGS:
            path = self._texts_dir / f"{lang}.json"
            with path.open("r", encoding="utf-8") as f:
                self._texts[lang] = json.load(f)
        self._loaded = True
        log.info("i18n.loaded", langs=list(self._texts.keys()))

    def normalize_lang(self, lang: str) -> str:
        """Reject any lang not in SUPPORTED_LANGS, returning 'en' as fallback."""
        if lang not in SUPPORTED_LANGS:
            return "en"
        return lang

    def t(self, key: str, lang: str = "en", **kwargs: Any) -> str:
        """Translate a key with fallback chain: lang -> en -> key string."""
        if not self._loaded:
            self.load()
        lang = self.normalize_lang(lang)

        # Try requested lang first.
        template = self._texts.get(lang, {}).get(key)
        # Fallback to English.
        if template is None and lang != "en":
            template = self._texts.get("en", {}).get(key)
        # Last resort: return the key itself.
        if template is None:
            log.warning("i18n.missing_key", key=key, lang=lang)
            return key

        if kwargs:
            try:
                return template.format(**kwargs)
            except (KeyError, IndexError):
                return template
        return template

    def get_keys(self, lang: str) -> set[str]:
        """Return the set of keys for a given language."""
        if not self._loaded:
            self.load()
        return set(self._texts.get(self.normalize_lang(lang), {}).keys())


# Module-level singleton.
i18n = I18n(TEXTS_DIR)


def make_translator(lang: str) -> Translator:
    """Create a t() callable bound to a specific language."""

    def t(key: str, **kwargs: Any) -> str:
        return i18n.t(key, lang=lang, **kwargs)

    return t
