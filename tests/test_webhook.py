"""Webhook endpoint tests: secret verification, idempotency, provider validation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def webhook_app(monkeypatch: pytest.MonkeyPatch):
    """Build the webhook app with a test secret."""
    monkeypatch.setenv("BOT_TOKEN", "dummy:token")
    monkeypatch.setenv("ADMIN_CHAT_ID", "1")
    monkeypatch.setenv("LANDING_URL", "https://example.com")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret-123")

    from app.config import get_settings
    get_settings.cache_clear()

    import db.session as sm
    sm._engine = None
    sm._session_maker = None

    from app.webhook_app import create_app
    app = create_app()
    return app


@pytest.fixture
def webhook_client(webhook_app):
    return TestClient(webhook_app)


def test_health_endpoint(webhook_client) -> None:
    """GET /health returns 200."""
    response = webhook_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_provider_404(webhook_client) -> None:
    """Unknown affiliate provider returns 404."""
    response = webhook_client.post(
        "/webhooks/affiliate/unknown_provider",
        headers={"X-Webhook-Secret": "test-secret-123"},
        json={"partner_conversion_id": "X", "offer_code": "Y"},
    )
    assert response.status_code == 404


def test_bad_secret_401(webhook_client) -> None:
    """Wrong webhook secret returns 401."""
    response = webhook_client.post(
        "/webhooks/affiliate/default",
        headers={"X-Webhook-Secret": "wrong-secret"},
        json={"partner_conversion_id": "X", "offer_code": "Y"},
    )
    assert response.status_code == 401


def test_good_secret_accepted(webhook_client) -> None:
    """Correct secret passes verification (may 404 on offer, not 401)."""
    response = webhook_client.post(
        "/webhooks/affiliate/default",
        headers={"X-Webhook-Secret": "test-secret-123"},
        json={"partner_conversion_id": "X1", "offer_code": "NONEXISTENT"},
    )
    # Not 401 — secret was accepted; 404 because offer doesn't exist.
    assert response.status_code != 401
    assert response.status_code == 404


def test_secret_via_secret_token_header(webhook_client) -> None:
    """Secret via secret_token header also works."""
    response = webhook_client.post(
        "/webhooks/affiliate/default",
        headers={"secret_token": "test-secret-123"},
        json={"partner_conversion_id": "X2", "offer_code": "NONEXISTENT"},
    )
    assert response.status_code != 401


def test_invalid_payload_422(webhook_client) -> None:
    """Malformed payload returns 422."""
    response = webhook_client.post(
        "/webhooks/affiliate/default",
        headers={"X-Webhook-Secret": "test-secret-123"},
        content=b'{"bad": "payload"}',
    )
    assert response.status_code == 422


def test_payment_endpoint_accepts(webhook_client) -> None:
    """Payment endpoint accepts valid payload."""
    response = webhook_client.post(
        "/webhooks/payments/xrocket",
        headers={"X-Webhook-Secret": "test-secret-123"},
        json={"payment_id": "PAY-001", "status": "paid"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "received"


def test_duplicate_payment_callback(webhook_client) -> None:
    """Duplicate payment callback returns duplicate status."""
    payload = {"payment_id": "PAY-DUP-001", "status": "paid"}
    headers = {"X-Webhook-Secret": "test-secret-123"}

    r1 = webhook_client.post("/webhooks/payments/xrocket", headers=headers, json=payload)
    assert r1.status_code == 200

    r2 = webhook_client.post("/webhooks/payments/xrocket", headers=headers, json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
