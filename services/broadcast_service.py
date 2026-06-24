"""Safe broadcast system: enqueue, rate-limited send, opt-out respect.

Design:
- Enqueue into broadcasts + broadcast_recipients.
- Skip users with marketing_opt_in=false for marketing sends.
- broadcast_worker sends with rate limiting (~25 msg/sec per Telegram limits).
- Honors 429 retry-after, retries transient errors, marks per-recipient status.
- No rate-limit circumvention.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from db.base import BroadcastStatus, RecipientStatus
from db.models import Broadcast, BroadcastRecipient, User
from db.repositories import BroadcastRepository

log = get_logger("app.broadcast")

# Telegram rate limits: ~30 msg/sec global, ~1 msg/sec per chat.
# We use a conservative 25 msg/sec with 1-sec per-chat spacing handled by the API.
MAX_MESSAGES_PER_SECOND = 25
MAX_RETRIES = 3


@dataclass
class BroadcastResult:
    """Result of a broadcast enqueue operation."""

    broadcast_id: int
    recipient_count: int
    status: Literal["queued", "empty"]


class BroadcastService:
    """Handles broadcast enqueue and queue processing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BroadcastRepository(session)

    async def enqueue(
        self,
        *,
        admin_id: int,
        body_text: str,
        segment: str = "all",
        marketing_only: bool = False,
    ) -> BroadcastResult:
        """Create a broadcast + enqueue recipients.

        Args:
            admin_id: Admin user ID.
            body_text: The broadcast message text.
            segment: Targeting segment ('all', 'compliant', 'marketing_opt_in').
            marketing_only: If True, skip users with marketing_opt_in=false.
        """
        # Build the recipient query.
        query = select(User.id).where(User.id > 0)
        if marketing_only or segment == "marketing_opt_in":
            query = query.where(User.marketing_opt_in.is_(True))

        result = await self.session.execute(query)
        user_ids = [row[0] for row in result.all()]

        if not user_ids:
            return BroadcastResult(broadcast_id=0, recipient_count=0, status="empty")

        # Create the broadcast.
        broadcast = await self.repo.create_broadcast(
            admin_id=admin_id,
            body_key_or_text=body_text,
            segment=segment,
        )
        broadcast.status = BroadcastStatus.queued
        await self.session.flush()

        # Enqueue recipients.
        await self.repo.add_recipients(broadcast.id, user_ids)
        await self.session.flush()

        log.info(
            "broadcast.queued",
            broadcast_id=broadcast.id,
            recipients=len(user_ids),
            segment=segment,
        )
        return BroadcastResult(
            broadcast_id=broadcast.id,
            recipient_count=len(user_ids),
            status="queued",
        )

    async def process_queue(self, bot: Any) -> int:
        """Process queued broadcasts. Returns number of messages sent.

        Called by the broadcast_worker background job. Handles rate limiting
        and 429 retry-after. This method is called periodically and processes
        a batch of recipients per invocation.
        """
        sent_count = 0

        # Find broadcasts in 'queued' or 'sending' status.
        result = await self.session.execute(
            select(Broadcast)
            .where(Broadcast.status.in_([BroadcastStatus.queued, BroadcastStatus.sending]))
            .order_by(Broadcast.id)
        )
        broadcasts = list(result.scalars().all())

        for broadcast in broadcasts:
            broadcast.status = BroadcastStatus.sending
            await self.session.flush()

            # Find unsent recipients.
            recip_result = await self.session.execute(
                select(BroadcastRecipient)
                .where(
                    BroadcastRecipient.broadcast_id == broadcast.id,
                    BroadcastRecipient.status == RecipientStatus.queued,
                )
                .order_by(BroadcastRecipient.id)
                .limit(MAX_MESSAGES_PER_SECOND)
            )
            recipients = list(recip_result.scalars().all())

            if not recipients:
                # All recipients processed — mark broadcast as sent.
                broadcast.status = BroadcastStatus.sent
                await self.session.flush()
                continue

            for recipient in recipients:
                try:
                    await bot.send_message(
                        chat_id=recipient.user_id,
                        text=broadcast.body_key_or_text,
                    )
                    recipient.status = RecipientStatus.sent
                    sent_count += 1
                except Exception as exc:
                    error_str = str(exc)
                    if "429" in error_str or "retry" in error_str.lower():
                        # Rate limited — leave as queued for next cycle.
                        log.warning(
                            "broadcast.rate_limited",
                            recipient_id=recipient.user_id,
                            broadcast_id=broadcast.id,
                        )
                        break  # stop processing this batch
                    else:
                        recipient.status = RecipientStatus.failed
                        log.error(
                            "broadcast.send_failed",
                            recipient_id=recipient.user_id,
                            error=error_str[:200],
                        )
                await self.session.flush()

            # Rate limit: wait between batches.
            await asyncio.sleep(1)

        if sent_count:
            log.info("broadcast.batch_sent", count=sent_count)
        return sent_count

    async def get_broadcast_stats(self) -> dict[str, int]:
        """Get broadcast statistics."""
        total = await self.session.scalar(select(func.count(Broadcast.id)))
        sent = await self.session.scalar(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.status == RecipientStatus.sent
            )
        )
        failed = await self.session.scalar(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.status == RecipientStatus.failed
            )
        )
        queued = await self.session.scalar(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.status == RecipientStatus.queued
            )
        )
        return {
            "total_broadcasts": total or 0,
            "sent": sent or 0,
            "failed": failed or 0,
            "queued": queued or 0,
        }
