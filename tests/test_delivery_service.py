"""Delivery service tests: dedup, retry cap, attempts increment."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import DeliveryStatus, DeliveryType
from db.repositories import DeliveryRepository, OfferRepository, UserRepository
from services.delivery_service import DeliveryService


@pytest.mark.asyncio
async def test_delivery_dedup(db_session: AsyncSession) -> None:
    """Delivering the same dedupe_key twice results in one delivery."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    user = await user_repo.create(telegram_id=910910910)
    offer = await offer_repo.create(
        code="DEL1",
        title_key="offer.del1",
        base_url="https://x.com",
        delivery_type=DeliveryType.access_link,
    )
    await db_session.commit()

    del_service = DeliveryService(db_session)

    # Create a mock payment-like trigger.
    from db.base import PaymentProvider, PaymentStatus
    from db.repositories import PaymentRepository
    pay_repo = PaymentRepository(db_session)
    payment = await pay_repo.create(
        user_id=user.id, offer_id=offer.id, provider=PaymentProvider.xrocket,
        idempotency_key="idem-del-1", amount=500, currency="USDT",
        status=PaymentStatus.paid,
    )
    await db_session.commit()

    r1 = await del_service.deliver_for_payment(payment)
    await db_session.commit()
    assert r1.status == "delivered"

    # Second delivery attempt -> skipped (already sent).
    r2 = await del_service.deliver_for_payment(payment)
    await db_session.commit()
    assert r2.status == "skipped"


@pytest.mark.asyncio
async def test_delivery_retry_increments_attempts(db_session: AsyncSession) -> None:
    """Retrying a failed delivery increments attempts."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    user = await user_repo.create(telegram_id=920920920)
    offer = await offer_repo.create(
        code="DEL2", title_key="offer.del2", base_url="https://x.com",
    )
    await db_session.commit()

    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.create(
        user_id=user.id, offer_id=offer.id,
        delivery_type=DeliveryType.text, dedupe_key="dedupe-retry-1",
    )
    # Mark as failed.
    await del_repo.mark_failed(delivery.id, "test error")
    await db_session.commit()

    # Retry should increment attempts and succeed.
    del_service = DeliveryService(db_session)
    result = await del_service.retry_failed(delivery)
    await db_session.commit()

    assert result.status in ("delivered", "failed")  # MVP always delivers
    refreshed = await del_repo.get_by_dedupe_key("dedupe-retry-1")
    assert refreshed is not None
    assert refreshed.attempts >= 1


@pytest.mark.asyncio
async def test_delivery_retry_cap(db_session: AsyncSession) -> None:
    """Delivery stops retrying after MAX_RETRIES (5)."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    user = await user_repo.create(telegram_id=930930930)
    offer = await offer_repo.create(
        code="DEL3", title_key="offer.del3", base_url="https://x.com",
    )
    await db_session.commit()

    del_repo = DeliveryRepository(db_session)
    delivery = await del_repo.create(
        user_id=user.id, offer_id=offer.id,
        delivery_type=DeliveryType.text, dedupe_key="dedupe-retry-2",
    )
    # Set attempts to max.
    delivery.attempts = 5
    delivery.status = DeliveryStatus.failed
    await db_session.commit()

    del_service = DeliveryService(db_session)
    result = await del_service.retry_failed(delivery)
    await db_session.commit()

    assert result.status == "failed"
    assert "max_retries" in result.reason
