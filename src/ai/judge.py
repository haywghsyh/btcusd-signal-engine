"""
AI Judge - Evaluates signal candidates using OpenAI ChatGPT API.
AI does NOT make free-form trading decisions. It evaluates system-generated candidates.
"""
import json
import logging
from typing import Dict, Optional

from src.config.settings import Settings
from src.features.engine import get_latest_features
from src.signals.generator import SignalCandidate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert XAUUSD trading signal evaluator.
You evaluate pre-generated signal candidates - you do NOT create trading strategies from scratch.

Your role:
1. Evaluate the candidate signal (BUY or SELL)
2. Determine SL, TP1, TP2, TP3 based on market structure
3. Assess confidence (0-100)
4. Provide invalidation condition
5. Give brief reasoning

Rules for SL/TP:
- SL must be based on market structure (swing highs/lows, ATR)
- SL must be within 100 pips (1 pip = 0.10 USD for XAUUSD)
- TP1: conservative/safe target
- TP2: standard target
- TP3: extended target, must achieve RR >= 1.0 vs SL
- For BUY: SL < Entry < TP1 < TP2 < TP3
- For SELL: TP3 < TP2 < TP1 < Entry < SL

If the setup is not convincing, return NO_TRADE.

You MUST respond with valid JSON only, no other text."""

USER_PROMPT_TEMPLATE = """Evaluate this {direction} signal candidate for XAUUSD.

Current Price: {current_price}

Market States:
{market_states}

Key Levels:
- Swing High: {swing_high}
- Swing Low: {swing_low}
- ATR (M15): {atr}

Features Summary:
H4: {h4_features}
H1: {h1_features}
M15: {m15_features}
M5: {m5_features}

Candidate Reason: {reason}

Respond with JSON:
For BUY/SELL:
{{
  "symbol": "XAUUSD",
  "decision": "BUY" or "SELL" or "NO_TRADE",
  "entry_type": "MARKET",
  "current_price": <number>,
  "sl": <number>,
  "tp1": <number>,
  "tp2": <number>,
  "tp3": <number>,
  "risk_reward_tp3": <number>,
  "confidence": <0-100>,
  "invalidate_if": "<condition>",
  "reason": "<brief reason>"
}}

For NO_TRADE:
{{
  "symbol": "XAUUSD",
  "decision": "NO_TRADE",
  "confidence": <0-100>,
  "reason": "<why no trade>"
}}"""


def _extract_feature_summary(features: Dict) -> str:
    """Create a concise feature summary for the AI prompt."""
    keys = ["close", "ema20", "ema50", "ema200", "atr", "rsi",
            "swing_high", "swing_low", "body_size", "volatility",
            "dist_ema20", "dist_ema50"]
    parts = []
    for k in keys:
        v = features.get(k)
        if v is not None:
            if isinstance(v, float):
                parts.append(f"{k}={v:.2f}")
            else:
                parts.append(f"{k}={v}")
    return ", ".join(parts) if parts else "N/A"


def build_prompt(candidate: SignalCandidate,
                 featured_data: Dict) -> str:
    """Build the user prompt for AI evaluation."""
    h4_f = get_latest_features(featured_data.get("H4"))
    h1_f = get_latest_features(featured_data.get("H1"))
    m15_f = get_latest_features(featured_data.get("M15"))
    m5_f = get_latest_features(featured_data.get("M5"))

    states_str = "\n".join(f"  {k}: {v}" for k, v in candidate.market_states.items())

    return USER_PROMPT_TEMPLATE.format(
        direction=candidate.direction,
        current_price=f"{candidate.current_price:.2f}",
        market_states=states_str,
        swing_high=f"{candidate.swing_high:.2f}",
        swing_low=f"{candidate.swing_low:.2f}",
        atr=f"{candidate.atr:.2f}",
        h4_features=_extract_feature_summary(h4_f),
        h1_features=_extract_feature_summary(h1_f),
        m15_features=_extract_feature_summary(m15_f),
        m5_features=_extract_feature_summary(m5_f),
        reason=candidate.reason,
    )


def evaluate_candidate(
    candidate: SignalCandidate,
    featured_data: Dict,
    settings: Settings,
) -> Optional[Dict]:
    """
    Send candidate to OpenAI ChatGPT API for evaluation.
    Returns parsed JSON response or None on failure.
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package not installed. Install with: pip install openai")
        return None

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not set")
        return None

    user_prompt = build_prompt(candidate, featured_data)

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.ai_model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = response.choices[0].message.content.strip()
        logger.info(f"AI raw response: {raw_text[:200]}")

        # Extract JSON from response
        ai_output = _parse_ai_response(raw_text)
        if ai_output is None:
            logger.error("Failed to parse AI response as JSON")
            return None

        # Attach raw data for logging
        ai_output["_ai_input"] = user_prompt
        ai_output["_ai_raw_output"] = raw_text

        return ai_output

    except Exception as e:
        logger.error(f"AI evaluation error: {e}")
        return None


def _parse_ai_response(text: str) -> Optional[Dict]:
    """Parse AI response, handling markdown code blocks."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                continue

    # Try finding JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None
