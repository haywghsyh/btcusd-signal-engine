"""
AI Judge - ChatGPT freely analyzes XAUUSD market data and decides entries.
No pre-filtered candidates. AI has full autonomy to decide BUY/SELL/NO_TRADE.
"""
import json
import logging
from typing import Dict, List, Optional

from src.config.settings import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたはXAUUSD（ゴールド）専門のプロスキャルパーです。
市場データを分析し、自分の判断でエントリーシグナルを出してください。

【トレードスタイル】
- スキャルピングのみ（保有時間: 数分〜最大1時間程度）
- デイトレードやスイングトレードは禁止
- SLは狭く（5〜30pips目安）、TPも近めに設定
- 1 pip = 0.10 USD（XAUUSD）

【重要な方針】
- 勝率を意識しつつも、積極的にエントリーチャンスを探すこと（目標: 60%以上）
- 少しでも優位性があればエントリーする。完璧な条件を待たない
- 1日8〜15回程度のシグナルを目標（積極的にチャンスを拾う）
- エントリー理由を明確に説明すること
- 明確にリスクが高い場合のみNO_TRADEにする。迷ったらエントリーする側に倒す

【分析のポイント】
- 短期の値動き（M5, M15）を重視。小さなチャンスも見逃さない
- EMA, RSI, ATRなどのテクニカル指標を参考に
- サポート/レジスタンスレベルを意識
- ローソク足のパターンや勢いを見る
- H1, H4はトレンドの方向確認に使用
- トレンドフォロー、反転、レンジブレイクなど多様な手法でチャンスを探す
- RSIの買われすぎ/売られすぎだけでNO_TRADEにしない。他の根拠と組み合わせて判断する

【SL/TPルール】
- BUYの場合: SL < Entry < TP1 < TP2 < TP3
- SELLの場合: TP3 < TP2 < TP1 < Entry < SL
- SLは市場構造に基づいて設定（直近の安値/高値）
- TP1: 堅実な利確（RR 1:1程度）
- TP2: 標準的な利確
- TP3: 伸ばせる場合の利確

必ず有効なJSONのみで返答してください。"""

USER_PROMPT_TEMPLATE = """以下のXAUUSD市場データを分析し、スキャルピングエントリーすべきか判断してください。

【現在価格】{current_price}

【M5（5分足）直近データ】
{m5_summary}

【M15（15分足）直近データ】
{m15_summary}

【H1（1時間足）コンテキスト】
{h1_summary}

【H4（4時間足）トレンド】
{h4_summary}

【本日のシグナル状況】
- 発行済みシグナル数: {signals_today}
- 直近の結果: {recent_results}

エントリーする場合:
{{
  "symbol": "XAUUSD",
  "decision": "BUY" or "SELL",
  "entry_type": "MARKET",
  "current_price": <現在価格>,
  "sl": <ストップロス>,
  "tp1": <利確1>,
  "tp2": <利確2>,
  "tp3": <利確3>,
  "risk_reward_tp3": <リスクリワード比>,
  "confidence": <0-100>,
  "invalidate_if": "<無効条件>",
  "reason": "<エントリー理由を日本語で簡潔に>"
}}

見送る場合:
{{
  "symbol": "XAUUSD",
  "decision": "NO_TRADE",
  "confidence": <0-100>,
  "reason": "<見送り理由を日本語で簡潔に>"
}}"""


def _format_candle_summary(features: Dict, num_candles: int = 20) -> str:
    """Format recent candle data into a readable summary for AI."""
    if not features:
        return "データなし"

    parts = []

    # Latest values
    latest_keys = [
        ("close", "現在値"), ("ema20", "EMA20"), ("ema50", "EMA50"),
        ("ema200", "EMA200"), ("rsi", "RSI"), ("atr", "ATR"),
        ("swing_high", "直近高値"), ("swing_low", "直近安値"),
        ("body_size", "実体サイズ"), ("volatility", "ボラティリティ%"),
    ]

    for key, label in latest_keys:
        v = features.get(key)
        if v is not None:
            if isinstance(v, float):
                parts.append(f"{label}: {v:.2f}")
            else:
                parts.append(f"{label}: {v}")

    # EMA alignment
    if features.get("ema_bullish_aligned"):
        parts.append("EMA配列: 上昇トレンド（20>50>200）")
    elif features.get("ema_bearish_aligned"):
        parts.append("EMA配列: 下降トレンド（20<50<200）")
    else:
        parts.append("EMA配列: 混在")

    # Candle direction
    consec = features.get("consecutive_direction", 0)
    if consec > 0:
        parts.append(f"連続陽線: {int(abs(consec))}本")
    elif consec < 0:
        parts.append(f"連続陰線: {int(abs(consec))}本")

    return "\n".join(parts)


def build_free_analysis_prompt(
    featured_data: Dict,
    current_price: float,
    signals_today: int = 0,
    recent_results: str = "まだなし",
) -> str:
    """Build prompt for free AI analysis (no pre-filtered candidate)."""
    from src.features.engine import get_latest_features

    m5_features = get_latest_features(featured_data.get("M5"))
    m15_features = get_latest_features(featured_data.get("M15"))
    h1_features = get_latest_features(featured_data.get("H1"))
    h4_features = get_latest_features(featured_data.get("H4"))

    return USER_PROMPT_TEMPLATE.format(
        current_price=f"{current_price:.2f}",
        m5_summary=_format_candle_summary(m5_features),
        m15_summary=_format_candle_summary(m15_features),
        h1_summary=_format_candle_summary(h1_features),
        h4_summary=_format_candle_summary(h4_features),
        signals_today=signals_today,
        recent_results=recent_results,
    )


def analyze_market(
    featured_data: Dict,
    current_price: float,
    settings: Settings,
    signals_today: int = 0,
    recent_results: str = "まだなし",
) -> Optional[Dict]:
    """
    Let ChatGPT freely analyze market data and decide entry.
    No pre-filtering - AI has full autonomy.
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package not installed")
        return None

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not set")
        return None

    user_prompt = build_free_analysis_prompt(
        featured_data, current_price, signals_today, recent_results
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.ai_model,
            max_tokens=1024,
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = response.choices[0].message.content.strip()
        logger.info(f"AI raw response: {raw_text[:300]}")

        ai_output = _parse_ai_response(raw_text)
        if ai_output is None:
            logger.error("Failed to parse AI response as JSON")
            return None

        # Attach raw data for logging
        ai_output["_ai_input"] = user_prompt
        ai_output["_ai_raw_output"] = raw_text

        return ai_output

    except Exception as e:
        logger.error(f"AI analysis error: {e}")
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
