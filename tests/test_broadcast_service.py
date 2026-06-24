"""Broadcast service tests: enqueue, opt-out respect, queue processing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import UserRepository
from services.broadcast_service import BroadcastService


@pytest.mark.asyncio
async def test_enqueue_all_users(db_session: AsyncSession) -> None:
    """Enqueueing 'all' segment targets all users."""
    user_repo = UserRepository(db_session)
    await user_repo.create(telegram_id=200200201)
    await user_repo.create(telegram_id=200200202)
    await db_session.commit()

    svc = BroadcastService(db_session)
    result = await svc.enqueue(
        admin_id=1,
        body_text="Test broadcast",
        segment="all",
    )
    await db_session.commit()

    assert result.status == "queued"
    assert result.recipient_count >= 2
    assert result.broadcast_id > 0


@pytest.mark.asyncio
async def test_enqueue_marketing_only_skips_opt_out(db_session: AsyncSession) -> None:
    """Marketing-only broadcast skips users with marketing_opt_in=false."""
    user_repo = UserRepository(db_session)
    _u1 = await user_repo.create(telegram_id=200200301)
    u2 = await user_repo.create(telegram_id=200200302)
    await user_repo.set_compliance(
        telegram_id=u2.id, marketing_opt_in=True
    )
    await db_session.commit()

    svc = BroadcastService(db_session)
    result = await svc.enqueue(
        admin_id=1,
        body_text="Marketing message",
        segment="marketing",
        marketing_only=True,
    )
    await db_session.commit()

    assert result.recipient_count == 1  # only u2 opted in


@pytest.mark.asyncio
async def test_enqueue_empty(db_session: AsyncSession) -> None:
    """Enqueueing with no users returns empty."""
    svc = BroadcastService(db_session)
    result = await svc.enqueue(admin_id=1, body_text="x", segment="all")
    await db_session.commit()
    assert result.status == "empty"
    assert result.recipient_count == 0


@pytest.mark.asyncio
async def test_process_queue_sends(db_session: AsyncSession) -> None:
    """Queue processing sends messages via bot."""
    user_repo = UserRepository(db_session)
    await user_repo.create(telegram_id=200200401)
    await db_session.commit()

    svc = BroadcastService(db_session)
    await svc.enqueue(admin_id=1, body_text="Hello!", segment="all")
    await db_session.commit()

    # Mock bot.
    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await svc.process_queue(bot)
    await db_session.commit()

    assert sent >= 1
    bot.send_message.assert_called()


@pytest.mark.asyncio
async def test_broadcast_stats(db_session: AsyncSession) -> None:
    """Broadcast stats return correct counts."""
    user_repo = UserRepository(db_session)
    await user_repo.create(telegram_id=200200501)
    await db_session.commit()

    svc = BroadcastService(db_session)
    await svc.enqueue(admin_id=1, body_text="Stats test", segment="all")
    await db_session.commit()

    stats = await svc.get_broadcast_stats()
    assert stats["total_broadcasts"] >= 1
    assert stats["queued"] >= 1
