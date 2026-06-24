"""End-to-end integration tests: walk onboarding -> compliance -> offer view ->
  (paid path: invoice -> callback -> delivery) AND
  (affiliate path: click -> postback -> delivery).
Asserts single delivery in both paths.

Also verifies: compliance gate precedes offer access; FAQ parity; text parity.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import (
    ClickSource,
    ConversionStatus,
    DeliveryStatus,
    DeliveryType,
    OfferKind,
    PaymentStatus,
)
from db.repositories import (
    DeliveryRepository,
    OfferRepository,
    UserRepository,
)
from services.conversion_service import ConversionService
from services.delivery_service import DeliveryService
from services.payment_service import PaymentService
from services.referral_service import ReferralService
from services.xrocket_client import MockXRocketClient
from tests.conftest import make_callback_update, make_message_update

# ---------------------------------------------------------------------------
# PATH 1: Affiliate (free offer) — click -> postback -> delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_affiliate_path_click_postback_delivery(db_session: AsyncSession) -> None:
    """Full affiliate path: create offer -> click -> postback -> single delivery."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    # Setup: owner user, converter user, and free affiliate offer.
    owner = await user_repo.create(telegram_id=800800001)
    converter = await user_repo.create(telegram_id=800800099)
    offer = await offer_repo.create(
        code="AFF-INT-1",
        title_key="offer.affiliate",
        base_url="https://partner.example.com/offer",
        kind=OfferKind.affiliate_link,
        requires_payment=False,
        delivery_type=DeliveryType.external_link,
    )
    await db_session.commit()

    # Step 1: Owner creates referral; converter clicks it.
    ref_service = ReferralService(db_session)
    referral = await ref_service.get_or_create_for_user(owner, offer=offer)
    click, fraud = await ref_service.record_click(
        referral=referral, user=converter, source=ClickSource.telegram
    )
    await db_session.commit()
    assert click is not None
    assert fraud.blocked is False

    # Step 2: Simulate a postback conversion.
    conv_service = ConversionService(db_session)
    result = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="AFF-CONV-001",
        referral_code=referral.code,
        converting_user_id=converter.id,
        status=ConversionStatus.approved,
    )
    await db_session.commit()
    assert result.status == "created"
    assert result.conversion is not None

    # Step 3: Trigger delivery for the conversion.
    delivery_service = DeliveryService(db_session)
    del_result = await delivery_service.deliver_for_conversion(result.conversion)
    await db_session.commit()
    assert del_result.status == "delivered"

    # Step 4: Verify SINGLE delivery (no double-delivery).
    dedupe_key = f"conv:{converter.id}:{offer.id}:{result.conversion.id}"
    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.get_by_dedupe_key(dedupe_key)
    assert delivery is not None
    assert delivery.status == DeliveryStatus.sent

    # Second delivery attempt: no-op.
    del_result2 = await delivery_service.deliver_for_conversion(result.conversion)
    await db_session.commit()
    assert del_result2.status == "skipped"

    # Still only one delivery.
    delivery2 = await del_repo.get_by_dedupe_key(dedupe_key)
    assert delivery2.id == delivery.id


# ---------------------------------------------------------------------------
# PATH 2: Paid access — invoice -> paid callback -> delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paid_path_invoice_callback_delivery(db_session: AsyncSession) -> None:
    """Full paid path: create offer -> invoice -> paid callback -> single delivery."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    user = await user_repo.create(telegram_id=800800002)
    offer = await offer_repo.create(
        code="PAID-INT-1",
        title_key="offer.paid",
        base_url="https://partner.example.com/paid",
        kind=OfferKind.paid_access,
        requires_payment=True,
        price_amount=500,
        price_currency="USDT",
        delivery_type=DeliveryType.access_link,
    )
    await db_session.commit()

    # Step 1: Create invoice via mock xRocket.
    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)
    inv_result = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()
    assert inv_result.status == "created"
    assert inv_result.payment is not None
    payment = inv_result.payment

    # Step 2: Simulate paid callback.
    confirmed = await pay_service.confirm_payment(
        provider_invoice_id=payment.provider_invoice_id or "",
        payment_id_from_payload=payment.id,
    )
    await db_session.commit()
    assert confirmed is not None
    assert confirmed.status == PaymentStatus.paid

    # Step 3: Verify SINGLE delivery (auto-triggered on confirm).
    dedupe_key = f"pay:{user.id}:{offer.id}:{payment.id}"
    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.get_by_dedupe_key(dedupe_key)
    assert delivery is not None
    assert delivery.status == DeliveryStatus.sent

    # Step 4: Second confirmation = no-op (no double delivery).
    confirmed2 = await pay_service.confirm_payment(
        provider_invoice_id=payment.provider_invoice_id or "",
        payment_id_from_payload=payment.id,
    )
    await db_session.commit()
    assert confirmed2.status == PaymentStatus.paid

    delivery2 = await del_repo.get_by_dedupe_key(dedupe_key)
    assert delivery2.id == delivery.id


# ---------------------------------------------------------------------------
# COMPLIANCE GATE PRECEDES OFFER ACCESS (integration via Dispatcher)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compliance_gate_blocks_catalog(dp, mock_bot) -> None:
    """Non-compliant user cannot see catalog offers."""
    uid = 800800003
    # Send /start but DON'T complete compliance.
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    mock_bot.reset_mock()

    # Try to access catalog.
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "menu:catalog"))

    # Should show compliance warning, not offers.
    text = ""
    if mock_bot.edit_message_text.called:
        text = mock_bot.edit_message_text.call_args.kwargs.get("text", "")
    elif mock_bot.send_message.called:
        text = mock_bot.send_message.call_args.kwargs.get("text", "")
    assert "verification" in text.lower() or "⛔" in text


# ---------------------------------------------------------------------------
# CONVERSION -> DELIVERY TRIGGERED ON MANUAL APPROVE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manual_conversion_approve_triggers_delivery(db_session: AsyncSession) -> None:
    """Admin approving a conversion triggers delivery."""
    from services.admin_service import AdminService

    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    user = await user_repo.create(telegram_id=800800004)
    offer = await offer_repo.create(
        code="MANUAL-INT-1", title_key="offer.m", base_url="https://x.com",
    )
    await db_session.commit()

    # Create a pending conversion.
    conv_service = ConversionService(db_session)
    result = await conv_service.record_conversion(
        offer=offer, partner_conversion_id="MANUAL-CONV-001",
        status=ConversionStatus.pending,
    )
    await db_session.commit()

    # Admin approves.
    admin_svc = AdminService(db_session)
    approved = await admin_svc.manual_confirm_conversion(
        admin_id=1, conversion_id=result.conversion.id,
        status=ConversionStatus.approved,
    )
    await db_session.commit()
    assert approved is not None
    assert approved.status == ConversionStatus.approved

    # Delivery should exist.
    dedupe_key = f"conv:{user.id or 0}:{offer.id}:{result.conversion.id}"
    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.get_by_dedupe_key(dedupe_key)
    # Note: user_id may be 0 if not set on conversion, so check by conversion_id.
    from sqlalchemy import select

    from db.models import Delivery
    result_q = await db_session.execute(
        select(Delivery).where(Delivery.conversion_id == result.conversion.id)
    )
    delivery = result_q.scalars().first()
    assert delivery is not None
    assert delivery.status == DeliveryStatus.sent


# ---------------------------------------------------------------------------
# WEBHOOK POSTBACK -> CONVERSION -> DELIVERY (for approved status)
# ---------------------------------------------------------------------------

def test_webhook_approved_postback_triggers_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST affiliate postback with status=approved triggers delivery."""
    import os
    import tempfile

    db_file = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("BOT_TOKEN", "dummy:token")
    monkeypatch.setenv("ADMIN_CHAT_ID", "1")
    monkeypatch.setenv("LANDING_URL", "https://example.com")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("PAYMENTS_ENABLED", "true")

    from app.config import get_settings
    get_settings.cache_clear()
    import db.session as sm
    sm._engine = None
    sm._session_maker = None

    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from db.base import Base

    async def setup_and_test() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_file}", connect_args={"check_same_thread": False}
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        # Create an offer.
        async with maker() as session:
            repo = OfferRepository(session)
            await repo.create(
                code="WH-INT-1", title_key="offer.wh", base_url="https://x.com"
            )
            await session.commit()

        # POST a postback with status=approved.
        from app.webhook_app import create_app
        client = TestClient(create_app())
        resp = client.post(
            "/webhooks/affiliate/default",
            headers={"X-Webhook-Secret": "test-secret"},
            json={
                "partner_conversion_id": "WH-CONV-001",
                "offer_code": "WH-INT-1",
                "status": "approved",
                "amount": 100,
                "currency": "USDT",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"

        # Verify delivery exists.
        from sqlalchemy import select as sa_select

        from db.models import Delivery
        async with maker() as session:
            result = await session.execute(
                sa_select(Delivery).order_by(Delivery.id.desc()).limit(1)
            )
            delivery = result.scalars().first()
            assert delivery is not None
            assert delivery.status == DeliveryStatus.sent

        await engine.dispose()

    asyncio.run(setup_and_test())
    os.unlink(db_file)


# ---------------------------------------------------------------------------
# PARITY CHECKS
# ---------------------------------------------------------------------------

def test_text_parity() -> None:
    """Every key in en.json exists in ru.json and vice versa."""
    from app.config import TEXTS_DIR
    en = json.loads((TEXTS_DIR / "en.json").read_text(encoding="utf-8"))
    ru = json.loads((TEXTS_DIR / "ru.json").read_text(encoding="utf-8"))
    en_keys, ru_keys = set(en.keys()), set(ru.keys())
    assert en_keys == ru_keys, (
        f"Missing in ru: {en_keys - ru_keys}, missing in en: {ru_keys - en_keys}"
    )


def test_faq_parity() -> None:
    """Every FAQ ID in en.yaml exists in ru.yaml and vice versa."""
    from utils.faq import faq_matcher
    faq_matcher.load()
    report = faq_matcher.check_parity()
    assert report["parity_ok"], (
        f"Missing in ru: {report['missing_in_ru']}, missing in en: {report['missing_in_en']}"
    )
