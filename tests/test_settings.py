"""Tests for settings and configuration."""
import pytest

from src.config.settings import Settings, SessionTime, price_to_pips, pips_to_price


class TestSessionTime:
    def test_tokyo_session(self):
        session = SessionTime("Tokyo", 9, 0, 15, 0)
        assert session.contains(10, 0) is True
        assert session.contains(8, 59) is False
        assert session.contains(15, 0) is False

    def test_ny_session_crosses_midnight(self):
        session = SessionTime("NewYork", 21, 0, 2, 0)
        assert session.contains(22, 0) is True
        assert session.contains(1, 0) is True
        assert session.contains(3, 0) is False
        assert session.contains(20, 0) is False


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.symbol == "XAUUSD"
        assert s.max_sl_pips == 100.0

    def test_is_trading_session(self):
        s = Settings()
        assert s.is_trading_session(10, 0) is True  # Tokyo
        assert s.is_trading_session(5, 0) is False   # Closed

    def test_get_active_session(self):
        s = Settings()
        assert s.get_active_session(10, 0) == "Tokyo"
        assert s.get_active_session(17, 0) == "London"
        assert s.get_active_session(22, 0) == "NewYork"
        assert s.get_active_session(5, 0) == "CLOSED"


class TestPipConversion:
    def test_price_to_pips(self):
        assert price_to_pips(5.0) == 50.0
        assert price_to_pips(-3.0) == 30.0

    def test_pips_to_price(self):
        assert pips_to_price(50.0) == 5.0
        assert pips_to_price(100.0) == 10.0
