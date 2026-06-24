"""Tests for ReferralService: code generation, deep links, click recording, stats."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import ClickSource
from db.repositories import OfferRepository, UserRepository
from services.referral_service import ReferralService


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session: AsyncSession) -> None:
    """get_or_create_for_user returns the same referral on repeated calls."""
    user_repo = UserRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=111111111)
    ref1 = await ref_service.get_or_create_for_user(user)
    await db_session.commit()

    ref2 = await ref_service.get_or_create_for_user(user)
    await db_session.commit()

    assert ref1.id == ref2.id
    assert ref1.code == ref2.code
    assert ref1.owner_user_id == user.id


@pytest.mark.asyncio
async def test_referral_code_is_stable(db_session: AsyncSession) -> None:
    """Same user_id always produces the same code."""
    user_repo = UserRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=222222222)
    ref = await ref_service.get_or_create_for_user(user)
    await db_session.commit()

    from utils.security import generate_referral_code
    expected = generate_referral_code(222222222)
    assert ref.code == expected


@pytest.mark.asyncio
async def test_build_deep_link(db_session: AsyncSession) -> None:
    """Deep link contains the bot username and referral code."""
    user_repo = UserRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=333333333)
    ref = await ref_service.get_or_create_for_user(user)
    await db_session.commit()

    link = ref_service.build_deep_link(ref)
    assert ref.code in link
    assert "https://t.me/" in link


@pytest.mark.asyncio
async def test_record_click_telegram(db_session: AsyncSession) -> None:
    """Recording a click via telegram source creates a Click row."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=444444444)
    offer = await offer_repo.create(
        code="TEST1", title_key="offer.test", base_url="https://x.com"
    )
    ref = await ref_service.get_or_create_for_user(user, offer=offer)
    await db_session.commit()

    click, fraud = await ref_service.record_click(
        referral=ref, user=user, source=ClickSource.telegram
    )
    await db_session.commit()

    assert click is not None
    assert click.referral_id == ref.id
    assert click.offer_id == offer.id
    assert click.user_id == user.id
    assert fraud.blocked is False


@pytest.mark.asyncio
async def test_user_stats(db_session: AsyncSession) -> None:
    """User stats report correct counts after clicks."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=555555555)
    offer = await offer_repo.create(
        code="TEST2", title_key="offer.test", base_url="https://x.com"
    )
    ref = await ref_service.get_or_create_for_user(user, offer=offer)
    await ref_service.record_click(referral=ref, user=user)
    await ref_service.record_click(referral=ref, user=user)  # dedup: blocked
    await db_session.commit()

    stats = await ref_service.get_user_stats(user)
    assert stats["referrals"] >= 1
    assert stats["clicks"] == 1  # second click was duplicate-blocked


@pytest.mark.asyncio
async def test_resolve_unknown_code_returns_none(db_session: AsyncSession) -> None:
    """Resolving an unknown code returns None."""
    ref_service = ReferralService(db_session)
    result = await ref_service.resolve_referral_code("NONEXISTENT")
    assert result is None
