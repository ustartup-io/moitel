"""Stats service: aggregate queries for admin visibility (UI in Step 7)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import ConversionStatus
from db.models import Click, Conversion, Referral


class StatsService:
    """Returns aggregate stats for dashboards and admin views."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def referral_stats(self, owner_user_id: int) -> dict[str, int]:
        """Per-user referral stats."""
        referrals = await self.session.scalar(
            select(func.count(Referral.id)).where(Referral.owner_user_id == owner_user_id)
        )
        ref_ids_subq = select(Referral.id).where(Referral.owner_user_id == owner_user_id)
        clicks = await self.session.scalar(
            select(func.count(Click.id)).where(Click.referral_id.in_(ref_ids_subq))
        )
        conversions = await self.session.scalar(
            select(func.count(Conversion.id)).where(
                Conversion.referral_id.in_(ref_ids_subq)
            )
        )
        approved = await self.session.scalar(
            select(func.count(Conversion.id)).where(
                Conversion.referral_id.in_(ref_ids_subq),
                Conversion.status == ConversionStatus.approved,
            )
        )
        return {
            "referrals": referrals or 0,
            "clicks": clicks or 0,
            "conversions": conversions or 0,
            "approved": approved or 0,
        }

    async def global_click_stats(self) -> dict[str, int]:
        """Global click totals."""
        total = await self.session.scalar(select(func.count(Click.id)))
        return {"total_clicks": total or 0}

    async def global_conversion_stats(self) -> dict[str, int]:
        """Global conversion totals by status."""
        total = await self.session.scalar(select(func.count(Conversion.id)))
        approved = await self.session.scalar(
            select(func.count(Conversion.id)).where(
                Conversion.status == ConversionStatus.approved
            )
        )
        pending = await self.session.scalar(
            select(func.count(Conversion.id)).where(
                Conversion.status == ConversionStatus.pending
            )
        )
        rejected = await self.session.scalar(
            select(func.count(Conversion.id)).where(
                Conversion.status == ConversionStatus.rejected
            )
        )
        return {
            "total": total or 0,
            "approved": approved or 0,
            "pending": pending or 0,
            "rejected": rejected or 0,
        }

    async def suspicious_conversions(self) -> list[Conversion]:
        """List conversions flagged as suspicious (amount=0 or suspicious source)."""
        result = await self.session.execute(
            select(Conversion).where(Conversion.amount == 0).order_by(Conversion.id.desc())
        )
        return list(result.scalars().all())

    async def per_offer_performance(self) -> list[dict[str, int | str]]:
        """Click + conversion counts per offer."""
        click_counts = (
            select(Click.offer_id, func.count(Click.id).label("clicks"))
            .group_by(Click.offer_id)
        )
        result = await self.session.execute(click_counts)
        click_map = {row.offer_id: row.clicks for row in result}

        conv_counts = (
            select(Conversion.offer_id, func.count(Conversion.id).label("conversions"))
            .group_by(Conversion.offer_id)
        )
        result = await self.session.execute(conv_counts)
        conv_map = {row.offer_id: row.conversions for row in result}

        all_offer_ids = set(click_map.keys()) | set(conv_map.keys())
        return [
            {
                "offer_id": oid,
                "clicks": click_map.get(oid, 0),
                "conversions": conv_map.get(oid, 0),
            }
            for oid in sorted(all_offer_ids)
        ]
