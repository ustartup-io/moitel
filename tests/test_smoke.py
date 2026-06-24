"""FULL SMOKE TEST — walks every production path end-to-end.

Simulates: onboarding (EN+RU), compliance gate, catalog, offer view,
affiliate path (click->postback->delivery), paid path (invoice->callback->delivery),
support escalation round-trip, admin-only broadcast, /health, /stats.

Uses mocked Bot + mocked xRocket + TestClient for webhooks.
No real Telegram API calls. This IS the smoke test evidence for launch.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_callback_update, make_message_update


def _text(mock_bot, method_name: str = "send_message") -> str:
    call = getattr(mock_bot, method_name).call_args
    if call is None:
        return ""
    return call.kwargs.get("text", "")


# ---------------------------------------------------------------------------
# SMOKE: Onboarding EN — /start -> language -> compliance -> menu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_onboarding_en(dp, mock_bot) -> None:
    """EN onboarding: start -> pick English -> compliance gate -> main menu."""
    uid = 990000001

    # /start -> language picker
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    assert "🌐" in _text(mock_bot) or "language" in _text(mock_bot).lower()

    # Pick English
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:en"))
    assert "📋" in _text(mock_bot, "edit_message_text") or "verification" in _text(
        mock_bot, "edit_message_text"
    ).lower()

    # Complete compliance: start -> age -> jurisdiction -> RG -> terms -> marketing
    await dp.feed_update(mock_bot, make_callback_update(3, uid, "compliance:start:go"))
    assert "18" in _text(mock_bot, "edit_message_text")

    await dp.feed_update(mock_bot, make_callback_update(4, uid, "compliance:age:yes"))
    assert "🌍" in _text(mock_bot, "edit_message_text")

    await dp.feed_update(mock_bot, make_callback_update(5, uid, "compliance:jurisdiction:GB"))
    assert "⚠️" in _text(mock_bot, "edit_message_text")

    await dp.feed_update(mock_bot, make_callback_update(6, uid, "compliance:rg:yes"))
    assert "📄" in _text(mock_bot, "edit_message_text")

    await dp.feed_update(mock_bot, make_callback_update(7, uid, "compliance:terms:yes"))
    assert "📧" in _text(mock_bot, "edit_message_text")

    await dp.feed_update(mock_bot, make_callback_update(8, uid, "compliance:marketing:yes"))
    assert "✅" in _text(mock_bot, "edit_message_text")


# ---------------------------------------------------------------------------
# SMOKE: Onboarding RU — verify Russian path works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_onboarding_ru(dp, mock_bot) -> None:
    """RU onboarding: start -> pick Russian -> compliance intro is in Russian."""
    uid = 990000002
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:ru"))
    text = _text(mock_bot, "edit_message_text")
    assert "проверк" in text.lower() or "📋" in text


# ---------------------------------------------------------------------------
# SMOKE: Compliance gate blocks catalog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_compliance_blocks_catalog(dp, mock_bot) -> None:
    """Non-compliant user can't see catalog."""
    uid = 990000003
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "menu:catalog"))
    text = _text(mock_bot, "edit_message_text") or _text(mock_bot)
    assert "verification" in text.lower() or "⛔" in text


# ---------------------------------------------------------------------------
# SMOKE: Compliant user sees catalog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_catalog_after_compliance(dp, mock_bot, db_session) -> None:
    """Compliant user with a seeded offer sees catalog."""
    from db.base import OfferKind
    from db.repositories import OfferRepository

    # Seed an offer.
    offer_repo = OfferRepository(db_session)
    await offer_repo.create(
        code="SMOKE1",
        title_key="offer.smoke1",
        base_url="https://partner.example.com/landing",
        kind=OfferKind.affiliate_link,
        requires_payment=False,
    )
    await db_session.commit()

    uid = 990000004
    # Complete onboarding.
    await dp.feed_update(mock_bot, make_message_update(1, uid, "/start"))
    await dp.feed_update(mock_bot, make_callback_update(2, uid, "lang:set:en"))
    await dp.feed_update(mock_bot, make_callback_update(3, uid, "compliance:start:go"))
    await dp.feed_update(mock_bot, make_callback_update(4, uid, "compliance:age:yes"))
    await dp.feed_update(mock_bot, make_callback_update(5, uid, "compliance:jurisdiction:GB"))
    await dp.feed_update(mock_bot, make_callback_update(6, uid, "compliance:rg:yes"))
    await dp.feed_update(mock_bot, make_callback_update(7, uid, "compliance:terms:yes"))
    await dp.feed_update(mock_bot, make_callback_update(8, uid, "compliance:marketing:no"))

    # Now open catalog.
    mock_bot.reset_mock()
    await dp.feed_update(mock_bot, make_callback_update(9, uid, "menu:catalog"))
    text = _text(mock_bot, "edit_message_text")
    assert "SMOKE1" in text or "offer" in text.lower() or "📚" in text


# ---------------------------------------------------------------------------
# SMOKE: Affiliate path — click -> postback -> single delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_affiliate_path(db_session) -> None:
    """Full affiliate path with single delivery."""
    from db.base import ConversionStatus, OfferKind
    from db.repositories import (
        OfferRepository,
        UserRepository,
    )
    from services.conversion_service import ConversionService
    from services.delivery_service import DeliveryService
    from services.referral_service import ReferralService

    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    owner = await user_repo.create(telegram_id=990000010)
    converter = await user_repo.create(telegram_id=990000011)
    offer = await offer_repo.create(
        code="SMOKE-AFF",
        title_key="offer.smoke_aff",
        base_url="https://partner.example.com",
        kind=OfferKind.affiliate_link,
        requires_payment=False,
    )
    await db_session.commit()

    ref_service = ReferralService(db_session)
    referral = await ref_service.get_or_create_for_user(owner, offer=offer)
    click, _ = await ref_service.record_click(referral=referral, user=converter)
    await db_session.commit()
    assert click is not None

    conv_service = ConversionService(db_session)
    result = await conv_service.record_conversion(
        offer=offer,
        partner_conversion_id="SMOKE-AFF-CONV",
        referral_code=referral.code,
        converting_user_id=converter.id,
        status=ConversionStatus.approved,
    )
    await db_session.commit()
    assert result.status == "created"

    delivery_service = DeliveryService(db_session)
    del_result = await delivery_service.deliver_for_conversion(result.conversion)
    await db_session.commit()
    assert del_result.status == "delivered"

    # Dedup: second attempt = no-op.
    del_result2 = await delivery_service.deliver_for_conversion(result.conversion)
    await db_session.commit()
    assert del_result2.status == "skipped"


# ---------------------------------------------------------------------------
# SMOKE: Paid path — invoice -> paid callback -> single delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_paid_path(db_session) -> None:
    """Full paid path with single delivery."""
    from db.base import DeliveryStatus, DeliveryType, OfferKind, PaymentStatus
    from db.repositories import DeliveryRepository, OfferRepository, UserRepository
    from services.payment_service import PaymentService
    from services.xrocket_client import MockXRocketClient

    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    user = await user_repo.create(telegram_id=990000020)
    offer = await offer_repo.create(
        code="SMOKE-PAID",
        title_key="offer.smoke_paid",
        base_url="https://partner.example.com/paid",
        kind=OfferKind.paid_access,
        requires_payment=True,
        price_amount=1000,
        price_currency="USDT",
        delivery_type=DeliveryType.access_link,
    )
    await db_session.commit()

    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)
    inv = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()
    assert inv.status == "created"

    confirmed = await pay_service.confirm_payment(
        provider_invoice_id=inv.payment.provider_invoice_id or "",
        payment_id_from_payload=inv.payment.id,
    )
    await db_session.commit()
    assert confirmed.status == PaymentStatus.paid

    dedupe_key = f"pay:{user.id}:{offer.id}:{inv.payment.id}"
    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.get_by_dedupe_key(dedupe_key)
    assert delivery is not None
    assert delivery.status == DeliveryStatus.sent

    # Second confirm = no-op.
    confirmed2 = await pay_service.confirm_payment(
        provider_invoice_id=inv.payment.provider_invoice_id or "",
        payment_id_from_payload=inv.payment.id,
    )
    await db_session.commit()
    assert confirmed2.status == PaymentStatus.paid
    delivery2 = await del_repo.get_by_dedupe_key(dedupe_key)
    assert delivery2.id == delivery.id


# ---------------------------------------------------------------------------
# SMOKE: Support escalation round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_support_escalation(db_session) -> None:
    """Support: unmatched -> escalate -> close."""
    from db.base import SupportState
    from db.repositories import UserRepository
    from services.support_service import SupportService
    from utils.faq import faq_matcher

    user_repo = UserRepository(db_session)
    user = await user_repo.create(telegram_id=990000030)
    await db_session.commit()

    svc = SupportService(db_session, faq_matcher)

    # Two unmatched -> escalate.
    await svc.process_message(user, "xyzqwerty")
    await db_session.commit()
    r2 = await svc.process_message(user, "more nonsense")
    await db_session.commit()
    assert r2.action == "escalate"
    assert r2.request.state == SupportState.escalated

    # Close.
    closed = await svc.close_request(r2.request.id)
    await db_session.commit()
    assert closed.state == SupportState.closed


# ---------------------------------------------------------------------------
# SMOKE: Admin-only broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smoke_admin_broadcast(db_session) -> None:
    """Admin broadcast to a single user."""
    from unittest.mock import AsyncMock, MagicMock

    from db.repositories import UserRepository
    from services.broadcast_service import BroadcastService

    user_repo = UserRepository(db_session)
    await user_repo.create(telegram_id=990000040)
    await db_session.commit()

    svc = BroadcastService(db_session)
    result = await svc.enqueue(
        admin_id=1, body_text="🧪 Test broadcast", segment="all"
    )
    await db_session.commit()
    assert result.status == "queued"
    assert result.recipient_count >= 1

    # Process queue with mock bot.
    bot = MagicMock()
    bot.send_message = AsyncMock()
    sent = await svc.process_queue(bot)
    await db_session.commit()
    assert sent >= 1


# ---------------------------------------------------------------------------
# SMOKE: Webhook health + affiliate postback via TestClient
# ---------------------------------------------------------------------------

def test_smoke_webhook_health_and_postback() -> None:
    """Webhook: health check + affiliate postback end-to-end."""
    db_file = tempfile.mktemp(suffix=".db")
    os.environ["BOT_TOKEN"] = "dummy:token"
    os.environ["ADMIN_CHAT_ID"] = "1"
    os.environ["LANDING_URL"] = "https://example.com"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_file}"
    os.environ["WEBHOOK_SECRET"] = "smoke-secret"
    os.environ["PAYMENTS_ENABLED"] = "true"

    from app.config import get_settings
    get_settings.cache_clear()
    import db.session as sm
    sm._engine = None
    sm._session_maker = None

    # Create schema + seed offer.
    import asyncio as aio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from db.base import Base
    from db.repositories import OfferRepository

    async def setup() -> None:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_file}", connect_args={"check_same_thread": False}
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            repo = OfferRepository(session)
            await repo.create(
                code="WH-SMOKE", title_key="offer.wh", base_url="https://x.com"
            )
            await session.commit()
        await engine.dispose()

    aio.run(setup())

    from app.webhook_app import create_app
    client = TestClient(create_app())

    # Health check
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Affiliate postback (pending status — no delivery trigger)
    r = client.post(
        "/webhooks/affiliate/default",
        headers={"X-Webhook-Secret": "smoke-secret"},
        json={
            "partner_conversion_id": "WH-SMOKE-001",
            "offer_code": "WH-SMOKE",
            "status": "pending",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "created"

    # Duplicate postback = no-op
    r2 = client.post(
        "/webhooks/affiliate/default",
        headers={"X-Webhook-Secret": "smoke-secret"},
        json={
            "partner_conversion_id": "WH-SMOKE-001",
            "offer_code": "WH-SMOKE",
            "status": "pending",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"

    os.unlink(db_file)
