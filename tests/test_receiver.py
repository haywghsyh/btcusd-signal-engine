"""Tests for the market data receiver."""
import pytest

from src.config.settings import Settings
from src.data.receiver import MarketDataReceiver, CandleBuffer


@pytest.fixture
def settings():
    return Settings()


class TestCandleBuffer:
    def test_add_and_count(self):
        buf = CandleBuffer(max_candles=100)
        buf.add({"time": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0, "close": 1.5, "volume": 10})
        assert buf.count() == 1

    def test_dedup_by_time(self):
        buf = CandleBuffer(max_candles=100)
        candle = {"time": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0, "close": 1.5, "volume": 10}
        buf.add(candle)
        buf.add(candle)
        assert buf.count() == 1

    def test_max_candles(self):
        buf = CandleBuffer(max_candles=5)
        for i in range(10):
            buf.add({"time": f"2025-01-01T00:{i:02d}:00", "open": i, "high": i+1, "low": i-1, "close": i, "volume": 1})
        assert buf.count() == 5

    def test_to_dataframe(self):
        buf = CandleBuffer(max_candles=100)
        buf.add({"time": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0, "close": 1.5, "volume": 10})
        df = buf.to_dataframe()
        assert df is not None
        assert len(df) == 1


class TestMarketDataReceiver:
    def test_process_valid_webhook(self, settings):
        receiver = MarketDataReceiver(settings)
        payload = {
            "symbol": "BTCUSD",
            "timestamp": "2025-01-01T00:00:00Z",
            "open": 85000.0,
            "high": 85200.0,
            "low": 84800.0,
            "close": 85100.0,
            "volume": 100,
            "timeframe": "M5",
        }
        assert receiver.process_webhook(payload) is True

    def test_reject_wrong_symbol(self, settings):
        receiver = MarketDataReceiver(settings)
        payload = {
            "symbol": "EURUSD",
            "timestamp": "2025-01-01T00:00:00Z",
            "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
            "volume": 100, "timeframe": "M5",
        }
        assert receiver.process_webhook(payload) is False

    def test_reject_wrong_timeframe(self, settings):
        receiver = MarketDataReceiver(settings)
        payload = {
            "symbol": "BTCUSD",
            "timestamp": "2025-01-01T00:00:00Z",
            "open": 85000.0, "high": 85200.0, "low": 84800.0, "close": 85100.0,
            "volume": 100, "timeframe": "D1",
        }
        assert receiver.process_webhook(payload) is False

    def test_current_price_after_webhook(self, settings):
        receiver = MarketDataReceiver(settings)
        payload = {
            "symbol": "BTCUSD",
            "timestamp": "2025-01-01T00:00:00Z",
            "open": 85000.0, "high": 85200.0, "low": 84800.0, "close": 85100.0,
            "volume": 100, "timeframe": "M5",
        }
        receiver.process_webhook(payload)
        price = receiver.get_current_price()
        assert price is not None
        assert price["bid"] == 85100.0

    def test_get_status(self, settings):
        receiver = MarketDataReceiver(settings)
        status = receiver.get_status()
        assert "M5" in status
        assert "H4" in status
