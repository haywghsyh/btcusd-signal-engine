"""Tests for the feature engine."""
import numpy as np
import pandas as pd
import pytest

from src.features.engine import compute_features, ema, atr, rsi, get_latest_features


def make_sample_df(n=200, base_price=3000.0):
    """Create sample OHLCV DataFrame for testing."""
    rng = np.random.default_rng(42)
    prices = base_price + np.cumsum(rng.normal(0, 1, n))
    data = {
        "time": pd.date_range("2025-01-01", periods=n, freq="5min"),
        "open": prices,
        "high": prices + rng.uniform(0, 5, n),
        "low": prices - rng.uniform(0, 5, n),
        "close": prices + rng.normal(0, 1, n),
        "volume": rng.integers(100, 5000, n),
    }
    return pd.DataFrame(data)


class TestEMA:
    def test_ema_length(self):
        s = pd.Series(range(100), dtype=float)
        result = ema(s, 20)
        assert len(result) == 100

    def test_ema_values(self):
        s = pd.Series([1.0] * 50)
        result = ema(s, 20)
        assert abs(result.iloc[-1] - 1.0) < 0.001


class TestATR:
    def test_atr_positive(self):
        df = make_sample_df()
        result = atr(df, 14)
        valid = result.dropna()
        assert (valid > 0).all()


class TestRSI:
    def test_rsi_range(self):
        df = make_sample_df()
        result = rsi(df["close"], 14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


class TestComputeFeatures:
    def test_returns_dataframe(self):
        df = make_sample_df()
        result = compute_features(df, "M5")
        assert result is not None
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns(self):
        df = make_sample_df()
        result = compute_features(df, "M5")
        required = [
            "ema20", "ema50", "ema200", "atr", "rsi",
            "swing_high", "swing_low", "body_size",
            "upper_wick", "lower_wick", "dist_ema20",
        ]
        for col in required:
            assert col in result.columns, f"Missing column: {col}"

    def test_insufficient_data(self):
        df = make_sample_df(n=10)
        result = compute_features(df, "M5")
        assert result is None

    def test_get_latest_features(self):
        df = make_sample_df()
        featured = compute_features(df, "M5")
        latest = get_latest_features(featured)
        assert isinstance(latest, dict)
        assert "close" in latest
        assert "ema20" in latest
