"""Inline keyboard builders shared across routers."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from routers.callbacks import (
    AdminCallback,
    ComplianceCallback,
    LangCallback,
    MenuCallback,
    SupportCallback,
)
from utils.i18n import Translator

# Common jurisdictions shown on the compliance gate (MVP subset).
JURISDICTIONS: list[tuple[str, str]] = [
    ("GB", "🇬🇧 UK"),
    ("RU", "🇷🇺 RU"),
    ("CY", "🇨🇾 CY"),
    ("MT", "🇲🇹 MT"),
]


def language_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇬🇧 English", callback_data=LangCallback(action="set", code="en"))
    kb.button(text="🇷🇺 Русский", callback_data=LangCallback(action="set", code="ru"))
    kb.adjust(2)
    return kb.as_markup()


def continue_keyboard(t: Translator) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("compliance.continue"),
        callback_data=ComplianceCallback(step="start", value="go"),
    )
    return kb.as_markup()


def yes_no_keyboard(step: str, t: Translator) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("common.yes"), callback_data=ComplianceCallback(step=step, value="yes"))
    kb.button(text=t("common.no"), callback_data=ComplianceCallback(step=step, value="no"))
    kb.adjust(2)
    return kb.as_markup()


def jurisdiction_keyboard(t: Translator) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, label in JURISDICTIONS:
        kb.button(
            text=label,
            callback_data=ComplianceCallback(step="jurisdiction", value=code),
        )
    kb.button(
        text=t("compliance.jurisdiction_other"),
        callback_data=ComplianceCallback(step="jurisdiction", value="OTHER"),
    )
    kb.adjust(2)
    return kb.as_markup()


def main_menu_keyboard(t: Translator) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("menu.catalog"), callback_data=MenuCallback(action="catalog"))
    kb.button(text=t("menu.referral"), callback_data=MenuCallback(action="referral"))
    kb.button(text=t("menu.support"), callback_data=MenuCallback(action="support"))
    kb.adjust(1)
    return kb.as_markup()


# --- Support keyboards -------------------------------------------------------

def support_category_keyboard(t: Translator, categories: list[str]) -> InlineKeyboardMarkup:
    """Build a keyboard of FAQ categories."""
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(
            text=t("support.category", category=cat.title()),
            callback_data=SupportCallback(action="category", category=cat),
        )
    kb.button(
        text=t("support.contact_admin"),
        callback_data=SupportCallback(action="escalate"),
    )
    kb.button(text=t("common.back"), callback_data=MenuCallback(action="back"))
    kb.adjust(1)
    return kb.as_markup()


def support_answer_keyboard(t: Translator, request_id: int = 0) -> InlineKeyboardMarkup:
    """Build the 'Did this solve it?' keyboard."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("common.yes"),
        callback_data=SupportCallback(action="solved", request_id=str(request_id)),
    )
    kb.button(
        text=t("common.no"),
        callback_data=SupportCallback(action="not_solved", request_id=str(request_id)),
    )
    kb.button(
        text=t("support.contact_admin"),
        callback_data=SupportCallback(action="escalate"),
    )
    kb.adjust(2)
    return kb.as_markup()


def admin_escalation_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Build the admin's escalation card keyboard (close/reply)."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Close request",
        callback_data=AdminCallback(action="close", request_id=str(request_id)),
    )
    kb.adjust(1)
    return kb.as_markup()
