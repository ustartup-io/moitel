"""Payment service tests with MOCKED xRocket client.

Scenarios:
- create invoice -> simulate paid callback -> delivery created once -> second callback no-op
- expired invoice -> no delivery
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import DeliveryStatus, OfferKind, PaymentStatus
from db.repositories import DeliveryRepository, OfferRepository, UserRepository
from services.payment_service import PaymentService
from services.xrocket_client import MockXRocketClient


async def _create_paid_offer(db_session: AsyncSession):
    """Helper: create a user + a paid-access offer."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)
    user = await user_repo.create(telegram_id=900900901)
    offer = await offer_repo.create(
        code="PAID1",
        title_key="offer.paid1",
        base_url="https://x.com",
        kind=OfferKind.paid_access,
        requires_payment=True,
        price_amount=1000,
        price_currency="USDT",
    )
    return user, offer


@pytest.mark.asyncio
async def test_create_invoice(db_session: AsyncSession) -> None:
    """Creating an invoice returns a payment row with provider_invoice_id."""
    user, offer = await _create_paid_offer(db_session)
    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)

    result = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()

    assert result.status == "created"
    assert result.payment is not None
    assert result.payment.provider_invoice_id is not None
    assert result.payment.status == PaymentStatus.pending
    assert result.pay_url is not None


@pytest.mark.asyncio
async def test_paid_callback_triggers_delivery_once(db_session: AsyncSession) -> None:
    """Pay -> confirm -> delivery created. Second confirm is a no-op."""
    user, offer = await _create_paid_offer(db_session)
    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)

    # Create invoice.
    result = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()
    assert result.payment is not None
    payment = result.payment

    # Simulate paid callback (first time).
    confirmed = await pay_service.confirm_payment(
        provider_invoice_id=payment.provider_invoice_id or "",
        payment_id_from_payload=payment.id,
    )
    await db_session.commit()
    assert confirmed is not None
    assert confirmed.status == PaymentStatus.paid

    # Delivery should exist.
    del_repo = DeliveryRepository(db_session)
    deliveries = await del_repo.get_by_dedupe_key(
        f"pay:{user.id}:{offer.id}:{payment.id}"
    )
    assert deliveries is not None
    assert deliveries.status == DeliveryStatus.sent

    # Second identical callback -> no-op (payment already paid).
    confirmed2 = await pay_service.confirm_payment(
        provider_invoice_id=payment.provider_invoice_id or "",
        payment_id_from_payload=payment.id,
    )
    await db_session.commit()
    assert confirmed2 is not None
    assert confirmed2.status == PaymentStatus.paid

    # Still only one delivery (no double delivery).
    deliveries2 = await del_repo.get_by_dedupe_key(
        f"pay:{user.id}:{offer.id}:{payment.id}"
    )
    assert deliveries2.id == deliveries.id


@pytest.mark.asyncio
async def test_expired_invoice_no_delivery(db_session: AsyncSession) -> None:
    """Expired invoice transitions to expired and no delivery occurs."""
    user, offer = await _create_paid_offer(db_session)
    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)

    result = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()
    assert result.payment is not None
    payment = result.payment

    # Simulate expired via polling.
    mock.simulate_expired(payment.provider_invoice_id or "")
    polled = await pay_service.poll_payment(payment)
    await db_session.commit()

    assert polled is not None
    assert polled.status == PaymentStatus.expired

    # No delivery should exist.
    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.get_by_dedupe_key(
        f"pay:{user.id}:{offer.id}:{payment.id}"
    )
    assert delivery is None


@pytest.mark.asyncio
async def test_polling_confirms_paid(db_session: AsyncSession) -> None:
    """Polling detects a paid invoice and confirms + delivers."""
    user, offer = await _create_paid_offer(db_session)
    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)

    result = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()
    payment = result.payment
    assert payment is not None

    # Simulate provider marking as paid.
    mock.simulate_paid(payment.provider_invoice_id or "")
    polled = await pay_service.poll_payment(payment)
    await db_session.commit()

    assert polled is not None
    assert polled.status == PaymentStatus.paid


@pytest.mark.asyncio
async def test_manual_confirm(db_session: AsyncSession) -> None:
    """Admin manual confirmation works."""
    user, offer = await _create_paid_offer(db_session)
    mock = MockXRocketClient()
    pay_service = PaymentService(db_session, xrocket_client=mock)

    result = await pay_service.create_invoice(user=user, offer=offer)
    await db_session.commit()
    payment = result.payment
    assert payment is not None

    manually = await pay_service.manual_confirm(payment.id, admin_id=1)
    await db_session.commit()

    assert manually is not None
    assert manually.status == PaymentStatus.paid
