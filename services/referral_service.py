"""Referral system: code generation, deep-link building, click recording.

Business rules:
- get_or_create_for_user is idempotent (deterministic code from user_id).
- Deep link format: https://t.me/<bot_username>?start=<code>
- Click recording applies anti-fraud checks before inserting.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_conf import get_logger
from db.base import ClickSource
from db.models import Click, Conversion, Offer, Referral, User
from db.repositories import ClickRepository, ReferralRepository
from services.anti_fraud import AntiFraudResult, AntiFraudService
from utils.security import generate_referral_code

log = get_logger("app.referral")


class ReferralService:
    """Handles referral code lifecycle, deep links, and click attribution."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.referral_repo = ReferralRepository(session)
        self.click_repo = ClickRepository(session)
        self._anti_fraud = AntiFraudService(session)

    async def get_or_create_for_user(
        self, user: User, offer: Offer | None = None
    ) -> Referral:
        """Get or create a referral for a user. Idempotent: code is deterministic."""
        # Try existing first.
        existing = await self.referral_repo.get_by_owner(user.id)
        for ref in existing:
            if offer is None or ref.offer_id == offer.id:
                return ref

        # Generate a new code (deterministic from user_id).
        code = generate_referral_code(user.id)
        # Ensure uniqueness (extremely unlikely collision, but guard anyway).
        while await self.referral_repo.get_by_code(code) is not None:
            code = f"{code}{user.id % 10}"

        referral = await self.referral_repo.create(
            owner_user_id=user.id,
            code=code,
            offer_id=offer.id if offer else None,
        )
        log.info("referral.created", user_id=user.id, code=code)
        return referral

    def build_deep_link(self, referral: Referral) -> str:
        """Build the Telegram deep link for a referral code."""
        settings = get_settings()
        username = settings.bot_username or "your_bot"
        return f"https://t.me/{username}?start={referral.code}"

    async def resolve_referral_code(self, code: str) -> Referral | None:
        """Look up a referral by its code."""
        return await self.referral_repo.get_by_code(code)

    async def record_click(
        self,
        *,
        referral: Referral,
        user: User | None = None,
        source: ClickSource = ClickSource.telegram,
        ip_hash: str | None = None,
        ua_hash: str | None = None,
    ) -> tuple[Click | None, AntiFraudResult]:
        """Record a click after anti-fraud checks. Returns (click, fraud_result).

        If the click is suppressed by anti-fraud, returns (None, result).
        """
        offer_id = referral.offer_id or 1  # fallback if no offer linked

        # Run anti-fraud checks.
        fraud_result = await self._anti_fraud.check_click(
            referral_id=referral.id,
            user_id=user.id if user else None,
            offer_id=offer_id,
            ip_hash=ip_hash,
        )

        if fraud_result.blocked:
            log.warning(
                "click.blocked",
                referral_id=referral.id,
                reason=fraud_result.reason,
                user_id=user.id if user else None,
            )
            return None, fraud_result

        click = await self.click_repo.create(
            offer_id=offer_id,
            referral_id=referral.id,
            user_id=user.id if user else None,
            source=source,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )
        log.info(
            "click.recorded",
            click_id=click.id,
            referral_id=referral.id,
            source=source,
        )
        return click, fraud_result

    async def get_user_stats(self, user: User) -> dict[str, int]:
        """Return simple referral stats for a user: referrals, clicks, conversions."""
        referrals = await self.referral_repo.get_by_owner(user.id)
        ref_ids = [r.id for r in referrals]

        if not ref_ids:
            return {"referrals": 0, "clicks": 0, "conversions": 0}

        click_count = await self.session.scalar(
            select(func.count(Click.id)).where(Click.referral_id.in_(ref_ids))
        )
        conv_count = await self.session.scalar(
            select(func.count(Conversion.id)).where(Conversion.referral_id.in_(ref_ids))
        )
        return {
            "referrals": len(referrals),
            "clicks": click_count or 0,
            "conversions": conv_count or 0,
        }
