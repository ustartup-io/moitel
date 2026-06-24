"""Admin service: stats aggregation, offer management, manual confirms, exports.

Every state-changing action writes admin_audit_logs via AdminAuditLogRepository.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from db.base import (
    ConversionStatus,
    DeliveryStatus,
    OfferKind,
    PaymentStatus,
)
from db.models import Conversion, Delivery, Offer, Payment, User
from db.repositories import (
    AdminAuditLogRepository,
    OfferRepository,
    PaymentRepository,
)
from services.conversion_service import ConversionService
from services.payment_service import PaymentService
from services.stats_service import StatsService

log = get_logger("app.admin")


class AdminService:
    """Admin operations: stats, offers, manual confirms, exports."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stats = StatsService(session)
        self.audit = AdminAuditLogRepository(session)
        self.offer_repo = OfferRepository(session)
        self.pay_repo = PaymentRepository(session)

    async def get_dashboard_stats(self) -> dict[str, Any]:
        """Return all dashboard stats in one call."""
        click_stats = await self.stats.global_click_stats()
        conv_stats = await self.stats.global_conversion_stats()
        user_count = await self.session.scalar(select(func.count(User.id)))
        payment_count = await self.session.scalar(
            select(func.count(Payment.id)).where(Payment.status == PaymentStatus.paid)
        )
        delivery_count = await self.session.scalar(
            select(func.count(Delivery.id)).where(Delivery.status == DeliveryStatus.sent)
        )
        active_offers = await self.session.scalar(
            select(func.count(Offer.id)).where(Offer.is_active.is_(True))
        )
        return {
            "users": user_count or 0,
            "clicks": click_stats["total_clicks"],
            "conversions": conv_stats,
            "paid_payments": payment_count or 0,
            "delivered": delivery_count or 0,
            "active_offers": active_offers or 0,
        }

    async def list_offers(self) -> list[Offer]:
        """List all offers."""
        result = await self.session.execute(select(Offer).order_by(Offer.id))
        return list(result.scalars().all())

    async def add_offer(
        self,
        *,
        admin_id: int,
        code: str,
        title_key: str,
        base_url: str,
        kind: OfferKind = OfferKind.affiliate_link,
        requires_payment: bool = False,
        price_amount: int | None = None,
        price_currency: str | None = None,
    ) -> Offer:
        """Add a new offer (audited)."""
        offer = await self.offer_repo.create(
            code=code,
            title_key=title_key,
            base_url=base_url,
            kind=kind,
            requires_payment=requires_payment,
            price_amount=price_amount,
            price_currency=price_currency,
        )
        await self.audit.create(
            admin_id=admin_id,
            action="offer.add",
            target_type="offer",
            target_id=str(offer.id),
            meta_json=f'{{"code": "{code}"}}',
        )
        log.info("admin.offer_added", offer_id=offer.id, code=code, admin_id=admin_id)
        return offer

    async def toggle_offer(self, *, admin_id: int, offer_id: int) -> Offer | None:
        """Toggle an offer's active status (audited)."""
        offer = await self.session.get(Offer, offer_id)
        if offer is None:
            return None
        offer.is_active = not offer.is_active
        await self.session.flush()
        await self.audit.create(
            admin_id=admin_id,
            action="offer.toggle",
            target_type="offer",
            target_id=str(offer_id),
            meta_json=f'{{"is_active": {offer.is_active}}}',
        )
        log.info("admin.offer_toggled", offer_id=offer_id, is_active=offer.is_active)
        return offer

    async def manual_confirm_payment(self, *, admin_id: int, payment_id: int) -> Payment | None:
        """Manually confirm a payment (audited, idempotent)."""
        pay_service = PaymentService(self.session)
        payment = await pay_service.manual_confirm(payment_id, admin_id)
        if payment:
            await self.audit.create(
                admin_id=admin_id,
                action="payment.manual_confirm",
                target_type="payment",
                target_id=str(payment_id),
            )
        return payment

    async def manual_confirm_conversion(
        self,
        *,
        admin_id: int,
        conversion_id: int,
        status: ConversionStatus = ConversionStatus.approved,
    ) -> Conversion | None:
        """Manually approve/reject a conversion (audited)."""
        conv_service = ConversionService(self.session)
        conversion = await conv_service.update_status(conversion_id, status)
        if conversion:
            await self.audit.create(
                admin_id=admin_id,
                action="conversion.manual_confirm",
                target_type="conversion",
                target_id=str(conversion_id),
                meta_json=f'{{"status": "{status}"}}',
            )
        return conversion

    async def export_conversions_csv(self) -> str:
        """Export conversions as CSV string."""
        result = await self.session.execute(
            select(Conversion).order_by(Conversion.id)
        )
        conversions = list(result.scalars().all())

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["id", "offer_id", "referral_id", "user_id", "status", "amount",
             "currency", "source", "partner_conversion_id", "created_at"]
        )
        for c in conversions:
            writer.writerow([
                c.id, c.offer_id, c.referral_id, c.user_id, c.status,
                c.amount, c.currency, c.source, c.partner_conversion_id, c.created_at,
            ])
        return output.getvalue()

    async def export_payments_csv(self) -> str:
        """Export payments as CSV string."""
        result = await self.session.execute(select(Payment).order_by(Payment.id))
        payments = list(result.scalars().all())

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["id", "user_id", "offer_id", "provider", "amount", "currency",
             "status", "provider_invoice_id", "paid_at", "created_at"]
        )
        for p in payments:
            writer.writerow([
                p.id, p.user_id, p.offer_id, p.provider, p.amount, p.currency,
                p.status, p.provider_invoice_id, p.paid_at, p.created_at,
            ])
        return output.getvalue()
