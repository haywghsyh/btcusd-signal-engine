"""
Feature Engine - Calculates technical indicators and features from OHLCV data.
"""
import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def swing_high(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """Rolling max of highs."""
    return df["high"].rolling(window=lookback).max()


def swing_low(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """Rolling min of lows."""
    return df["low"].rolling(window=lookback).min()


def compute_features(df: pd.DataFrame, timeframe: str) -> Optional[pd.DataFrame]:
    """
    Compute all features for a given timeframe DataFrame.
    Returns the DataFrame with feature columns added, or None on error.
    """
    if df is None or len(df) < 50:
        logger.error(f"Insufficient data for feature computation: {len(df) if df is not None else 0}")
        return None

    try:
        result = df.copy()

        # EMAs
        result["ema20"] = ema(result["close"], 20)
        result["ema50"] = ema(result["close"], 50)
        result["ema200"] = ema(result["close"], 200)

        # ATR
        result["atr"] = atr(result, 14)

        # RSI
        result["rsi"] = rsi(result["close"], 14)

        # Swing highs/lows
        result["swing_high"] = swing_high(result, 20)
        result["swing_low"] = swing_low(result, 20)

        # Recent high/low (shorter lookback)
        result["recent_high"] = result["high"].rolling(window=10).max()
        result["recent_low"] = result["low"].rolling(window=10).min()

        # Range width
        result["range_width"] = result["recent_high"] - result["recent_low"]

        # Volatility (ATR as % of price)
        result["volatility"] = result["atr"] / result["close"] * 100

        # Candle body size
        result["body_size"] = (result["close"] - result["open"]).abs()

        # Upper and lower wick
        result["upper_wick"] = result["high"] - result[["open", "close"]].max(axis=1)
        result["lower_wick"] = result[["open", "close"]].min(axis=1) - result["low"]

        # Price distance from EMAs
        result["dist_ema20"] = result["close"] - result["ema20"]
        result["dist_ema50"] = result["close"] - result["ema50"]
        result["dist_ema200"] = result["close"] - result["ema200"]

        # EMA alignment (bullish: 20 > 50 > 200)
        result["ema_bullish_aligned"] = (
            (result["ema20"] > result["ema50"]) & (result["ema50"] > result["ema200"])
        )
        result["ema_bearish_aligned"] = (
            (result["ema20"] < result["ema50"]) & (result["ema50"] < result["ema200"])
        )

        # Body/ATR ratio
        result["body_atr_ratio"] = result["body_size"] / result["atr"].replace(0, np.nan)

        # Bullish/bearish candle
        result["is_bullish"] = result["close"] > result["open"]
        result["is_bearish"] = result["close"] < result["open"]

        # Consecutive direction count
        direction = result["is_bullish"].astype(int) - result["is_bearish"].astype(int)
        groups = (direction != direction.shift()).cumsum()
        result["consecutive_direction"] = direction.groupby(groups).cumcount() + 1
        result["consecutive_direction"] *= direction

        logger.debug(f"Computed features for {timeframe}: {len(result)} rows")
        return result

    except Exception as e:
        logger.error(f"Feature computation error for {timeframe}: {e}")
        return None


def get_latest_features(df: pd.DataFrame) -> Dict:
    """Extract the latest row's features as a dictionary."""
    if df is None or len(df) == 0:
        return {}
    latest = df.iloc[-1]
    return {
        col: (float(val) if isinstance(val, (np.floating, float, np.integer, int)) else
              bool(val) if isinstance(val, (np.bool_, bool)) else str(val))
        for col, val in latest.items()
        if col != "time"
    }


def compute_all_features(data: Dict[str, pd.DataFrame]) -> Optional[Dict[str, pd.DataFrame]]:
    """Compute features for all timeframes. Returns None if any fails."""
    result = {}
    for tf, df in data.items():
        featured = compute_features(df, tf)
        if featured is None:
            return None
        result[tf] = featured
    return result
