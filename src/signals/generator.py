"""
Signal Candidate Generator - Generates BUY/SELL candidates based on market state.
Runs before AI evaluation.
"""
import logging
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from src.config.settings import Settings, price_to_pips

logger = logging.getLogger(__name__)


@dataclass
class SignalCandidate:
    direction: str  # "BUY" or "SELL"
    current_price: float
    swing_high: float
    swing_low: float
    atr: float
    market_states: Dict[str, str]
    reason: str


def check_contradictions(states: Dict[str, str], settings: Settings,
                         featured_data: Dict[str, pd.DataFrame]) -> Optional[str]:
    """Check if conditions prevent signal generation. Returns rejection reason or None."""
    h4 = states["H4"]
    h1 = states["H1"]
    m15 = states["M15"]

    # H4 and H1 contradiction
    if h4 == "bullish_trend" and h1 == "bearish_pullback":
        pass  # This is actually valid (pullback in uptrend)
    if h4 == "bullish_trend" and h1 in ("range_middle",):
        return "H1 in range middle during H4 bullish trend - no clear setup"
    if h4 == "bearish_trend" and h1 in ("range_middle",):
        return "H1 in range middle during H4 bearish trend - no clear setup"

    # M15 noise
    if m15 == "noisy":
        return "M15 is noisy - unreliable structure"

    # Choppy H4
    if h4 == "choppy":
        return "H4 is choppy - no clear directional bias"

    # Volatility check
    m5_data = featured_data.get("M5")
    if m5_data is not None and len(m5_data) > 0:
        latest = m5_data.iloc[-1]
        vol = latest.get("volatility", 0)
        if vol < 0.01:
            return "Insufficient volatility"

    # Spread check (will be done more precisely in risk filter)

    return None


def generate_candidate(
    states: Dict[str, str],
    featured_data: Dict[str, pd.DataFrame],
    current_price: Dict,
    settings: Settings,
) -> Optional[SignalCandidate]:
    """
    Generate a signal candidate based on market states and features.
    Returns None if no valid candidate.
    """
    # Check for rejection conditions
    rejection = check_contradictions(states, settings, featured_data)
    if rejection:
        logger.info(f"Signal candidate rejected: {rejection}")
        return None

    h4 = states["H4"]
    h1 = states["H1"]
    m15 = states["M15"]
    m5 = states["M5"]

    direction = None
    reason_parts = []

    # BUY candidate
    if (h4 in ("bullish_trend", "breakout_phase") and
        h1 in ("bullish_pullback", "continuation") and
        m15 in ("reversal_confirmed", "continuation_ready") and
        m5 == "execute_buy_ready"):
        direction = "BUY"
        reason_parts = [
            f"H4={h4}", f"H1={h1}", f"M15={m15}", f"M5={m5}",
        ]

    # SELL candidate
    elif (h4 in ("bearish_trend", "breakout_phase") and
          h1 in ("bearish_pullback", "continuation") and
          m15 in ("reversal_confirmed", "continuation_ready") and
          m5 == "execute_sell_ready"):
        direction = "SELL"
        reason_parts = [
            f"H4={h4}", f"H1={h1}", f"M15={m15}", f"M5={m5}",
        ]

    if direction is None:
        logger.info(f"No candidate: states don't match entry pattern. "
                    f"H4={h4} H1={h1} M15={m15} M5={m5}")
        return None

    # Get key levels from M15/H1 data
    h1_latest = featured_data["H1"].iloc[-1]
    m15_latest = featured_data["M15"].iloc[-1]
    m5_latest = featured_data["M5"].iloc[-1]

    price = current_price.get("bid", m5_latest["close"])

    candidate = SignalCandidate(
        direction=direction,
        current_price=price,
        swing_high=float(h1_latest["swing_high"]),
        swing_low=float(h1_latest["swing_low"]),
        atr=float(m15_latest["atr"]),
        market_states=states,
        reason=", ".join(reason_parts),
    )

    logger.info(f"Generated {direction} candidate at {price:.1f}")
    return candidate
