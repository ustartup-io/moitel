"""Single source of truth for the async engine + session factory.

- Creates an async engine bound to DATABASE_URL (lazily on first use).
- Enables WAL mode on SQLite to reduce write contention (MVP).
- Provides `get_session()` — an async context manager — for middleware/handlers.
- Provides `get_async_session()` sessionmaker for services needing a fresh session.

The service layer commits explicitly; repo methods never commit.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def create_engine_from_url(database_url: str) -> AsyncEngine:
    """Build an async engine with SQLite WAL pragma applied on connect."""
    engine_kwargs: dict[str, Any] = {}
    if _is_sqlite(database_url):
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(database_url, echo=False, **engine_kwargs)

    if _is_sqlite(database_url):
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the singleton async engine (created lazily)."""
    global _engine
    if _engine is None:
        from app.config import get_settings
        _engine = create_engine_from_url(get_settings().database_url)
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory (created lazily)."""
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_maker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context-managed session for middleware/handlers.

    Usage:
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_telegram_id(...)
            await session.commit()
    """
    async with get_async_session()() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the engine pool on shutdown."""
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_maker = None
