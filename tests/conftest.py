"""Shared pytest fixtures."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.base import Base

# --- Sync env setup (autouse, works for both sync and async tests) -----------

@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Set env vars + reset caches for each test."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("BOT_TOKEN", "dummy:token")
    monkeypatch.setenv("ADMIN_CHAT_ID", "1")
    monkeypatch.setenv("LANDING_URL", "https://example.com")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("PAYMENTS_ENABLED", "true")

    from app.config import get_settings
    get_settings.cache_clear()

    import db.session as sm
    sm._engine = None
    sm._session_maker = None


# --- Async schema creation (autouse, depends on _env for ordering) -----------

@pytest_asyncio.fixture(autouse=True)
async def _schema(_env: None) -> AsyncIterator[None]:
    """Create schema on the per-test SQLite database."""
    from app.config import get_settings

    db_url = get_settings().database_url
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield

    import db.session as sm
    if sm._engine is not None:
        await sm._engine.dispose()
    sm._engine = None
    sm._session_maker = None


@pytest.fixture(autouse=True)
def _quiet_logging() -> None:
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# --- Direct DB session (for repository tests) --------------------------------

@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    from app.config import get_settings

    db_url = get_settings().database_url
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


# --- Mock Bot + Update builders ----------------------------------------------

@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock(spec=Bot)
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.edit_message_text = AsyncMock()
    bot.answer_callback_query = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.id = 123456789
    return bot


def make_message_update(update_id: int, user_id: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=TgUser(id=user_id, is_bot=False, first_name="Test"),
            text=text,
        ),
    )


def make_callback_update(
    update_id: int, user_id: int, data: str, message_text: str = ""
) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb_{update_id}",
            data=data,
            from_user=TgUser(id=user_id, is_bot=False, first_name="Test"),
            message=Message(
                message_id=999,
                date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=TgUser(id=user_id, is_bot=False, first_name="Bot"),
                text=message_text,
            ),
            chat_instance=str(user_id),
        ),
    )


# --- Session-scoped Dispatcher -----------------------------------------------

@pytest.fixture(scope="session")
def dp():
    import os

    os.environ.setdefault("BOT_TOKEN", "dummy:token")
    os.environ.setdefault("ADMIN_CHAT_ID", "1")
    os.environ.setdefault("LANDING_URL", "https://example.com")

    from app.main import build_dispatcher
    return build_dispatcher()
