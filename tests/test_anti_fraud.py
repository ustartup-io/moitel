"""Anti-fraud tests: duplicate clicks, velocity, self-referral, fingerprint."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import OfferRepository, UserRepository
from services.anti_fraud import AntiFraudService
from services.referral_service import ReferralService


@pytest.mark.asyncio
async def test_duplicate_click_blocked(db_session: AsyncSession) -> None:
    """Second click by same user on same referral+offer within window is blocked."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=700700700)
    offer = await offer_repo.create(
        code="AF1", title_key="offer.test", base_url="https://x.com"
    )
    ref = await ref_service.get_or_create_for_user(user, offer=offer)
    await db_session.commit()

    # First click: allowed.
    click1, fraud1 = await ref_service.record_click(referral=ref, user=user)
    await db_session.commit()
    assert click1 is not None
    assert fraud1.blocked is False

    # Second click: blocked as duplicate.
    click2, fraud2 = await ref_service.record_click(referral=ref, user=user)
    await db_session.commit()
    assert click2 is None
    assert fraud2.blocked is True
    assert fraud2.reason == "duplicate_click"


@pytest.mark.asyncio
async def test_self_referral_blocked(db_session: AsyncSession) -> None:
    """Self-referral is flagged + blocked."""
    af = AntiFraudService(db_session)
    result = await af.check_self_referral(owner_user_id=100, converting_user_id=100)
    assert result.blocked is True
    assert result.reason == "self_referral"

    result2 = await af.check_self_referral(owner_user_id=100, converting_user_id=200)
    assert result2.blocked is False


@pytest.mark.asyncio
async def test_different_users_click_allowed(db_session: AsyncSession) -> None:
    """Different users clicking the same referral are both allowed."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_service = ReferralService(db_session)

    owner = await user_repo.create(telegram_id=800800800)
    user2 = await user_repo.create(telegram_id=800800801)
    offer = await offer_repo.create(
        code="AF2", title_key="offer.test", base_url="https://x.com"
    )
    ref = await ref_service.get_or_create_for_user(owner, offer=offer)
    await db_session.commit()

    click1, _ = await ref_service.record_click(referral=ref, user=user2)
    await db_session.commit()
    assert click1 is not None

    # Same user again = blocked (duplicate).
    click2, fraud2 = await ref_service.record_click(referral=ref, user=user2)
    await db_session.commit()
    assert click2 is None
    assert fraud2.reason == "duplicate_click"


@pytest.mark.asyncio
async def test_click_with_ip_hash_stored(db_session: AsyncSession) -> None:
    """Click with IP hash stores only the hash, never raw IP."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_service = ReferralService(db_session)

    user = await user_repo.create(telegram_id=900900900)
    offer = await offer_repo.create(
        code="AF3", title_key="offer.test", base_url="https://x.com"
    )
    ref = await ref_service.get_or_create_for_user(user, offer=offer)
    await db_session.commit()

    from utils.security import hash_ip

    ip_hash = hash_ip("203.0.113.42", "test-salt")
    click, _ = await ref_service.record_click(
        referral=ref, user=user, ip_hash=ip_hash
    )
    await db_session.commit()

    assert click is not None
    assert click.ip_hash == ip_hash
    assert "203.0.113" not in click.ip_hash  # raw IP never stored
