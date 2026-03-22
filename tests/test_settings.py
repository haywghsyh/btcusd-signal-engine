"""Tests for settings and configuration."""
import pytest

from src.config.settings import Settings, SessionTime, price_to_pips, pips_to_price


class TestSessionTime:
    def test_asia_session(self):
        session = SessionTime("Asia", 0, 0, 8, 0)
        assert session.contains(3, 0) is True
        assert session.contains(8, 0) is False

    def test_london_session(self):
        session = SessionTime("London", 8, 0, 16, 0)
        assert session.contains(10, 0) is True
        assert session.contains(7, 59) is False
        assert session.contains(16, 0) is False

    def test_ny_session(self):
        session = SessionTime("NewYork", 16, 0, 24, 0)
        assert session.contains(20, 0) is True
        assert session.contains(15, 0) is False


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.symbol == "BTCUSD"
        assert s.max_sl_pips == 500.0

    def test_is_trading_session(self):
        s = Settings()
        # BTC trades 24/7 - all hours should be in a session
        assert s.is_trading_session(3, 0) is True   # Asia
        assert s.is_trading_session(10, 0) is True   # London
        assert s.is_trading_session(20, 0) is True   # NewYork

    def test_get_active_session(self):
        s = Settings()
        assert s.get_active_session(3, 0) == "Asia"
        assert s.get_active_session(10, 0) == "London"
        assert s.get_active_session(20, 0) == "NewYork"


class TestPipConversion:
    def test_price_to_pips(self):
        # BTCUSD: 1 pip = 1.0 USD
        assert price_to_pips(5.0) == 5.0
        assert price_to_pips(-3.0) == 3.0

    def test_pips_to_price(self):
        assert pips_to_price(50.0) == 50.0
        assert pips_to_price(100.0) == 100.0
