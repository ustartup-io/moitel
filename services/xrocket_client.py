"""Thin async xRocket Pay client.

Base URL: https://pay.xrocket.tg/
Auth: API key via `Rocket-Pay-Key` header.

Implemented endpoints:
  POST /tg-invoices    — create invoice
  GET  /tg-invoices/{id} — get invoice status

IMPORTANT: The exact request/response field names for xRocket Pay may differ
from what's documented here. This client isolates all API uncertainty behind
typed pydantic models. If a field is uncertain, it's marked TODO. In production,
verify against the live API and adjust the models. Tests use a mock client.

NEVER accept bookmaker deposits/wagers — this is only for selling digital access.
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.logging_conf import get_logger

log = get_logger("app.xrocket")

# TODO(verify-live): Confirm exact xRocket Pay field names against the live API.
# These models capture the expected shape; adjust after live API verification.

XROCKET_HEADERS_KEY = "Rocket-Pay-Key"


class CreateInvoiceRequest(BaseModel):
    """Request body for POST /tg-invoices."""

    amount: str = Field(..., description="Amount as string (e.g. '10.50')")
    currency: str = Field(..., description="Currency code: TON, USDT")
    description: str | None = None
    payload: str = Field(..., description="Our internal payment ID for callback mapping")
    expired_in: int = Field(default=86400, description="Seconds until expiry (default 24h)")
    callback_url: str | None = Field(None, description="Webhook callback URL for status updates")


class InvoiceResponse(BaseModel):
    """Response from xRocket invoice endpoints.

    The API wraps data in {success, data} or returns {ok, result}. We handle
    both shapes by normalizing on parse.
    """

    id: str = Field(..., description="xRocket invoice ID")
    status: str = Field("active", description="active | paid | expired")
    amount: str | None = None
    currency: str | None = None
    pay_url: str | None = Field(None, description="URL for the user to pay")
    payload: str | None = None
    # TODO(verify-live): confirm if pay_url or link is the field name.


class XRocketClient:
    """Async xRocket Pay client using httpx."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.xrocket_base_url).rstrip("/")
        self._api_key = api_key or (
            settings.xrocket_api_key.get_secret_value()
            if settings.xrocket_api_key
            else ""
        )
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {XROCKET_HEADERS_KEY: self._api_key}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self.headers,
                timeout=self._timeout,
            )
        return self._client

    async def create_invoice(
        self,
        *,
        amount: str,
        currency: str,
        payload: str,
        description: str | None = None,
        expired_in: int = 86400,
        callback_url: str | None = None,
    ) -> InvoiceResponse:
        """Create a new invoice. Returns typed InvoiceResponse."""
        body = CreateInvoiceRequest(
            amount=amount,
            currency=currency,
            description=description,
            payload=payload,
            expired_in=expired_in,
            callback_url=callback_url,
        )
        client = await self._get_client()
        resp = await client.post("/tg-invoices", json=body.model_dump(exclude_none=True))

        if resp.status_code not in (200, 201):
            log.error("xrocket.create_invoice.failed", status=resp.status_code, body=resp.text[:200])
            raise XRocketError(f"xRocket create_invoice failed: {resp.status_code}")

        data = _normalize_response(resp.json())
        return _parse_invoice(data)

    async def get_invoice(self, invoice_id: str) -> InvoiceResponse:
        """Get invoice status by ID."""
        client = await self._get_client()
        resp = await client.get(f"/tg-invoices/{invoice_id}")

        if resp.status_code == 404:
            raise XRocketError(f"Invoice {invoice_id} not found")
        if resp.status_code != 200:
            log.error("xrocket.get_invoice.failed", status=resp.status_code, invoice_id=invoice_id)
            raise XRocketError(f"xRocket get_invoice failed: {resp.status_code}")

        data = _normalize_response(resp.json())
        return _parse_invoice(data)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class XRocketError(Exception):
    """Raised when xRocket API returns an error."""


# --- Response normalization helpers ------------------------------------------

def _normalize_response(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize xRocket API response envelope: {success,data} or {ok,result}."""
    if "data" in raw:
        return dict(raw["data"])
    if "result" in raw:
        return dict(raw["result"])
    return dict(raw)


def _parse_invoice(data: dict[str, Any]) -> InvoiceResponse:
    """Parse a normalized invoice dict into InvoiceResponse."""
    # Handle field name variations (TODO: confirm against live API).
    pay_url = data.get("pay_url") or data.get("link") or data.get("url")
    invoice_id = str(data.get("id") or data.get("invoice_id") or "")
    if not invoice_id:
        raise XRocketError("Invoice response missing 'id' field")
    return InvoiceResponse(
        id=invoice_id,
        status=data.get("status", "active"),
        amount=data.get("amount"),
        currency=data.get("currency"),
        pay_url=pay_url,
        payload=data.get("payload"),
    )


class MockXRocketClient:
    """In-memory mock for tests. Mimics XRocketClient interface.

    Usage:
        mock = MockXRocketClient()
        # create_invoice returns active -> call mock.simulate_paid(id) to transition.
    """

    def __init__(self) -> None:
        self._invoices: dict[str, InvoiceResponse] = {}

    async def create_invoice(
        self,
        *,
        amount: str,
        currency: str,
        payload: str,
        description: str | None = None,
        expired_in: int = 86400,
        callback_url: str | None = None,
    ) -> InvoiceResponse:
        inv = InvoiceResponse(
            id=f"mock-{payload}",
            status="active",
            amount=amount,
            currency=currency,
            pay_url=f"https://pay.xrocket.tg/mock/{payload}",
            payload=payload,
        )
        self._invoices[inv.id] = inv
        return inv

    async def get_invoice(self, invoice_id: str) -> InvoiceResponse:
        inv = self._invoices.get(invoice_id)
        if inv is None:
            raise XRocketError(f"Invoice {invoice_id} not found")
        return inv

    async def close(self) -> None:
        pass

    # Test helpers ----------------------------------------------------------

    def simulate_paid(self, invoice_id: str) -> None:
        """Transition a mock invoice to 'paid' status."""
        if invoice_id in self._invoices:
            self._invoices[invoice_id].status = "paid"

    def simulate_expired(self, invoice_id: str) -> None:
        """Transition a mock invoice to 'expired' status."""
        if invoice_id in self._invoices:
            self._invoices[invoice_id].status = "expired"
