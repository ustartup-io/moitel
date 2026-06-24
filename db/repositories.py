"""Minimal repository per aggregate.

Convention: repositories NEVER commit. The service layer owns the transaction
boundary (calls `await session.commit()` after repo operations). This keeps
test boundaries clean and avoids premature commits.

Each repository takes an AsyncSession in its constructor.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import (
    ClickSource,
    ConversionSource,
    ConversionStatus,
    DeliveryStatus,
    DeliveryType,
    Lang,
    OfferKind,
    PaymentProvider,
    PaymentStatus,
    SupportState,
    UserStatus,
    WebhookStatus,
)
from db.models import (
    AdminAuditLog,
    Broadcast,
    BroadcastRecipient,
    Click,
    Conversion,
    Delivery,
    Offer,
    Payment,
    Referral,
    SupportRequest,
    User,
    WebhookEvent,
)


class Repository:
    """Base: just holds the session. No commit here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class UserRepository(Repository):
    async def create(
        self, *, telegram_id: int, username: str | None = None, lang: Lang = Lang.en
    ) -> User:
        user = User(id=telegram_id, username=username, lang=lang)
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.id == telegram_id))
        return result.scalar_one_or_none()

    async def update_status(self, telegram_id: int, status: UserStatus) -> None:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            user.status = status
            await self.session.flush()

    async def set_lang(self, telegram_id: int, lang: Lang) -> User | None:
        """Set only the user's language."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            return None
        user.lang = lang
        await self.session.flush()
        return user

    async def set_compliance(
        self,
        *,
        telegram_id: int,
        lang: Lang | None = None,
        jurisdiction_code: str | None = None,
        age_confirmed: bool | None = None,
        terms_accepted: bool | None = None,
        marketing_opt_in: bool | None = None,
    ) -> User | None:
        """Partially update compliance fields. Only sets fields that are not None."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            return None
        now = datetime.now(UTC)
        if lang is not None:
            user.lang = lang
        if jurisdiction_code is not None:
            user.jurisdiction_code = jurisdiction_code
            user.jurisdiction_attested_at = now
        if age_confirmed:
            user.age_confirmed_at = now
        if terms_accepted:
            user.terms_accepted_at = now
        if marketing_opt_in is not None:
            user.marketing_opt_in = marketing_opt_in
        await self.session.flush()
        return user


class OfferRepository(Repository):
    async def create(
        self,
        *,
        code: str,
        title_key: str,
        base_url: str,
        kind: OfferKind = OfferKind.affiliate_link,
        requires_payment: bool = False,
        price_amount: int | None = None,
        price_currency: str | None = None,
        delivery_type: DeliveryType = DeliveryType.external_link,
        delivery_payload: str | None = None,
        jurisdiction_allowlist: str | None = None,
        is_active: bool = True,
    ) -> Offer:
        offer = Offer(
            code=code,
            title_key=title_key,
            base_url=base_url,
            kind=kind,
            requires_payment=requires_payment,
            price_amount=price_amount,
            price_currency=price_currency,
            delivery_type=delivery_type,
            delivery_payload=delivery_payload,
            jurisdiction_allowlist=jurisdiction_allowlist,
            is_active=is_active,
        )
        self.session.add(offer)
        await self.session.flush()
        return offer

    async def get_by_code(self, code: str) -> Offer | None:
        result = await self.session.execute(select(Offer).where(Offer.code == code))
        return result.scalar_one_or_none()

    async def get_active(self) -> list[Offer]:
        result = await self.session.execute(
            select(Offer).where(Offer.is_active.is_(True)).order_by(Offer.id)
        )
        return list(result.scalars().all())


class ReferralRepository(Repository):
    async def create(
        self, *, owner_user_id: int, code: str, offer_id: int | None = None
    ) -> Referral:
        referral = Referral(owner_user_id=owner_user_id, code=code, offer_id=offer_id)
        self.session.add(referral)
        await self.session.flush()
        return referral

    async def get_by_code(self, code: str) -> Referral | None:
        result = await self.session.execute(select(Referral).where(Referral.code == code))
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_user_id: int) -> list[Referral]:
        result = await self.session.execute(
            select(Referral).where(Referral.owner_user_id == owner_user_id)
        )
        return list(result.scalars().all())


class ClickRepository(Repository):
    async def create(
        self,
        *,
        offer_id: int,
        referral_id: int | None = None,
        user_id: int | None = None,
        source: ClickSource = ClickSource.telegram,
        ip_hash: str | None = None,
        ua_hash: str | None = None,
    ) -> Click:
        click = Click(
            offer_id=offer_id,
            referral_id=referral_id,
            user_id=user_id,
            source=source,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )
        self.session.add(click)
        await self.session.flush()
        return click


class ConversionRepository(Repository):
    async def create(
        self,
        *,
        offer_id: int,
        source: ConversionSource,
        click_id: int | None = None,
        referral_id: int | None = None,
        user_id: int | None = None,
        partner_conversion_id: str | None = None,
        status: ConversionStatus = ConversionStatus.pending,
        amount: int | None = None,
        currency: str | None = None,
    ) -> Conversion:
        conversion = Conversion(
            offer_id=offer_id,
            source=source,
            click_id=click_id,
            referral_id=referral_id,
            user_id=user_id,
            partner_conversion_id=partner_conversion_id,
            status=status,
            amount=amount,
            currency=currency,
        )
        self.session.add(conversion)
        await self.session.flush()
        return conversion

    async def get_by_partner_id(self, partner_conversion_id: str) -> Conversion | None:
        result = await self.session.execute(
            select(Conversion).where(Conversion.partner_conversion_id == partner_conversion_id)
        )
        return result.scalar_one_or_none()


class PaymentRepository(Repository):
    async def create(
        self,
        *,
        user_id: int,
        offer_id: int,
        provider: PaymentProvider,
        idempotency_key: str,
        amount: int,
        currency: str,
        provider_invoice_id: str | None = None,
        status: PaymentStatus = PaymentStatus.created,
    ) -> Payment:
        payment = Payment(
            user_id=user_id,
            offer_id=offer_id,
            provider=provider,
            idempotency_key=idempotency_key,
            amount=amount,
            currency=currency,
            provider_invoice_id=provider_invoice_id,
            status=status,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def mark_paid(
        self, payment_id: int, provider_invoice_id: str | None = None
    ) -> Payment | None:
        payment = await self.session.get(Payment, payment_id)
        if payment is None:
            return None
        payment.status = PaymentStatus.paid
        payment.paid_at = datetime.now(UTC)
        if provider_invoice_id is not None:
            payment.provider_invoice_id = provider_invoice_id
        await self.session.flush()
        return payment

    async def get_pending(self) -> list[Payment]:
        """Return all payments in pending or created status (for polling)."""
        result = await self.session.execute(
            select(Payment)
            .where(Payment.status.in_([PaymentStatus.pending, PaymentStatus.created]))
            .order_by(Payment.id)
        )
        return list(result.scalars().all())

    async def mark_expired(self, payment_id: int) -> Payment | None:
        payment = await self.session.get(Payment, payment_id)
        if payment is None:
            return None
        payment.status = PaymentStatus.expired
        await self.session.flush()
        return payment

    async def mark_failed(self, payment_id: int) -> Payment | None:
        payment = await self.session.get(Payment, payment_id)
        if payment is None:
            return None
        payment.status = PaymentStatus.failed
        await self.session.flush()
        return payment

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return await self.session.get(Payment, payment_id)


class DeliveryRepository(Repository):
    async def create(
        self,
        *,
        user_id: int,
        offer_id: int,
        delivery_type: DeliveryType,
        dedupe_key: str,
        payment_id: int | None = None,
        conversion_id: int | None = None,
    ) -> Delivery:
        delivery = Delivery(
            user_id=user_id,
            offer_id=offer_id,
            delivery_type=delivery_type,
            dedupe_key=dedupe_key,
            payment_id=payment_id,
            conversion_id=conversion_id,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def get_by_dedupe_key(self, dedupe_key: str) -> Delivery | None:
        result = await self.session.execute(
            select(Delivery).where(Delivery.dedupe_key == dedupe_key)
        )
        return result.scalar_one_or_none()

    async def mark_sent(self, delivery_id: int) -> Delivery | None:
        delivery = await self.session.get(Delivery, delivery_id)
        if delivery is None:
            return None
        delivery.status = DeliveryStatus.sent
        delivery.sent_at = datetime.now(UTC)
        await self.session.flush()
        return delivery

    async def mark_failed(self, delivery_id: int, error: str) -> Delivery | None:
        delivery = await self.session.get(Delivery, delivery_id)
        if delivery is None:
            return None
        delivery.status = DeliveryStatus.failed
        delivery.last_error = error
        await self.session.flush()
        return delivery

    async def increment_attempts(self, delivery_id: int, error: str | None = None) -> Delivery | None:
        delivery = await self.session.get(Delivery, delivery_id)
        if delivery is None:
            return None
        delivery.attempts += 1
        if error:
            delivery.last_error = error
        await self.session.flush()
        return delivery

    async def get_failed(self) -> list[Delivery]:
        """Return deliveries in failed status that haven't exceeded retry cap."""
        result = await self.session.execute(
            select(Delivery)
            .where(Delivery.status == DeliveryStatus.failed)
            .where(Delivery.attempts < 5)
            .order_by(Delivery.id)
        )
        return list(result.scalars().all())


class SupportRepository(Repository):
    async def create(
        self,
        *,
        user_id: int,
        lang: Lang,
        category: str | None = None,
        last_message: str | None = None,
    ) -> SupportRequest:
        sr = SupportRequest(
            user_id=user_id, lang=lang, category=category, last_message=last_message
        )
        self.session.add(sr)
        await self.session.flush()
        return sr

    async def get_open_for_user(self, user_id: int) -> SupportRequest | None:
        result = await self.session.execute(
            select(SupportRequest)
            .where(SupportRequest.user_id == user_id)
            .where(SupportRequest.state.in_([SupportState.open, SupportState.answered]))
            .order_by(SupportRequest.id.desc())
        )
        return result.scalars().first()


class WebhookEventRepository(Repository):
    async def create(
        self,
        *,
        provider: str,
        dedupe_hash: str,
        payload_json: str,
        external_event_id: str | None = None,
        status: WebhookStatus = WebhookStatus.received,
    ) -> WebhookEvent:
        event = WebhookEvent(
            provider=provider,
            dedupe_hash=dedupe_hash,
            payload_json=payload_json,
            external_event_id=external_event_id,
            status=status,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_by_dedupe_hash(self, dedupe_hash: str) -> WebhookEvent | None:
        result = await self.session.execute(
            select(WebhookEvent).where(WebhookEvent.dedupe_hash == dedupe_hash)
        )
        return result.scalar_one_or_none()

    async def mark_processed(self, event_id: int) -> WebhookEvent | None:
        event = await self.session.get(WebhookEvent, event_id)
        if event is None:
            return None
        event.status = WebhookStatus.processed
        event.processed_at = datetime.now(UTC)
        await self.session.flush()
        return event


class BroadcastRepository(Repository):
    """Repository for broadcasts + recipients (used in Step 7)."""

    async def create_broadcast(
        self, *, admin_id: int, body_key_or_text: str, segment: str
    ) -> Broadcast:
        bc = Broadcast(
            admin_id=admin_id,
            body_key_or_text=body_key_or_text,
            segment=segment,
        )
        self.session.add(bc)
        await self.session.flush()
        return bc

    async def add_recipients(self, broadcast_id: int, user_ids: list[int]) -> None:
        for uid in user_ids:
            recipient = BroadcastRecipient(broadcast_id=broadcast_id, user_id=uid)
            self.session.add(recipient)
        await self.session.flush()


class AdminAuditLogRepository(Repository):
    """Repository for admin audit logs."""

    async def create(
        self, *, admin_id: int, action: str, target_type: str | None = None,
        target_id: str | None = None, meta_json: str | None = None,
    ) -> AdminAuditLog:
        log_entry = AdminAuditLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta_json=meta_json,
        )
        self.session.add(log_entry)
        await self.session.flush()
        return log_entry
