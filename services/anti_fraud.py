"""Lightweight anti-fraud: duplicate clicks, velocity, self-referral, fingerprint.

Design principle: FLAG, don't auto-ban. Blocked clicks are suppressed; suspicious
patterns are logged and flagged on conversions for admin review.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from db.models import Click

log = get_logger("app.antifraud")

# Tunable constants (documented assumptions for MVP).
CLICK_DEDUP_WINDOW_SECONDS = 300  # 5 min: suppress duplicate clicks in this window.
CLICK_VELOCITY_LIMIT = 10  # max clicks/min per user or IP-hash before throttling.
MAX_FINGERPRINT_ACCOUNTS = 3  # flag if same ip_hash seen on >N accounts.


@dataclass
class AntiFraudResult:
    """Result of an anti-fraud check."""

    blocked: bool = False
    reason: str = ""
    suspicious: bool = False


class AntiFraudService:
    """Checks clicks for duplicate, velocity, and fingerprint fraud."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_click(
        self,
        *,
        referral_id: int,
        user_id: int | None,
        offer_id: int,
        ip_hash: str | None = None,
    ) -> AntiFraudResult:
        """Run all anti-fraud checks for a potential click."""
        # 1. Duplicate check: same referral + user + offer within window.
        if user_id is not None:
            dup = await self._check_duplicate(referral_id, user_id, offer_id)
            if dup.blocked:
                return dup

            # 2. Velocity check: too many clicks from this user recently.
            velocity = await self._check_velocity(user_id=user_id)
            if velocity.blocked:
                return velocity

        # 3. Velocity by IP hash.
        if ip_hash:
            ip_velocity = await self._check_velocity(ip_hash=ip_hash)
            if ip_velocity.blocked:
                return ip_velocity

        # 4. Fingerprint check (suspicious, not blocking).
        suspicious = False
        if ip_hash and user_id is not None:
            suspicious = await self._check_fingerprint(ip_hash, user_id)

        return AntiFraudResult(suspicious=suspicious)

    async def check_self_referral(
        self, owner_user_id: int, converting_user_id: int
    ) -> AntiFraudResult:
        """Block self-referrals: owner == converter."""
        if owner_user_id == converting_user_id:
            log.warning(
                "self_referral.blocked",
                user_id=converting_user_id,
            )
            return AntiFraudResult(blocked=True, reason="self_referral", suspicious=True)
        return AntiFraudResult()

    async def _check_duplicate(
        self, referral_id: int, user_id: int, offer_id: int
    ) -> AntiFraudResult:
        """Check if the same user clicked the same referral+offer recently."""
        cutoff = time.time() - CLICK_DEDUP_WINDOW_SECONDS
        from datetime import UTC, datetime

        cutoff_dt = datetime.fromtimestamp(cutoff, tz=UTC)
        count = await self.session.scalar(
            select(func.count(Click.id)).where(
                Click.referral_id == referral_id,
                Click.user_id == user_id,
                Click.offer_id == offer_id,
                Click.created_at >= cutoff_dt,
            )
        )
        if count and count > 0:
            return AntiFraudResult(blocked=True, reason="duplicate_click")
        return AntiFraudResult()

    async def _check_velocity(
        self, *, user_id: int | None = None, ip_hash: str | None = None
    ) -> AntiFraudResult:
        """Check if too many clicks in the last 60 seconds."""
        cutoff = time.time() - 60
        from datetime import UTC, datetime

        cutoff_dt = datetime.fromtimestamp(cutoff, tz=UTC)
        query = select(func.count(Click.id)).where(Click.created_at >= cutoff_dt)
        if user_id is not None:
            query = query.where(Click.user_id == user_id)
        elif ip_hash is not None:
            query = query.where(Click.ip_hash == ip_hash)
        else:
            return AntiFraudResult()

        count = await self.session.scalar(query)
        if count and count >= CLICK_VELOCITY_LIMIT:
            return AntiFraudResult(blocked=True, reason="velocity_exceeded")
        return AntiFraudResult()

    async def _check_fingerprint(self, ip_hash: str, user_id: int) -> bool:
        """Flag if the same IP hash appears on many different accounts."""
        distinct_users = await self.session.scalar(
            select(func.count(func.distinct(Click.user_id))).where(
                Click.ip_hash == ip_hash,
                Click.user_id != user_id,
                Click.user_id.isnot(None),
            )
        )
        if distinct_users and distinct_users >= MAX_FINGERPRINT_ACCOUNTS:
            log.warning(
                "fingerprint.suspicious",
                ip_hash=ip_hash[:8],
                distinct_users=distinct_users,
            )
            return True
        return False
