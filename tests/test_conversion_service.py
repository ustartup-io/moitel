"""Tests for ConversionService: dedup, self-referral block, attribution."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import ClickSource, ConversionStatus
from db.repositories import (
    ClickRepository,
    OfferRepository,
    UserRepository,
)
from services.conversion_service import ConversionService
from services.referral_service import ReferralService


async def _setup_referral_with_click(db_session: AsyncSession, owner_id: int, clicker_id: int):
    """Helper: create owner, clicker, referral, and a click."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_service = ReferralService(db_session)
    click_repo = ClickRepository(db_session)

    owner = await user_repo.create(telegram_id=owner_id)
    clicker = await user_repo.create(telegram_id=clicker_id)
    offer = await offer_repo.create(
        code="CONV1", title_key="offer.test", base_url="https://x.com"
    )
    ref = await ref_service.get_or_create_for_user(owner, offer=offer)
    await click_repo.create(
        offer_id=offer.id, referral_id=ref.id, user_id=clicker.id, source=ClickSource.telegram
    )
    await db_session.commit()
    return owner, clicker, offer, ref


@pytest.mark.asyncio
async def test_duplicate_postback_is_noop(db_session: AsyncSession) -> None:
    """Posting the same partner_conversion_id twice creates ONE conversion."""
    _owner, clicker, offer, ref = await _setup_referral_with_click(
        db_session, 700700700, 700700701
    )
    conv_service = ConversionService(db_session)

    result1 = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="PART-DUP-001",
        referral_code=ref.code,
        converting_user_id=clicker.id,
    )
    await db_session.commit()
    assert result1.status == "created"
    assert result1.conversion is not None

    result2 = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="PART-DUP-001",
        referral_code=ref.code,
        converting_user_id=clicker.id,
    )
    await db_session.commit()
    assert result2.status == "duplicate"


@pytest.mark.asyncio
async def test_self_referral_blocked(db_session: AsyncSession) -> None:
    """Self-referral is blocked."""
    owner, _clicker, offer, ref = await _setup_referral_with_click(
        db_session, 800800800, 800800801
    )
    conv_service = ConversionService(db_session)

    # Owner tries to convert via their own referral code.
    result = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="PART-SELF-001",
        referral_code=ref.code,
        converting_user_id=owner.id,  # same as owner
    )
    await db_session.commit()

    assert result.status == "blocked"
    assert result.reason == "self_referral"
    assert result.conversion is None


@pytest.mark.asyncio
async def test_conversion_with_attribution(db_session: AsyncSession) -> None:
    """Conversion attributes to the referral + click from last-touch."""
    _owner, clicker, offer, ref = await _setup_referral_with_click(
        db_session, 900900900, 900900901
    )
    conv_service = ConversionService(db_session)

    result = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="PART-ATTR-001",
        referral_code=ref.code,
        converting_user_id=clicker.id,
        amount=5000,
        currency="USDT",
    )
    await db_session.commit()

    assert result.status == "created"
    assert result.conversion is not None
    assert result.conversion.referral_id == ref.id
    assert result.conversion.amount == 5000
    assert result.conversion.currency == "USDT"


@pytest.mark.asyncio
async def test_conversion_without_referral(db_session: AsyncSession) -> None:
    """Conversion without a referral code still records (no attribution)."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    user = await user_repo.create(telegram_id=110110110)
    offer = await offer_repo.create(
        code="CONV2", title_key="offer.test", base_url="https://x.com"
    )
    await db_session.commit()

    conv_service = ConversionService(db_session)
    result = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="PART-NOATTR-001",
        converting_user_id=user.id,
    )
    await db_session.commit()

    assert result.status == "created"
    assert result.conversion is not None
    assert result.conversion.referral_id is None


@pytest.mark.asyncio
async def test_update_conversion_status(db_session: AsyncSession) -> None:
    """Conversion status can be updated."""
    _owner, clicker, offer, ref = await _setup_referral_with_click(
        db_session, 120120120, 120120121
    )
    conv_service = ConversionService(db_session)

    result = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="PART-STATUS-001",
        referral_code=ref.code,
        converting_user_id=clicker.id,
    )
    await db_session.commit()

    assert result.conversion is not None
    assert result.conversion.status == ConversionStatus.pending

    updated = await conv_service.update_status(
        result.conversion.id, ConversionStatus.approved
    )
    await db_session.commit()

    assert updated is not None
    assert updated.status == ConversionStatus.approved
