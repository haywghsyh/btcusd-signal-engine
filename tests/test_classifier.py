"""Tests for the market state classifier."""
import numpy as np
import pandas as pd
import pytest

from src.features.engine import compute_features
from src.classifier.market_state import (
    classify_h4, classify_h1, classify_m15, classify_m5, classify_all,
    H4_STATES, H1_STATES, M15_STATES, M5_STATES,
)


def make_trending_df(n=200, base=3000.0, trend=0.5):
    """Create trending OHLCV data."""
    rng = np.random.default_rng(42)
    prices = base + np.arange(n) * trend + rng.normal(0, 0.5, n)
    data = {
        "time": pd.date_range("2025-01-01", periods=n, freq="h"),
        "open": prices - 0.5,
        "high": prices + rng.uniform(1, 4, n),
        "low": prices - rng.uniform(1, 4, n),
        "close": prices,
        "volume": rng.integers(100, 5000, n),
    }
    return pd.DataFrame(data)


def make_range_df(n=200, base=3000.0):
    """Create range-bound OHLCV data."""
    rng = np.random.default_rng(42)
    prices = base + rng.normal(0, 2, n)
    data = {
        "time": pd.date_range("2025-01-01", periods=n, freq="h"),
        "open": prices - 0.5,
        "high": prices + rng.uniform(0.5, 2, n),
        "low": prices - rng.uniform(0.5, 2, n),
        "close": prices,
        "volume": rng.integers(100, 5000, n),
    }
    return pd.DataFrame(data)


class TestClassifyH4:
    def test_returns_valid_state(self):
        df = compute_features(make_trending_df(), "H4")
        state = classify_h4(df)
        assert state in H4_STATES

    def test_bullish_trend(self):
        df = compute_features(make_trending_df(trend=1.0), "H4")
        state = classify_h4(df)
        assert state in ("bullish_trend", "breakout_phase")


class TestClassifyH1:
    def test_returns_valid_state(self):
        df = compute_features(make_trending_df(), "H1")
        state = classify_h1(df, "bullish_trend")
        assert state in H1_STATES


class TestClassifyAll:
    def test_returns_all_timeframes(self):
        featured = {
            "H4": compute_features(make_trending_df(), "H4"),
            "H1": compute_features(make_trending_df(), "H1"),
            "M15": compute_features(make_trending_df(n=300), "M15"),
            "M5": compute_features(make_trending_df(n=300), "M5"),
        }
        result = classify_all(featured)
        assert result is not None
        assert "H4" in result
        assert "H1" in result
        assert "M15" in result
        assert "M5" in result
