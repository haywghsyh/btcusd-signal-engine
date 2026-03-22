"""Tests for the webhook server endpoints."""
import json
import pytest

from main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestWebhookEndpoints:
    def test_status_endpoint(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "symbol" in data
        assert data["symbol"] == "BTCUSD"

    def test_tradingview_webhook(self, client):
        payload = {
            "symbol": "BTCUSD",
            "timestamp": "2025-01-01T10:00:00Z",
            "open": 85000.0,
            "high": 85200.0,
            "low": 84800.0,
            "close": 85100.0,
            "volume": 100,
            "timeframe": "M5",
        }
        resp = client.post(
            "/webhook/tradingview",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_invalid_webhook(self, client):
        resp = client.post(
            "/webhook/tradingview",
            data="not json",
            content_type="text/plain",
        )
        # Should handle gracefully
        assert resp.status_code in (200, 400)

    def test_recent_signals(self, client):
        resp = client.get("/signals/recent")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "signals" in data

    def test_batch_webhook(self, client):
        payload = {
            "timeframe": "H1",
            "candles": [
                {"timestamp": "2025-01-01T00:00:00Z", "open": 85000, "high": 85200, "low": 84800, "close": 85100, "volume": 100},
                {"timestamp": "2025-01-01T01:00:00Z", "open": 85100, "high": 85300, "low": 85000, "close": 85200, "volume": 150},
            ],
        }
        resp = client.post(
            "/webhook/batch",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["loaded"] == 2

    def test_manual_analyze(self, client):
        resp = client.post("/analyze")
        assert resp.status_code == 200
