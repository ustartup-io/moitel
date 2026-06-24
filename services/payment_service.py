"""Payment service: invoice creation, confirmation, status machine.

Status machine: created -> pending -> paid | expired | failed

Confirmation paths:
  - Primary: payment webhook (app/webhook_app.py) -> confirm_payment()
  - Fallback: polling job -> poll_payment()
  - Emergency: admin manual confirm -> manual_confirm()

All confirmation paths are idempotent: paid payments cannot be re-transitioned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_conf import get_logger
from db.base import PaymentProvider, PaymentStatus
from db.models import Offer, Payment, User
from db.repositories import PaymentRepository
from services.delivery_service import DeliveryService
from services.xrocket_client import MockXRocketClient, XRocketClient, XRocketError
from utils.security import generate_idempotency_key

log = get_logger("app.payment")


@dataclass
class PaymentResult:
    """Outcome of a payment operation."""

    payment: Payment | None
    status: Literal["created", "duplicate", "error"]
    pay_url: str | None = None
    reason: str = ""


class PaymentService:
    """Handles invoice creation and payment confirmation."""

    def __init__(
        self,
        session: AsyncSession,
        xrocket_client: XRocketClient | MockXRocketClient | None = None,
    ) -> None:
        self.session = session
        self.pay_repo = PaymentRepository(session)
        self._xrocket = xrocket_client

    def _get_xrocket_client(self) -> XRocketClient | MockXRocketClient:
        """Return the xRocket client (lazy init or injected mock)."""
        if self._xrocket is not None:
            return self._xrocket
        return XRocketClient()

    async def create_invoice(self, *, user: User, offer: Offer) -> PaymentResult:
        """Create a payment + xRocket invoice for a paid-access offer."""
        settings = get_settings()
        if not settings.payments_enabled:
            return PaymentResult(None, "error", reason="Payments not enabled")

        if not offer.requires_payment:
            return PaymentResult(None, "error", reason="Offer does not require payment")

        # Idempotency: check if a non-terminal payment already exists for this user+offer.
        idem_key = generate_idempotency_key("xr", user.id, offer.id)
        existing = await self.pay_repo.get_by_idempotency_key(idem_key)
        if existing and existing.status in (PaymentStatus.created, PaymentStatus.pending):
            log.info("payment.duplicate_pending", payment_id=existing.id)
            return PaymentResult(existing, "duplicate")

        # Create the payment row.
        amount = offer.price_amount or 0
        currency = offer.price_currency or "USDT"
        payment = await self.pay_repo.create(
            user_id=user.id,
            offer_id=offer.id,
            provider=PaymentProvider.xrocket,
            idempotency_key=idem_key,
            amount=amount,
            currency=currency,
        )

        # Create the xRocket invoice.
        client = self._get_xrocket_client()
        try:
            invoice = await client.create_invoice(
                amount=str(amount),
                currency=currency,
                payload=str(payment.id),
                description=f"Access: {offer.code}",
                callback_url=settings.webhook_base_url.rstrip("/") + "/webhooks/payments/xrocket"
                if settings.webhook_base_url
                else None,
            )
        except XRocketError as exc:
            log.error("payment.invoice_failed", payment_id=payment.id, error=str(exc))
            await self.pay_repo.mark_failed(payment.id)
            return PaymentResult(payment, "error", reason=str(exc))

        # Update payment with provider invoice ID + transition to pending.
        payment.provider_invoice_id = invoice.id
        payment.status = PaymentStatus.pending
        await self.session.flush()

        log.info(
            "payment.invoice_created",
            payment_id=payment.id,
            provider_invoice_id=invoice.id,
            amount=amount,
            currency=currency,
        )
        return PaymentResult(payment, "created", pay_url=invoice.pay_url)

    async def confirm_payment(
        self, *, provider_invoice_id: str, payment_id_from_payload: int | None = None
    ) -> Payment | None:
        """Transition a payment to 'paid' (idempotent). Triggers delivery.

        This is the primary confirmation path (via webhook).
        """
        payment = await self._find_payment(provider_invoice_id, payment_id_from_payload)
        if payment is None:
            log.warning("payment.not_found", provider_invoice_id=provider_invoice_id)
            return None

        # Idempotency: already paid -> no-op.
        if payment.status == PaymentStatus.paid:
            log.info("payment.already_paid", payment_id=payment.id)
            return payment

        # Transition to paid.
        await self.pay_repo.mark_paid(payment.id, provider_invoice_id)

        log.info("payment.confirmed", payment_id=payment.id, amount=payment.amount)

        # Trigger delivery.
        delivery_service = DeliveryService(self.session)
        await delivery_service.deliver_for_payment(payment)

        return payment

    async def poll_payment(self, payment: Payment) -> Payment | None:
        """Poll xRocket for payment status (fallback confirmation path)."""
        if payment.status in (PaymentStatus.paid, PaymentStatus.expired, PaymentStatus.failed):
            return payment  # terminal, skip

        if not payment.provider_invoice_id:
            return payment

        client = self._get_xrocket_client()
        try:
            invoice = await client.get_invoice(payment.provider_invoice_id)
        except XRocketError as exc:
            log.warning("payment.poll_failed", payment_id=payment.id, error=str(exc))
            return payment

        if invoice.status == "paid":
            return await self.confirm_payment(
                provider_invoice_id=payment.provider_invoice_id,
                payment_id_from_payload=payment.id,
            )
        if invoice.status == "expired":
            await self.pay_repo.mark_expired(payment.id)
            log.info("payment.expired", payment_id=payment.id)

        return payment

    async def manual_confirm(self, payment_id: int, admin_id: int) -> Payment | None:
        """Admin manual confirmation (emergency path)."""
        payment = await self.pay_repo.get_by_id(payment_id)
        if payment is None:
            return None

        if payment.status == PaymentStatus.paid:
            return payment

        log.info("payment.manual_confirmed", payment_id=payment_id, admin_id=admin_id)
        return await self.confirm_payment(
            provider_invoice_id=payment.provider_invoice_id or f"manual-{payment_id}",
            payment_id_from_payload=payment_id,
        )

    async def _find_payment(
        self, provider_invoice_id: str, payment_id_from_payload: int | None
    ) -> Payment | None:
        """Find a payment by payload ID (our internal ID) or provider invoice ID."""
        if payment_id_from_payload:
            payment = await self.pay_repo.get_by_id(payment_id_from_payload)
            if payment:
                return payment
        # Fallback: search by provider_invoice_id.
        from sqlalchemy import select as sa_select
        result = await self.session.execute(
            sa_select(Payment).where(Payment.provider_invoice_id == provider_invoice_id)
        )
        return result.scalar_one_or_none()
