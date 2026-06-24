"""Integration tests: feed Updates through the full Dispatcher (middleware + routers).

Uses a mock Bot and a real per-test SQLite database.
"""
from __future__ import annotations

import pytest

from db.base import Lang
from db.repositories import UserRepository
from tests.conftest import make_callback_update, make_message_update


def _text_from(mock_method) -> str:
    """Safely extract the 'text' kwarg from a mock's last call."""
    call = mock_method.call_args
    if call is None:
        return ""
    return call.kwargs.get("text", "")


@pytest.mark.asyncio
async def test_start_shows_language_picker(dp, mock_bot) -> None:
    """New user sends /start -> language picker shown."""
    await dp.feed_update(mock_bot, make_message_update(1, 100100100, "/start"))
    mock_bot.send_message.assert_called_once()
    text = _text_from(mock_bot.send_message)
    assert "language" in text.lower() or "🌐" in text


@pytest.mark.asyncio
async def test_full_onboarding_flow_en(dp, mock_bot, db_session) -> None:
    """Walk through: /start -> lang pick -> compliance steps -> main menu."""
    uid = 200200200

    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    assert mock_bot.send_message.called

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:en"))
    assert "verification" in _text_from(mock_bot.edit_message_text).lower() or "📋" in _text_from(
        mock_bot.edit_message_text
    )

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(3, uid, "compliance:start:go"))
    assert "18" in _text_from(mock_bot.edit_message_text)

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(4, uid, "compliance:age:yes"))
    assert "country" in _text_from(mock_bot.edit_message_text).lower() or "🌍" in _text_from(
        mock_bot.edit_message_text
    )

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(5, uid, "compliance:jurisdiction:GB"))
    assert "gambling" in _text_from(mock_bot.edit_message_text).lower()

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(6, uid, "compliance:rg:yes"))
    assert "terms" in _text_from(mock_bot.edit_message_text).lower()

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(7, uid, "compliance:terms:yes"))
    assert "promotional" in _text_from(mock_bot.edit_message_text).lower()

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(8, uid, "compliance:marketing:yes"))
    confirmed = _text_from(mock_bot.edit_message_text)
    assert "all set" in confirmed.lower() or "✅" in confirmed
    reply_markup = mock_bot.edit_message_text.call_args.kwargs.get("reply_markup")
    assert reply_markup is not None

    # Verify user is compliant in DB.
    repo = UserRepository(db_session)
    user = await repo.get_by_telegram_id(uid)
    assert user is not None
    assert user.age_confirmed_at is not None
    assert user.jurisdiction_code == "GB"
    assert user.terms_accepted_at is not None
    assert user.marketing_opt_in is True
    assert user.lang == Lang.en


@pytest.mark.asyncio
async def test_compliance_blocked_on_age_no(dp, mock_bot) -> None:
    """Declining age shows blocked message."""
    uid = 300300300
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:en"))
    await dp.feed_update(mock_bot, make_callback_update(3, uid, "compliance:start:go"))

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(4, uid, "compliance:age:no"))
    text = _text_from(mock_bot.edit_message_text)
    assert "sorry" in text.lower() or "⛔" in text or "must meet" in text.lower()


@pytest.mark.asyncio
async def test_start_after_compliance_shows_menu(dp, mock_bot) -> None:
    """Compliant user sends /start -> main menu directly."""
    uid = 400400400
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:ru"))
    await dp.feed_update(mock_bot, make_callback_update(3, uid, "compliance:start:go"))
    await dp.feed_update(mock_bot, make_callback_update(4, uid, "compliance:age:yes"))
    await dp.feed_update(mock_bot, make_callback_update(5, uid, "compliance:jurisdiction:RU"))
    await dp.feed_update(mock_bot, make_callback_update(6, uid, "compliance:rg:yes"))
    await dp.feed_update(mock_bot, make_callback_update(7, uid, "compliance:terms:yes"))
    await dp.feed_update(mock_bot, make_callback_update(8, uid, "compliance:marketing:no"))

    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_message_update(9, uid, "/start"))
    text = _text_from(mock_bot.send_message)
    assert "Главное меню" in text or "Main Menu" in text


@pytest.mark.asyncio
async def test_help_command(dp, mock_bot) -> None:
    """/help shows help body with landing URL."""
    uid = 500500500
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/help"))
    text = _text_from(mock_bot.send_message)
    assert "https://example.com" in text


@pytest.mark.asyncio
async def test_ru_onboarding(dp, mock_bot) -> None:
    """Onboarding works end-to-end in Russian."""
    uid = 600600600
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:ru"))
    text = _text_from(mock_bot.edit_message_text)
    assert "проверк" in text.lower() or "📋" in text
