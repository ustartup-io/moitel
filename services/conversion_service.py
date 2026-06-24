"""Conversion tracking: postback/callback/manual sources with attribution.

Attribution rules (documented assumptions for MVP):
- Last-touch within a 30-day window.
- Self-referral blocked (owner == converter -> reject/flag).
- Dedup by partner_conversion_id UNIQUE; duplicate postback = no-op 200.
- Offer-specific override is a single optional field, not a framework.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from db.base import ConversionSource, ConversionStatus
from db.models import Click, Conversion, Offer, Referral
from db.repositories import ConversionRepository
from services.anti_fraud import AntiFraudService

log = get_logger("app.conversion")

ATTRIBUTION_WINDOW_DAYS = 30


class ConversionResult:
    """Outcome of a conversion attempt."""

    def __init__(
        self,
        conversion: Conversion | None,
        status: Literal["created", "duplicate", "blocked"],
        reason: str = "",
    ) -> None:
        self.conversion = conversion
        self.status = status
        self.reason = reason

    @property
    def is_duplicate(self) -> bool:
        return self.status == "duplicate"

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"


class ConversionService:
    """Handles conversion creation with attribution + dedup + anti-fraud."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conv_repo = ConversionRepository(session)
        self._anti_fraud = AntiFraudService(session)

    async def record_conversion(
        self,
        *,
        offer: Offer,
        partner_conversion_id: str,
        source: ConversionSource = ConversionSource.postback,
        amount: int | None = None,
        currency: str | None = None,
        status: ConversionStatus = ConversionStatus.pending,
        referral_code: str | None = None,
        converting_user_id: int | None = None,
    ) -> ConversionResult:
        """Record a conversion with full attribution + dedup.

        Returns ConversionResult with status:
        - "duplicate": partner_conversion_id already exists (no-op).
        - "blocked": self-referral or fraud.
        - "created": new conversion recorded.
        """
        # 1. Dedup by partner_conversion_id.
        existing = await self.conv_repo.get_by_partner_id(partner_conversion_id)
        if existing is not None:
            log.info(
                "conversion.duplicate",
                partner_conversion_id=partner_conversion_id,
                conversion_id=existing.id,
            )
            return ConversionResult(existing, "duplicate", "partner_conversion_id exists")

        # 2. Resolve referral for attribution.
        referral: Referral | None = None
        click: Click | None = None

        if referral_code:
            from db.repositories import ReferralRepository
            ref_repo = ReferralRepository(self.session)
            referral = await ref_repo.get_by_code(referral_code)

            if referral:
                # 3. Self-referral check.
                if converting_user_id and referral.owner_user_id == converting_user_id:
                    fraud = await self._anti_fraud.check_self_referral(
                        referral.owner_user_id, converting_user_id
                    )
                    if fraud.blocked:
                        log.warning(
                            "conversion.self_referral_blocked",
                            partner_conversion_id=partner_conversion_id,
                        )
                        return ConversionResult(None, "blocked", "self_referral")

                # 4. Last-touch attribution: find most recent click in window.
                click = await self._find_last_touch_click(
                    referral.id, converting_user_id
                )

        # 5. Create the conversion.
        conversion = await self.conv_repo.create(
            offer_id=offer.id,
            source=source,
            click_id=click.id if click else None,
            referral_id=referral.id if referral else None,
            user_id=converting_user_id,
            partner_conversion_id=partner_conversion_id,
            status=status,
            amount=amount,
            currency=currency,
        )
        log.info(
            "conversion.created",
            conversion_id=conversion.id,
            partner_conversion_id=partner_conversion_id,
            offer_id=offer.id,
            referral_id=referral.id if referral else None,
            source=source,
        )
        return ConversionResult(conversion, "created")

    async def update_status(
        self, conversion_id: int, status: ConversionStatus
    ) -> Conversion | None:
        """Update a conversion's status (pending -> approved/rejected)."""
        conv = await self.session.get(Conversion, conversion_id)
        if conv is None:
            return None
        conv.status = status
        await self.session.flush()
        log.info("conversion.status_updated", conversion_id=conversion_id, status=status)
        return conv

    async def _find_last_touch_click(
        self, referral_id: int, user_id: int | None
    ) -> Click | None:
        """Find the most recent click for a referral within the attribution window."""
        cutoff = datetime.now(UTC) - timedelta(days=ATTRIBUTION_WINDOW_DAYS)
        query = (
            select(Click)
            .where(Click.referral_id == referral_id, Click.created_at >= cutoff)
            .order_by(Click.created_at.desc())
            .limit(1)
        )
        if user_id is not None:
            query = query.where(Click.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalars().first()
