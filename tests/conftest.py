"""Shared pytest fixtures for database tests.

Each test gets a fresh SQLite database (via a temp file) with the schema
applied from Base.metadata.create_all — no Alembic needed at test time.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.base import Base


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide minimal env so app.config.Settings loads."""
    monkeypatch.setenv("BOT_TOKEN", "dummy:token")
    monkeypatch.setenv("ADMIN_CHAT_ID", "1")
    monkeypatch.setenv("LANDING_URL", "https://example.com")
    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _quiet_logging() -> None:
    """Suppress noisy aiosqlite/httpx debug logs during tests."""
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a fresh async session on a per-test SQLite database."""
    import tempfile

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()
    os.unlink(db_path)
