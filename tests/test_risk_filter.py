"""Tests for the risk filter."""
import pytest

from src.config.settings import Settings
from src.risk.filter import validate_signal, enrich_signal


@pytest.fixture
def settings():
    return Settings()


class TestValidateSignal:
    def test_valid_buy(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 85000.0,
            "sl": 84800.0,
            "tp1": 85200.0,
            "tp2": 85400.0,
            "tp3": 85600.0,
            "confidence": 75,
        }
        valid, reason = validate_signal(signal, settings, spread=10.0)
        assert valid, f"Should be valid but got: {reason}"

    def test_valid_sell(self, settings):
        signal = {
            "decision": "SELL",
            "current_price": 85000.0,
            "sl": 85200.0,
            "tp1": 84800.0,
            "tp2": 84600.0,
            "tp3": 84400.0,
            "confidence": 70,
        }
        valid, reason = validate_signal(signal, settings, spread=10.0)
        assert valid, f"Should be valid but got: {reason}"

    def test_no_trade_always_valid(self, settings):
        signal = {"decision": "NO_TRADE"}
        valid, _ = validate_signal(signal, settings)
        assert valid

    def test_reject_sl_too_wide(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 85000.0,
            "sl": 84400.0,  # 600 pips > 500 max
            "tp1": 85200.0,
            "tp2": 85400.0,
            "tp3": 85600.0,
            "confidence": 80,
        }
        valid, reason = validate_signal(signal, settings, spread=10.0)
        assert not valid
        assert "SL too wide" in reason

    def test_reject_bad_order_buy(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 85000.0,
            "sl": 84800.0,
            "tp1": 84900.0,  # TP1 < Entry!
            "tp2": 85200.0,
            "tp3": 85400.0,
            "confidence": 80,
        }
        valid, reason = validate_signal(signal, settings, spread=10.0)
        assert not valid

    def test_reject_missing_fields(self, settings):
        signal = {"decision": "BUY", "current_price": 85000.0}
        valid, _ = validate_signal(signal, settings)
        assert not valid


class TestEnrichSignal:
    def test_adds_rr_and_pips(self):
        signal = {
            "decision": "BUY",
            "current_price": 85000.0,
            "sl": 84800.0,
            "tp3": 85400.0,
        }
        enriched = enrich_signal(signal)
        assert "risk_reward_tp3" in enriched
        assert enriched["risk_reward_tp3"] == 2.0
        assert "sl_pips" in enriched
