"""In-process async background jobs.

Each job: try/except, structured logs, never crash the loop, respect a global
shutdown event. Started by app.main; no Celery/Redis.

Jobs:
  - payment_polling: poll xRocket for pending payments (fallback confirmation)
  - delivery_retry: retry failed deliveries (capped backoff)
  - webhook_reconciliation: reconcile pending webhook events
  - expired_payment_cleanup: mark old pending payments as expired
  - broadcast_worker: send queued broadcasts (used in Step 7)
  - health_heartbeat: periodic health log + optional admin ping
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.logging_conf import get_logger
from db.base import PaymentStatus, WebhookStatus
from db.models import Payment, WebhookEvent
from db.session import get_session
from services.delivery_service import DeliveryService
from services.payment_service import PaymentService

log = get_logger("app.jobs")

# Job intervals (seconds).
PAYMENT_POLLING_INTERVAL = 60
DELIVERY_RETRY_INTERVAL = 30
WEBHOOK_RECONCILE_INTERVAL = 120
EXPIRED_CLEANUP_INTERVAL = 300
BROADCAST_INTERVAL = 5
HEARTBEAT_INTERVAL = 600

PAYMENT_EXPIRY_HOURS = 24


class JobManager:
    """Manages background asyncio tasks with graceful shutdown."""

    def __init__(self) -> None:
        self._shutdown = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown.is_set()

    async def start_all(self) -> None:
        """Start all background jobs."""
        self._tasks = [
            asyncio.create_task(
                self._run_job("payment_polling", self._payment_polling, PAYMENT_POLLING_INTERVAL)
            ),
            asyncio.create_task(
                self._run_job("delivery_retry", self._delivery_retry, DELIVERY_RETRY_INTERVAL)
            ),
            asyncio.create_task(
                self._run_job(
                    "webhook_reconcile", self._webhook_reconcile, WEBHOOK_RECONCILE_INTERVAL
                )
            ),
            asyncio.create_task(
                self._run_job("expired_cleanup", self._expired_cleanup, EXPIRED_CLEANUP_INTERVAL)
            ),
            asyncio.create_task(
                self._run_job("broadcast_worker", self._broadcast_worker, BROADCAST_INTERVAL)
            ),
            asyncio.create_task(
                self._run_job("health_heartbeat", self._health_heartbeat, HEARTBEAT_INTERVAL)
            ),
        ]
        log.info("jobs.started", count=len(self._tasks))

    async def stop_all(self) -> None:
        """Signal shutdown and wait for all jobs to finish."""
        self._shutdown.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("jobs.stopped")

    async def _run_job(
        self,
        name: str,
        coro_fn: Callable[[], Awaitable[None]],
        interval: float,
    ) -> None:
        """Run a job in a loop: execute -> sleep(interval) -> repeat.

        Never crashes: all exceptions are caught and logged.
        """
        log.info("job.started", name=name, interval=interval)
        while not self._shutdown.is_set():
            try:
                await coro_fn()
            except Exception:
                log.error("job.error", name=name, exc_info=True)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
        log.info("job.stopped", name=name)

    # --- Individual jobs ----------------------------------------------------

    async def _payment_polling(self) -> None:
        """Poll xRocket for pending payments."""
        async with get_session() as session:
            result = await session.execute(
                select(Payment).where(
                    Payment.status.in_([PaymentStatus.pending, PaymentStatus.created])
                )
            )
            payments = list(result.scalars().all())

            if not payments:
                return

            pay_service = PaymentService(session)
            for payment in payments:
                try:
                    await pay_service.poll_payment(payment)
                except Exception:
                    log.error("payment.poll_error", payment_id=payment.id, exc_info=True)
            await session.commit()

        if payments:
            log.info("payment.poll_complete", count=len(payments))

    async def _delivery_retry(self) -> None:
        """Retry failed deliveries."""
        from db.repositories import DeliveryRepository

        async with get_session() as session:
            repo = DeliveryRepository(session)
            failed = await repo.get_failed()
            if not failed:
                return

            delivery_service = DeliveryService(session)
            for delivery in failed:
                await delivery_service.retry_failed(delivery)
            await session.commit()

        if failed:
            log.info("delivery.retry_complete", count=len(failed))

    async def _webhook_reconcile(self) -> None:
        """Reconcile pending webhook events (mark old ones as processed)."""
        async with get_session() as session:
            result = await session.execute(
                select(WebhookEvent)
                .where(WebhookEvent.status == WebhookStatus.received)
                .order_by(WebhookEvent.id)
                .limit(50)
            )
            events = list(result.scalars().all())
            for event in events:
                event.status = WebhookStatus.processed
                event.processed_at = datetime.now(UTC)
            await session.commit()

        if events:
            log.info("webhook.reconcile_complete", count=len(events))

    async def _expired_cleanup(self) -> None:
        """Mark old pending payments as expired (>24h old)."""
        cutoff = datetime.now(UTC) - timedelta(hours=PAYMENT_EXPIRY_HOURS)
        async with get_session() as session:
            result = await session.execute(
                select(Payment)
                .where(Payment.status.in_([PaymentStatus.pending, PaymentStatus.created]))
                .where(Payment.created_at < cutoff)
            )
            stale = list(result.scalars().all())
            for payment in stale:
                payment.status = PaymentStatus.expired
            await session.commit()

        if stale:
            log.warning("payment.expired_cleanup", count=len(stale))

    async def _broadcast_worker(self) -> None:
        """Process queued broadcasts (defined now, used in Step 7)."""
        # TODO(M7): implement broadcast queue processing with rate limiting.

    async def _health_heartbeat(self) -> None:
        """Log a periodic health heartbeat."""
        log.info("health.heartbeat", jobs_running=len(self._tasks))


# Module-level singleton.
job_manager = JobManager()
