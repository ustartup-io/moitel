"""Repository round-trip tests: create, fetch, unique-constraint violations.

Note: unique constraint violations surface at flush() time (when the INSERT SQL
is sent), not at commit(). The service layer catches IntegrityError and handles
it (e.g. as a duplicate-skip). Here we assert the exception is raised on the
duplicate create call and then rollback.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import (
    ClickSource,
    ConversionSource,
    DeliveryType,
    Lang,
    OfferKind,
    PaymentProvider,
)
from db.repositories import (
    ClickRepository,
    ConversionRepository,
    DeliveryRepository,
    OfferRepository,
    PaymentRepository,
    ReferralRepository,
    UserRepository,
)


@pytest.mark.asyncio
async def test_user_create_and_fetch_by_telegram_id(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    await repo.create(telegram_id=111222333, username="alice", lang=Lang.en)
    await db_session.commit()

    fetched = await repo.get_by_telegram_id(111222333)
    assert fetched is not None
    assert fetched.id == 111222333
    assert fetched.username == "alice"
    assert fetched.lang == Lang.en
    assert fetched.status.value == "active"
    assert fetched.marketing_opt_in is False


@pytest.mark.asyncio
async def test_user_duplicate_telegram_id_raises(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    await repo.create(telegram_id=999888777, username="bob")
    await db_session.commit()

    # Duplicate telegram_id must violate uniqueness at flush time.
    with pytest.raises(IntegrityError):
        await repo.create(telegram_id=999888777, username="bob2")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_user_compliance_round_trip(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    await repo.create(telegram_id=555666777)
    await db_session.commit()

    updated = await repo.set_compliance(
        telegram_id=555666777,
        lang=Lang.ru,
        jurisdiction_code="RU",
        age_confirmed=True,
        terms_accepted=True,
        marketing_opt_in=True,
    )
    await db_session.commit()

    assert updated is not None
    assert updated.lang == Lang.ru
    assert updated.jurisdiction_code == "RU"
    assert updated.age_confirmed_at is not None
    assert updated.jurisdiction_attested_at is not None
    assert updated.terms_accepted_at is not None
    assert updated.marketing_opt_in is True


@pytest.mark.asyncio
async def test_offer_create_and_fetch_by_code(db_session: AsyncSession) -> None:
    repo = OfferRepository(db_session)
    offer = await repo.create(
        code="WELCOME10",
        title_key="offer.welcome",
        base_url="https://partner.example.com/offer",
        kind=OfferKind.affiliate_link,
    )
    await db_session.commit()

    fetched = await repo.get_by_code("WELCOME10")
    assert fetched is not None
    assert fetched.id == offer.id
    assert fetched.is_active is True
    assert fetched.requires_payment is False


@pytest.mark.asyncio
async def test_offer_duplicate_code_raises(db_session: AsyncSession) -> None:
    repo = OfferRepository(db_session)
    await repo.create(code="UNIQUE1", title_key="offer.x", base_url="https://x.com")
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await repo.create(code="UNIQUE1", title_key="offer.y", base_url="https://y.com")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_referral_create_and_unique_code(db_session: AsyncSession) -> None:
    user_repo = UserRepository(db_session)
    ref_repo = ReferralRepository(db_session)

    user = await user_repo.create(telegram_id=100100100)
    await ref_repo.create(owner_user_id=user.id, code="ALICE100")
    await db_session.commit()

    fetched = await ref_repo.get_by_code("ALICE100")
    assert fetched is not None
    assert fetched.owner_user_id == user.id

    with pytest.raises(IntegrityError):
        await ref_repo.create(owner_user_id=user.id, code="ALICE100")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_payment_idempotency_key_unique(db_session: AsyncSession) -> None:
    user_repo = UserRepository(db_session)
    pay_repo = PaymentRepository(db_session)

    user = await user_repo.create(telegram_id=200200200)
    await pay_repo.create(
        user_id=user.id,
        offer_id=1,
        provider=PaymentProvider.xrocket,
        idempotency_key="idem-key-001",
        amount=500,
        currency="USDT",
    )
    await db_session.commit()

    fetched = await pay_repo.get_by_idempotency_key("idem-key-001")
    assert fetched is not None
    assert fetched.amount == 500

    with pytest.raises(IntegrityError):
        await pay_repo.create(
            user_id=user.id,
            offer_id=1,
            provider=PaymentProvider.xrocket,
            idempotency_key="idem-key-001",
            amount=999,
            currency="USDT",
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_delivery_dedupe_key_unique(db_session: AsyncSession) -> None:
    user_repo = UserRepository(db_session)
    del_repo = DeliveryRepository(db_session)

    user = await user_repo.create(telegram_id=300300300)
    await del_repo.create(
        user_id=user.id,
        offer_id=1,
        delivery_type=DeliveryType.access_link,
        dedupe_key="dedupe-001",
    )
    await db_session.commit()

    fetched = await del_repo.get_by_dedupe_key("dedupe-001")
    assert fetched is not None

    with pytest.raises(IntegrityError):
        await del_repo.create(
            user_id=user.id,
            offer_id=1,
            delivery_type=DeliveryType.access_link,
            dedupe_key="dedupe-001",
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_full_referral_click_conversion_chain(db_session: AsyncSession) -> None:
    """End-to-end aggregate chain: user -> referral -> click -> conversion."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    ref_repo = ReferralRepository(db_session)
    click_repo = ClickRepository(db_session)
    conv_repo = ConversionRepository(db_session)

    owner = await user_repo.create(telegram_id=400400400)
    offer = await offer_repo.create(
        code="CHAIN1", title_key="offer.chain", base_url="https://chain.example.com"
    )
    referral = await ref_repo.create(
        owner_user_id=owner.id, code="CHAIN-REF", offer_id=offer.id
    )
    click = await click_repo.create(
        offer_id=offer.id, referral_id=referral.id, source=ClickSource.telegram
    )
    conversion = await conv_repo.create(
        offer_id=offer.id,
        source=ConversionSource.postback,
        click_id=click.id,
        referral_id=referral.id,
        partner_conversion_id="PART-001",
        amount=1000,
        currency="USDT",
    )
    await db_session.commit()

    fetched_conv = await conv_repo.get_by_partner_id("PART-001")
    assert fetched_conv is not None
    assert fetched_conv.id == conversion.id
    assert fetched_conv.referral_id == referral.id
    assert fetched_conv.click_id == click.id
    assert fetched_conv.amount == 1000


@pytest.mark.asyncio
async def test_user_not_found_returns_none(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    fetched = await repo.get_by_telegram_id(777777777)
    assert fetched is None
