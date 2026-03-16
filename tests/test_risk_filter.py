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
            "current_price": 3030.0,
            "sl": 3025.0,
            "tp1": 3035.0,
            "tp2": 3040.0,
            "tp3": 3045.0,
            "confidence": 75,
        }
        valid, reason = validate_signal(signal, settings, spread=0.3)
        assert valid, f"Should be valid but got: {reason}"

    def test_valid_sell(self, settings):
        signal = {
            "decision": "SELL",
            "current_price": 3030.0,
            "sl": 3035.0,
            "tp1": 3025.0,
            "tp2": 3020.0,
            "tp3": 3015.0,
            "confidence": 70,
        }
        valid, reason = validate_signal(signal, settings, spread=0.3)
        assert valid, f"Should be valid but got: {reason}"

    def test_no_trade_always_valid(self, settings):
        signal = {"decision": "NO_TRADE"}
        valid, _ = validate_signal(signal, settings)
        assert valid

    def test_reject_sl_too_wide(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 3030.0,
            "sl": 3010.0,  # 200 pips
            "tp1": 3040.0,
            "tp2": 3050.0,
            "tp3": 3060.0,
            "confidence": 80,
        }
        valid, reason = validate_signal(signal, settings, spread=0.3)
        assert not valid
        assert "SL too wide" in reason

    def test_reject_bad_order_buy(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 3030.0,
            "sl": 3025.0,
            "tp1": 3028.0,  # TP1 < Entry!
            "tp2": 3040.0,
            "tp3": 3045.0,
            "confidence": 80,
        }
        valid, reason = validate_signal(signal, settings, spread=0.3)
        assert not valid

    def test_reject_low_rr(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 3030.0,
            "sl": 3025.0,
            "tp1": 3031.0,
            "tp2": 3032.0,
            "tp3": 3033.0,  # RR < 1.0
            "confidence": 80,
        }
        valid, reason = validate_signal(signal, settings, spread=0.3)
        assert not valid
        assert "RR too low" in reason

    def test_reject_wide_spread(self, settings):
        signal = {
            "decision": "BUY",
            "current_price": 3030.0,
            "sl": 3025.0,
            "tp1": 3035.0,
            "tp2": 3040.0,
            "tp3": 3045.0,
            "confidence": 80,
        }
        valid, reason = validate_signal(signal, settings, spread=1.0)  # 10 pips
        assert not valid
        assert "Spread" in reason

    def test_reject_missing_fields(self, settings):
        signal = {"decision": "BUY", "current_price": 3030.0}
        valid, _ = validate_signal(signal, settings)
        assert not valid


class TestEnrichSignal:
    def test_adds_rr_and_pips(self):
        signal = {
            "decision": "BUY",
            "current_price": 3030.0,
            "sl": 3025.0,
            "tp3": 3040.0,
        }
        enriched = enrich_signal(signal)
        assert "risk_reward_tp3" in enriched
        assert enriched["risk_reward_tp3"] == 2.0
        assert "sl_pips" in enriched
