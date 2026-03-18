"""
Market State Classifier - Classifies market state for each timeframe.
"""
import logging
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Valid states per timeframe
H4_STATES = ["bullish_trend", "bearish_trend", "range", "breakout_phase", "choppy"]
H1_STATES = [
    "bullish_pullback", "bearish_pullback", "continuation",
    "range_middle", "range_edge", "reversal_candidate",
]
M15_STATES = ["reversal_confirmed", "continuation_ready", "compression", "expansion", "noisy"]
M5_STATES = ["execute_buy_ready", "execute_sell_ready", "waiting", "invalid"]


def classify_h4(df: pd.DataFrame) -> str:
    """Classify H4 market state based on EMA alignment, ATR, RSI."""
    latest = df.iloc[-1]
    prev = df.iloc[-5:]

    ema20 = latest["ema20"]
    ema50 = latest["ema50"]
    ema200 = latest["ema200"]
    close = latest["close"]
    atr_val = latest["atr"]
    rsi_val = latest["rsi"]

    # ATR expansion check (current vs average of last 20)
    atr_series = df["atr"].dropna()
    avg_atr = atr_series.tail(20).mean() if len(atr_series) >= 20 else atr_series.mean()
    atr_expanding = atr_val > avg_atr * 1.3 if avg_atr > 0 else False

    # Choppy: RSI around 50 and no EMA alignment
    ema_aligned_bull = ema20 > ema50 > ema200
    ema_aligned_bear = ema20 < ema50 < ema200

    if ema_aligned_bull and close > ema20 and rsi_val > 50:
        if atr_expanding:
            return "breakout_phase"
        return "bullish_trend"

    if ema_aligned_bear and close < ema20 and rsi_val < 50:
        if atr_expanding:
            return "breakout_phase"
        return "bearish_trend"

    # Range: price between EMA50 and EMA200, RSI neutral
    if 40 < rsi_val < 60:
        range_width = latest.get("range_width", 0)
        if range_width > 0 and latest["body_size"] < range_width * 0.3:
            return "range"

    # Choppy: frequent direction changes
    last_10_dirs = df["consecutive_direction"].tail(10)
    if last_10_dirs.abs().mean() < 2:
        return "choppy"

    # Default based on EMA relationship
    if close > ema200:
        return "bullish_trend"
    elif close < ema200:
        return "bearish_trend"
    return "range"


def classify_h1(df: pd.DataFrame, h4_state: str) -> str:
    """Classify H1 state relative to H4 context."""
    latest = df.iloc[-1]
    close = latest["close"]
    ema20 = latest["ema20"]
    ema50 = latest["ema50"]
    rsi_val = latest["rsi"]
    dist_ema50 = latest["dist_ema50"]

    recent_high = latest["recent_high"]
    recent_low = latest["recent_low"]
    range_width = latest["range_width"]

    # Range position
    if range_width > 0:
        range_pos = (close - recent_low) / range_width
    else:
        range_pos = 0.5

    # Continuation: strong move in trend direction
    if h4_state == "bullish_trend":
        if close < ema20 and rsi_val < 45 and close > ema50:
            return "bullish_pullback"
        if close > ema20 and latest["is_bullish"]:
            return "continuation"

    if h4_state == "bearish_trend":
        if close > ema20 and rsi_val > 55 and close < ema50:
            return "bearish_pullback"
        if close < ema20 and latest["is_bearish"]:
            return "continuation"

    # Range positions
    if 0.35 < range_pos < 0.65:
        return "range_middle"

    if range_pos <= 0.15 or range_pos >= 0.85:
        return "range_edge"

    # Reversal candidate: RSI extreme + wick rejection
    if (rsi_val > 70 and latest["upper_wick"] > latest["body_size"]) or \
       (rsi_val < 30 and latest["lower_wick"] > latest["body_size"]):
        return "reversal_candidate"

    return "continuation"


def classify_m15(df: pd.DataFrame, h1_state: str) -> str:
    """Classify M15 state for structure confirmation."""
    latest = df.iloc[-1]
    prev3 = df.tail(3)

    close = latest["close"]
    ema20 = latest["ema20"]
    atr_val = latest["atr"]
    body_size = latest["body_size"]
    rsi_val = latest["rsi"]

    atr_series = df["atr"].dropna()
    avg_atr = atr_series.tail(20).mean() if len(atr_series) >= 20 else atr_series.mean()

    # Noisy: rapid direction changes and small bodies
    bodies = prev3["body_size"]
    if bodies.mean() < avg_atr * 0.3 and len(prev3["is_bullish"].unique()) > 1:
        return "noisy"

    # Compression: decreasing ATR
    if len(atr_series) >= 5:
        recent_atr = atr_series.tail(5).values
        if all(recent_atr[i] >= recent_atr[i + 1] for i in range(len(recent_atr) - 1)):
            return "compression"

    # Expansion: ATR spike
    if atr_val > avg_atr * 1.5:
        return "expansion"

    # Reversal confirmed: price crossed EMA20 with strong body
    crossed_ema = False
    if len(df) >= 3:
        prev_close = df.iloc[-2]["close"]
        prev_ema20 = df.iloc[-2]["ema20"]
        if (prev_close < prev_ema20 and close > ema20) or \
           (prev_close > prev_ema20 and close < ema20):
            crossed_ema = True

    if crossed_ema and body_size > avg_atr * 0.5:
        return "reversal_confirmed"

    # Continuation ready: aligned with H1
    if h1_state in ("bullish_pullback", "continuation") and close > ema20 and rsi_val > 50:
        return "continuation_ready"
    if h1_state in ("bearish_pullback", "continuation") and close < ema20 and rsi_val < 50:
        return "continuation_ready"

    return "noisy"


def classify_m5(df: pd.DataFrame, m15_state: str, h4_state: str) -> str:
    """Classify M5 state for entry timing."""
    if m15_state in ("noisy", "compression"):
        return "waiting"

    latest = df.iloc[-1]
    close = latest["close"]
    ema20 = latest["ema20"]
    rsi_val = latest["rsi"]
    body_size = latest["body_size"]
    atr_val = latest["atr"]

    if atr_val <= 0:
        return "invalid"

    strong_body = body_size > atr_val * 0.4

    # Buy ready
    if h4_state in ("bullish_trend", "breakout_phase"):
        if close > ema20 and latest["is_bullish"] and strong_body and rsi_val > 45:
            return "execute_buy_ready"

    # Sell ready
    if h4_state in ("bearish_trend", "breakout_phase"):
        if close < ema20 and latest["is_bearish"] and strong_body and rsi_val < 55:
            return "execute_sell_ready"

    return "waiting"


def classify_all(featured_data: Dict[str, pd.DataFrame]) -> Optional[Dict[str, str]]:
    """
    Classify market state for all timeframes.
    Returns dict like {"H4": "bullish_trend", "H1": "bullish_pullback", ...}
    """
    try:
        h4_state = classify_h4(featured_data["H4"])
        h1_state = classify_h1(featured_data["H1"], h4_state)
        m15_state = classify_m15(featured_data["M15"], h1_state)
        m5_state = classify_m5(featured_data["M5"], m15_state, h4_state)

        states = {
            "H4": h4_state,
            "H1": h1_state,
            "M15": m15_state,
            "M5": m5_state,
        }
        logger.info(f"Market states: {states}")
        return states

    except Exception as e:
        logger.error(f"Classification error: {e}")
        return None
