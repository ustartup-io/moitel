"""FAQ matcher tests: keyword matching, EN/RU parity, fallback, categories."""
from __future__ import annotations

from app.config import PROJECT_ROOT
from utils.faq import FaqMatcher


def test_faq_parity() -> None:
    """Every FAQ ID in en.yaml exists in ru.yaml and vice versa."""
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    matcher.load()
    report = matcher.check_parity()
    assert report["parity_ok"], (
        f"Missing in ru: {report['missing_in_ru']}, "
        f"missing in en: {report['missing_in_en']}"
    )


def test_match_en_how_to_pay() -> None:
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("how to pay", "en")
    assert result.matched
    assert result.item is not None
    assert result.item.id == "how_to_pay"


def test_match_ru_how_to_pay() -> None:
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("как оплатить", "ru")
    assert result.matched
    assert result.item is not None
    assert result.item.id == "how_to_pay"


def test_match_en_referral() -> None:
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("how does referral work", "en")
    assert result.matched
    assert result.item is not None
    assert result.item.id == "how_referral_works"


def test_match_ru_referral() -> None:
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("пригласить друга", "ru")
    assert result.matched
    assert result.item is not None
    assert result.item.id == "how_referral_works"


def test_no_match_returns_false() -> None:
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("xyzqwerty nonexistent", "en")
    assert not result.matched
    assert result.item is None


def test_answer_resolves() -> None:
    """Matched FAQ returns actual answer text (not just the key)."""
    from utils.i18n import i18n
    i18n.load()
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("is it safe", "en")
    assert result.matched
    assert len(result.answer) > 10
    assert result.answer != "faq.is_it_safe"  # resolved to actual text


def test_answer_resolves_ru() -> None:
    from utils.i18n import i18n
    i18n.load()
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    result = matcher.match("надёжно", "ru")
    assert result.matched
    assert len(result.answer) > 10


def test_categories_returned() -> None:
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    cats = matcher.get_categories("en")
    assert "general" in cats
    assert "payments" in cats
    assert "referrals" in cats
    assert len(cats) >= 5


def test_fallback_to_en() -> None:
    """English FAQ keyword matches even in ru mode (patterns are lang-specific)."""
    from utils.i18n import i18n
    i18n.load()
    matcher = FaqMatcher(PROJECT_ROOT / "faq")
    # Russian keyword for "safe" should match in both modes.
    result = matcher.match("надёжно ли", "ru")
    assert result.matched
