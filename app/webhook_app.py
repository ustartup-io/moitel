"""FastAPI webhook app for affiliate postbacks + payment callbacks.

Runs only if WEBHOOK_ENABLED=true (separate uvicorn process).
Secret verification via X-Webhook-Secret header or secret_token query param.
Idempotency via webhook_events.dedupe_hash (duplicate = immediate 200).

Endpoints:
  POST /webhooks/affiliate/{provider}  — affiliate postbacks
  POST /webhooks/payments/{provider}   — payment callbacks (consumed in Step 5)
  GET  /health                         — health check
"""
from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.logging_conf import bind_correlation, get_logger, setup_logging
from db.base import ConversionSource, ConversionStatus
from db.repositories import OfferRepository, WebhookEventRepository
from db.session import get_session
from services.conversion_service import ConversionService
from utils.security import compute_dedupe_hash

log = get_logger("app.webhook")

KNOWN_AFFILIATE_PROVIDERS = {"default", "hasoffers", "postback"}
KNOWN_PAYMENT_PROVIDERS = {"xrocket", "manual"}


# --- Pydantic payload models -------------------------------------------------

class AffiliatePostbackPayload(BaseModel):
    """Affiliate postback payload. Fields are mapped to our conversion model."""

    partner_conversion_id: str = Field(..., description="Unique conversion ID from partner")
    offer_code: str = Field(..., description="Our offer code to map to")
    amount: int | None = Field(None, description="Conversion amount (minor units)")
    currency: str | None = None
    status: str = Field("pending", description="pending | approved | rejected")
    referral_code: str | None = Field(None, description="Referral code for attribution")
    click_id: str | None = None


class PaymentCallbackPayload(BaseModel):
    """Payment callback payload (consumed in Step 5)."""

    payment_id: str = Field(..., description="Provider payment/invoice ID")
    status: str = Field(..., description="paid | failed | expired")
    amount: int | None = None
    currency: str | None = None


# --- Secret verification -----------------------------------------------------

def _get_webhook_secret() -> str:
    """Return the configured webhook secret (empty string if not set)."""
    settings = get_settings()
    if settings.webhook_secret:
        return settings.webhook_secret.get_secret_value()
    return ""


def _verify_secret(
    x_webhook_secret: str | None, secret_token: str | None
) -> None:
    """Verify the shared secret. Raises 401 if invalid."""
    expected = _get_webhook_secret()
    if not expected:
        if get_settings().environment == "prod":
            raise HTTPException(status_code=401, detail="No webhook secret configured")
        return  # dev: allow without secret

    provided = x_webhook_secret or secret_token
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# --- Idempotency -------------------------------------------------------------

async def _check_and_record_event(
    provider: str, raw_body: bytes, external_event_id: str | None = None
) -> bool:
    """Check dedupe_hash; if new, record the event. Returns False if duplicate."""
    dedupe_hash = compute_dedupe_hash(provider, raw_body)

    async with get_session() as session:
        event_repo = WebhookEventRepository(session)
        existing = await event_repo.get_by_dedupe_hash(dedupe_hash)
        if existing is not None:
            log.info("webhook.duplicate", dedupe_hash=dedupe_hash[:12])
            return False

        await event_repo.create(
            provider=provider,
            dedupe_hash=dedupe_hash,
            payload_json=raw_body.decode(errors="replace"),
            external_event_id=external_event_id,
        )
        await session.commit()
        return True


# --- Endpoint handlers (plain async functions) -------------------------------

async def health() -> dict[str, str]:
    return {"status": "ok"}


async def affiliate_postback(
    request: Request,
    provider: str = Path(...),
    x_webhook_secret: str | None = Header(None, alias="X-Webhook-Secret"),
    secret_token: str | None = Header(None, alias="secret_token"),
) -> dict[str, Any]:
    """Handle an affiliate postback with idempotency + secret verification."""
    if provider not in KNOWN_AFFILIATE_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    _verify_secret(x_webhook_secret, secret_token)

    raw_body = await request.body()

    # Idempotency check.
    is_new = await _check_and_record_event(provider, raw_body)
    if not is_new:
        return {"status": "duplicate", "detail": "Already processed"}

    # Parse + validate payload.
    try:
        payload = AffiliatePostbackPayload(**json.loads(raw_body))
    except Exception as exc:
        log.error("webhook.invalid_payload", error=str(exc))
        raise HTTPException(status_code=422, detail=f"Invalid payload: {exc}") from exc

    bind_correlation(webhook_event_id=raw_body.hex()[:12])

    # Process the conversion.
    async with get_session() as session:
        offer_repo = OfferRepository(session)
        offer = await offer_repo.get_by_code(payload.offer_code)
        if offer is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown offer_code: {payload.offer_code}"
            )

        conv_service = ConversionService(session)
        status_enum = ConversionStatus(
            payload.status
            if payload.status in ("pending", "approved", "rejected")
            else "pending"
        )
        result = await conv_service.record_conversion(
            offer=offer,
            partner_conversion_id=payload.partner_conversion_id,
            source=ConversionSource.postback,
            amount=payload.amount,
            currency=payload.currency,
            status=status_enum,
            referral_code=payload.referral_code,
        )
        await session.commit()

    return {
        "status": result.status,
        "conversion_id": result.conversion.id if result.conversion else None,
        "reason": result.reason or None,
    }


async def payment_callback(
    request: Request,
    provider: str = Path(...),
    x_webhook_secret: str | None = Header(None, alias="X-Webhook-Secret"),
    secret_token: str | None = Header(None, alias="secret_token"),
) -> dict[str, Any]:
    """Handle a payment callback (consumed in Step 5)."""
    if provider not in KNOWN_PAYMENT_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    _verify_secret(x_webhook_secret, secret_token)

    raw_body = await request.body()
    is_new = await _check_and_record_event(provider, raw_body)
    if not is_new:
        return {"status": "duplicate", "detail": "Already processed"}

    try:
        payload = PaymentCallbackPayload(**json.loads(raw_body))
    except Exception as exc:
        log.error("webhook.payment.invalid_payload", error=str(exc))
        raise HTTPException(status_code=422, detail=f"Invalid payload: {exc}") from exc

    # Look up payment by payload (our internal ID) and confirm.
    payment_id: int | None = None
    with suppress(ValueError):
        payment_id = int(payload.payment_id)

    async with get_session() as session:
        from services.payment_service import PaymentService
        pay_service = PaymentService(session)
        await pay_service.confirm_payment(
            provider_invoice_id=payload.payment_id,
            payment_id_from_payload=payment_id,
        )
        await session.commit()

    log.info("webhook.payment.confirmed", payment_id=payload.payment_id, status=payload.status)

    return {"status": "confirmed", "payment_id": payload.payment_id}


# --- App factory -------------------------------------------------------------

def create_app() -> FastAPI:
    """Build the FastAPI webhook app."""
    settings = get_settings()
    setup_logging(level=settings.log_level, json_logs=settings.environment == "prod")
    app = FastAPI(title="Affiliate Bot Webhooks", version="0.1.0")
    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/webhooks/affiliate/{provider}", affiliate_postback, methods=["POST"])
    app.add_api_route("/webhooks/payments/{provider}", payment_callback, methods=["POST"])
    return app
