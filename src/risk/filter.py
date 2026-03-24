"""
Risk Filter - Light validation of AI output.
Only checks that numbers make sense. Does NOT override AI's trading decisions.
"""
import logging
from typing import Dict, Optional, Tuple

from src.config.settings import Settings, price_to_pips

logger = logging.getLogger(__name__)


def validate_signal(ai_output: Dict, settings: Settings,
                    spread: float = 0.0) -> Tuple[bool, Optional[str]]:
    """
    Light validation - only check that the numbers are valid.
    AI has full autonomy on entry decisions.
    """
    decision = ai_output.get("decision", "").upper()

    if decision == "NO_TRADE":
        return True, None

    if decision not in ("BUY", "SELL"):
        return False, f"Invalid decision: {decision}"

    # Required fields
    required = ["current_price", "sl", "tp1", "tp2", "tp3"]
    for field in required:
        if field not in ai_output:
            return False, f"Missing field: {field}"
        try:
            float(ai_output[field])
        except (TypeError, ValueError):
            return False, f"Invalid numeric value for {field}: {ai_output[field]}"

    price = float(ai_output["current_price"])
    sl = float(ai_output["sl"])
    tp1 = float(ai_output["tp1"])
    tp2 = float(ai_output["tp2"])
    tp3 = float(ai_output["tp3"])

    # Check for NaN/Inf
    for name, val in [("price", price), ("sl", sl), ("tp1", tp1), ("tp2", tp2), ("tp3", tp3)]:
        if val != val or val == float("inf") or val == float("-inf"):
            return False, f"Invalid value for {name}: {val}"

    # Spread check
    if spread > settings.spread_threshold_pips:
        return False, f"Spread too wide: {spread:.1f} > {settings.spread_threshold_pips:.1f} pips"

    # SL width check (max 1000 pips for BTC short-term trading)
    sl_pips = price_to_pips(price - sl)
    if sl_pips > 1000:
        return False, f"SL too wide: {sl_pips:.1f} pips > 1000 max"

    if sl_pips < 0.5:
        return False, f"SL too tight: {sl_pips:.1f} pips"

    # Order validation
    if decision == "BUY":
        if not (sl < price < tp1):
            return False, (
                f"BUY order invalid: SL({sl:.1f}) < Entry({price:.1f}) < TP1({tp1:.1f})"
            )
    else:  # SELL
        if not (tp1 < price < sl):
            return False, (
                f"SELL order invalid: TP1({tp1:.1f}) < Entry({price:.1f}) < SL({sl:.1f})"
            )

    logger.info(f"Signal validated: {decision} SL={sl_pips:.1f}pips")
    return True, None


def enrich_signal(ai_output: Dict) -> Dict:
    """Add computed fields to validated signal."""
    decision = ai_output.get("decision", "").upper()
    if decision == "NO_TRADE":
        return ai_output

    price = float(ai_output["current_price"])
    sl = float(ai_output["sl"])
    tp3 = float(ai_output["tp3"])

    sl_distance = abs(price - sl)
    tp3_distance = abs(tp3 - price)
    rr = tp3_distance / sl_distance if sl_distance > 0 else 0

    ai_output["risk_reward_tp3"] = round(rr, 2)
    ai_output["sl_pips"] = round(price_to_pips(price - sl), 1)

    return ai_output
