"""FAQ loader + keyword matcher (rules-based, no ML/NLP).

Loads faq/{en,ru}.yaml into a structured knowledge base. Matching normalizes
input (lowercase, stripped) and checks for keyword/substring presence.

Fallback: if no match, returns None. Missing ru key falls back to en + WARNING.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import PROJECT_ROOT
from app.logging_conf import get_logger
from utils.i18n import SUPPORTED_LANGS, i18n

log = get_logger("app.faq")

FAQ_DIR = PROJECT_ROOT / "faq"


@dataclass
class FaqItem:
    """A single FAQ entry."""

    id: str
    category: str
    patterns: list[str]
    answer_key: str

    def matches(self, normalized_input: str) -> bool:
        """Check if any pattern is a substring of the normalized input."""
        return any(p in normalized_input for p in self.patterns)


@dataclass
class FaqMatchResult:
    """Result of a FAQ match attempt."""

    matched: bool
    item: FaqItem | None = None
    answer: str = ""
    categories: list[str] = field(default_factory=list)


class FaqMatcher:
    """Loads FAQ YAML files and matches user input to answers."""

    def __init__(self, faq_dir: Path = FAQ_DIR) -> None:
        self._faq_dir = faq_dir
        self._knowledge: dict[str, list[FaqItem]] = {}
        self._loaded = False

    def load(self) -> None:
        """Load all FAQ YAML files from disk."""
        if self._loaded:
            return
        for lang in SUPPORTED_LANGS:
            path = self._faq_dir / f"{lang}.yaml"
            if not path.exists():
                log.warning("faq.file_missing", lang=lang, path=str(path))
                continue
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            items: list[FaqItem] = []
            for category, entries in (raw or {}).items():
                for entry in entries:
                    items.append(
                        FaqItem(
                            id=entry["id"],
                            category=category,
                            patterns=[p.lower() for p in entry.get("patterns", [])],
                            answer_key=entry.get("answer_key", ""),
                        )
                    )
            self._knowledge[lang] = items
        self._loaded = True
        total = sum(len(v) for v in self._knowledge.values())
        log.info("faq.loaded", total_items=total, langs=list(self._knowledge.keys()))

    def get_categories(self, lang: str) -> list[str]:
        """Return the list of FAQ categories for a language."""
        if not self._loaded:
            self.load()
        items = self._knowledge.get(lang, [])
        # Preserve insertion order, deduplicated.
        seen: set[str] = set()
        cats: list[str] = []
        for item in items:
            if item.category not in seen:
                seen.add(item.category)
                cats.append(item.category)
        return cats

    def match(self, user_input: str, lang: str = "en") -> FaqMatchResult:
        """Match user input against FAQ patterns.

        Returns FaqMatchResult with the best match or matched=False.
        """
        if not self._loaded:
            self.load()

        normalized = user_input.lower().strip()
        items = self._knowledge.get(lang, self._knowledge.get("en", []))

        for item in items:
            if item.matches(normalized):
                answer = self._resolve_answer(item, lang)
                return FaqMatchResult(matched=True, item=item, answer=answer)

        return FaqMatchResult(matched=False, categories=self.get_categories(lang))

    def get_by_id(self, item_id: str, lang: str = "en") -> FaqItem | None:
        """Get a FAQ item by its ID."""
        if not self._loaded:
            self.load()
        items = self._knowledge.get(lang, self._knowledge.get("en", []))
        for item in items:
            if item.id == item_id:
                return item
        return None

    def get_items_by_category(self, category: str, lang: str = "en") -> list[FaqItem]:
        """Get all FAQ items in a category."""
        if not self._loaded:
            self.load()
        items = self._knowledge.get(lang, self._knowledge.get("en", []))
        return [item for item in items if item.category == category]

    def _resolve_answer(self, item: FaqItem, lang: str) -> str:
        """Resolve the answer text via i18n with fallback."""
        answer = i18n.t(item.answer_key, lang=lang)
        if answer == item.answer_key:
            # Key not found in requested lang; try English fallback.
            if lang != "en":
                answer_en = i18n.t(item.answer_key, lang="en")
                if answer_en != item.answer_key:
                    log.warning(
                        "faq.missing_lang_key",
                        key=item.answer_key,
                        lang=lang,
                    )
                    return answer_en
            # Last resort: return the key itself.
            return item.answer_key
        return answer

    def check_parity(self) -> dict[str, Any]:
        """Check FAQ ID parity between en and ru. Returns a report dict."""
        if not self._loaded:
            self.load()
        en_ids = {item.id for item in self._knowledge.get("en", [])}
        ru_ids = {item.id for item in self._knowledge.get("ru", [])}
        missing_in_ru = en_ids - ru_ids
        missing_in_en = ru_ids - en_ids
        return {
            "en_count": len(en_ids),
            "ru_count": len(ru_ids),
            "parity_ok": en_ids == ru_ids,
            "missing_in_ru": sorted(missing_in_ru),
            "missing_in_en": sorted(missing_in_en),
        }


# Module-level singleton.
faq_matcher = FaqMatcher()
