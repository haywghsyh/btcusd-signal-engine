"""Tests for signal database storage."""
import os
import pytest

from src.config.settings import Settings
from src.storage.database import SignalDatabase


@pytest.fixture
def db(tmp_path):
    settings = Settings()
    settings.db_path = str(tmp_path / "test_signals.db")
    return SignalDatabase(settings)


class TestSignalDatabase:
    def test_save_and_retrieve(self, db):
        signal = {
            "symbol": "XAUUSD",
            "decision": "BUY",
            "current_price": 3030.0,
            "sl": 3025.0,
            "tp1": 3035.0,
            "tp2": 3040.0,
            "tp3": 3045.0,
            "risk_reward_tp3": 2.0,
            "confidence": 80,
            "reason": "Test signal",
            "invalidate_if": "Below 3020",
        }
        signal_id = db.save_signal(signal)
        assert signal_id != ""

        recent = db.get_recent_signals(1)
        assert len(recent) == 1
        assert recent[0]["decision"] == "BUY"

    def test_no_trade_signal(self, db):
        signal = {
            "symbol": "XAUUSD",
            "decision": "NO_TRADE",
            "reason": "No setup",
            "confidence": 40,
        }
        signal_id = db.save_signal(signal)
        assert signal_id != ""

    def test_duplicate_detection(self, db):
        signal = {
            "symbol": "XAUUSD",
            "decision": "BUY",
            "current_price": 3030.0,
        }
        db.save_signal(signal, notification_sent=True)

        # Same direction, same price, within cooldown
        assert db.is_duplicate("BUY", 3030.5, cooldown_seconds=900) is True
        # Different direction
        assert db.is_duplicate("SELL", 3030.0, cooldown_seconds=900) is False
        # Far away price
        assert db.is_duplicate("BUY", 3050.0, cooldown_seconds=900) is False

    def test_get_last_signal_by_direction(self, db):
        signal = {
            "symbol": "XAUUSD",
            "decision": "SELL",
            "current_price": 3030.0,
        }
        db.save_signal(signal)
        result = db.get_last_signal_by_direction("SELL")
        assert result is not None
        assert result["decision"] == "SELL"
