"""Support service tests: FAQ match, escalation after N attempts, close."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import SupportState
from db.repositories import UserRepository
from services.support_service import SupportService
from utils.faq import faq_matcher


@pytest.mark.asyncio
async def test_faq_match_returns_answer(db_session: AsyncSession) -> None:
    """Known keyword returns FAQ answer, not escalation."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=950950950)
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)
    result = await svc.process_message(user, "how to pay")
    await db_session.commit()

    assert result.action == "answered"
    assert len(result.answer) > 10


@pytest.mark.asyncio
async def test_escalation_after_2_attempts(db_session: AsyncSession) -> None:
    """2 unmatched attempts trigger escalation."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=960960960)
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)

    # First unmatched attempt.
    r1 = await svc.process_message(user, "xyzqwerty nonsense")
    await db_session.commit()
    assert r1.action == "no_match"
    assert r1.attempt_count == 1

    # Second unmatched attempt -> escalate.
    r2 = await svc.process_message(user, "more nonsense words")
    await db_session.commit()
    assert r2.action == "escalate"

    # Verify request is escalated.
    assert r2.request is not None
    assert r2.request.state == SupportState.escalated


@pytest.mark.asyncio
async def test_faq_match_resets_attempts(db_session: AsyncSession) -> None:
    """A successful FAQ match resets the unmatched counter."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=970970970)
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)

    # First attempt: no match.
    r1 = await svc.process_message(user, "nonsense")
    await db_session.commit()
    assert r1.attempt_count == 1

    # Second attempt: match -> resets.
    r2 = await svc.process_message(user, "how to pay")
    await db_session.commit()
    assert r2.action == "answered"

    # Third attempt: no match -> counter should be 1 (reset).
    r3 = await svc.process_message(user, "more nonsense")
    await db_session.commit()
    assert r3.attempt_count == 1


@pytest.mark.asyncio
async def test_explicit_escalation(db_session: AsyncSession) -> None:
    """Explicit escalate_now creates an escalated request."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=980980980)
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)
    result = await svc.escalate_now(user, reason="user_requested")
    await db_session.commit()

    assert result.action == "escalate"
    assert result.request is not None
    assert result.request.state == SupportState.escalated


@pytest.mark.asyncio
async def test_close_request(db_session: AsyncSession) -> None:
    """Closing a request sets state=closed."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=990990990)
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)
    result = await svc.escalate_now(user, reason="test")
    await db_session.commit()

    assert result.request is not None
    request_id = result.request.id

    closed = await svc.close_request(request_id)
    await db_session.commit()

    assert closed is not None
    assert closed.state == SupportState.closed


@pytest.mark.asyncio
async def test_admin_card_built(db_session: AsyncSession) -> None:
    """Admin escalation card contains key info."""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=101010101, username="testuser")
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)
    result = await svc.process_message(user, "payment stuck")
    await db_session.commit()

    assert result.request is not None
    card = svc.build_admin_card(result.request, user, username="testuser")
    assert "101010101" in card
    assert "testuser" in card
    assert f"#{result.request.id}" in card
