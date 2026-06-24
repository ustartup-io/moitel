"""Auto-delivery service: delivers digital access after payment or conversion.

Delivery types: external_link, access_link, file_ref, access_code, text.

Key rules:
- dedupe_key (user+offer+payment/conversion) UNIQUE prevents double delivery.
- If a delivery row already 'sent', the operation is a no-op.
- Record attempts + last_error; on success set status=sent, sent_at.
- Sensitive payloads are NEVER logged (encryption-at-rest is a TODO).

Trigger points:
  (a) approved conversion for affiliate offers.
  (b) paid payment for paid-access offers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import alert_admin, get_logger
from db.base import DeliveryStatus
from db.models import Conversion, Delivery, Offer, Payment
from db.repositories import DeliveryRepository

log = get_logger("app.delivery")


@dataclass
class DeliveryResult:
    """Outcome of a delivery attempt."""

    delivery: Delivery | None
    status: Literal["delivered", "skipped", "duplicate", "failed"]
    reason: str = ""


class DeliveryService:
    """Handles auto-delivery with dedup and retry."""

    MAX_RETRIES = 5

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.delivery_repo = DeliveryRepository(session)

    async def deliver_for_payment(self, payment: Payment) -> DeliveryResult:
        """Deliver after a paid payment."""
        dedupe_key = f"pay:{payment.user_id}:{payment.offer_id}:{payment.id}"
        return await self._deliver(
            user_id=payment.user_id,
            offer_id=payment.offer_id,
            delivery_trigger=dedupe_key,
            payment_id=payment.id,
        )

    async def deliver_for_conversion(self, conversion: Conversion) -> DeliveryResult:
        """Deliver after an approved conversion."""
        dedupe_key = f"conv:{conversion.user_id}:{conversion.offer_id}:{conversion.id}"
        return await self._deliver(
            user_id=conversion.user_id or 0,
            offer_id=conversion.offer_id,
            delivery_trigger=dedupe_key,
            conversion_id=conversion.id,
        )

    async def retry_failed(self, delivery: Delivery) -> DeliveryResult:
        """Retry a failed delivery (with attempt increment + cap check)."""
        if delivery.attempts >= self.MAX_RETRIES:
            log.error(
                "delivery.max_retries_exceeded",
                delivery_id=delivery.id,
                attempts=delivery.attempts,
            )
            alert_admin(
                f"Delivery {delivery.id} exceeded {self.MAX_RETRIES} retries",
                delivery_id=delivery.id,
                attempts=delivery.attempts,
            )
            return DeliveryResult(delivery, "failed", "max_retries_exceeded")

        # Increment attempt counter.
        await self.delivery_repo.increment_attempts(delivery.id)

        # Fetch the offer to get delivery payload.
        offer = await self.session.get(Offer, delivery.offer_id)
        if offer is None:
            return DeliveryResult(delivery, "failed", "offer_not_found")

        # Attempt to "send" (in MVP, sending = marking as sent).
        return await self._send(delivery, offer)

    async def _deliver(
        self,
        *,
        user_id: int,
        offer_id: int,
        delivery_trigger: str,
        payment_id: int | None = None,
        conversion_id: int | None = None,
    ) -> DeliveryResult:
        """Core delivery logic with dedup check."""
        # Check for existing delivery by dedupe_key.
        existing = await self.delivery_repo.get_by_dedupe_key(delivery_trigger)
        if existing is not None:
            if existing.status == DeliveryStatus.sent:
                log.info("delivery.already_sent", delivery_id=existing.id)
                return DeliveryResult(existing, "skipped", "already_sent")
            if existing.status == DeliveryStatus.pending:
                # Resume a pending delivery.
                offer = await self.session.get(Offer, offer_id)
                if offer is None:
                    return DeliveryResult(existing, "failed", "offer_not_found")
                return await self._send(existing, offer)
            # Failed: return as-is (retry handled by job).
            return DeliveryResult(existing, "duplicate", "existing_failed")

        # Fetch the offer to determine delivery type.
        offer = await self.session.get(Offer, offer_id)
        if offer is None:
            return DeliveryResult(None, "failed", "offer_not_found")

        # Create the delivery record.
        delivery = await self.delivery_repo.create(
            user_id=user_id,
            offer_id=offer_id,
            delivery_type=offer.delivery_type,
            dedupe_key=delivery_trigger,
            payment_id=payment_id,
            conversion_id=conversion_id,
        )

        log.info(
            "delivery.created",
            delivery_id=delivery.id,
            user_id=user_id,
            offer_id=offer_id,
            delivery_type=offer.delivery_type,
        )

        # Attempt to send immediately.
        return await self._send(delivery, offer)

    async def _send(self, delivery: Delivery, offer: Offer) -> DeliveryResult:
        """Perform the actual delivery (mark as sent).

        In MVP, 'sending' means marking status=sent. The actual delivery content
        (external link, access code, etc.) is read from offer.delivery_payload.
        NEVER log the payload contents.

        TODO(M-later): integrate with bot.send_message to deliver content to user.
        TODO(M-later): encrypt offer.delivery_payload at rest.
        """
        try:
            # MVP: mark as sent. Real delivery (send_message) added later.
            await self.delivery_repo.mark_sent(delivery.id)
            log.info("delivery.sent", delivery_id=delivery.id, user_id=delivery.user_id)
            return DeliveryResult(delivery, "delivered")
        except Exception as exc:
            await self.delivery_repo.mark_failed(delivery.id, str(exc))
            log.error("delivery.failed", delivery_id=delivery.id, error=str(exc))
            return DeliveryResult(delivery, "failed", str(exc))
