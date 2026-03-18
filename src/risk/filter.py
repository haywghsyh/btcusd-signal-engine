"""
Risk Filter - Validates AI output against risk rules before notification.
"""
import logging
from typing import Dict, Optional, Tuple

from src.config.settings import Settings, price_to_pips

logger = logging.getLogger(__name__)


def validate_signal(ai_output: Dict, settings: Settings,
                    spread: float = 0.0) -> Tuple[bool, Optional[str]]:
    """
    Validate AI signal output against all risk rules.
    Returns (is_valid, rejection_reason).
    """
    decision = ai_output.get("decision", "").upper()

    # NO_TRADE is always valid (just won't notify)
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

    # SL width check
    sl_pips = price_to_pips(price - sl)
    if sl_pips > settings.max_sl_pips:
        return False, f"SL too wide: {sl_pips:.1f} pips > {settings.max_sl_pips} max"

    if sl_pips < 1.0:
        return False, f"SL too tight: {sl_pips:.1f} pips"

    # Order validation
    if decision == "BUY":
        if not (sl < price < tp1 < tp2 < tp3):
            return False, (
                f"BUY order invalid: SL({sl:.1f}) < Entry({price:.1f}) < "
                f"TP1({tp1:.1f}) < TP2({tp2:.1f}) < TP3({tp3:.1f})"
            )
    else:  # SELL
        if not (tp3 < tp2 < tp1 < price < sl):
            return False, (
                f"SELL order invalid: TP3({tp3:.1f}) < TP2({tp2:.1f}) < "
                f"TP1({tp1:.1f}) < Entry({price:.1f}) < SL({sl:.1f})"
            )

    # Risk/Reward check (TP3)
    sl_distance = abs(price - sl)
    tp3_distance = abs(tp3 - price)
    if sl_distance <= 0:
        return False, "SL distance is zero"

    rr = tp3_distance / sl_distance
    if rr < settings.min_rr:
        return False, f"RR too low: {rr:.2f} < {settings.min_rr}"

    # Spread check
    spread_pips = price_to_pips(spread)
    if spread_pips > settings.spread_threshold_pips:
        return False, f"Spread too wide: {spread_pips:.1f} pips"

    # Confidence check (optional soft filter)
    confidence = ai_output.get("confidence", 0)
    if isinstance(confidence, (int, float)) and confidence < 30:
        return False, f"Confidence too low: {confidence}"

    logger.info(f"Signal validated: {decision} RR={rr:.2f} SL={sl_pips:.1f}pips")
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
