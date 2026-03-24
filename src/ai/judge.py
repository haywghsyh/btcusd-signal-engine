"""
AI Judge - ChatGPT freely analyzes BTCUSD market data and decides entries.
No pre-filtered candidates. AI has full autonomy to decide BUY/SELL/NO_TRADE.
"""
import json
import logging
from typing import Dict, List, Optional

from src.config.settings import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたはBTCUSD（ビットコイン）専門のプロトレーダーです。
市場データを分析し、自分の判断でエントリーシグナルを出してください。

【トレードスタイル】
- 短期〜中期トレード（保有時間: 数分〜数時間、最大1日程度）
- M5/M15でエントリータイミングを計り、H1/H4でトレンド方向とターゲットを決める
- 1 pip = 1.0 USD（BTCUSD）
- SL目安: 150〜500pips（市場構造に基づく。ATRも参考に）
- TP3目安: 300〜1500pips（大きなトレンドに乗る場合はさらに広くてよい）

【重要な方針】
- 勝率を意識しつつも、積極的にエントリーチャンスを探すこと（目標: 60%以上）
- 少しでも優位性があればエントリーする。完璧な条件を待たない
- 1日8〜15回程度のシグナルを目標（積極的にチャンスを拾う）
- エントリー理由を明確に説明すること
- 明確にリスクが高い場合のみNO_TRADEにする。迷ったらエントリーする側に倒す
- BTCは24時間取引可能。ボラティリティの急変に注意

【分析のポイント】
- M5, M15でエントリーポイントを精密に決定
- H1, H4でトレンド方向と大きなサポレジを確認し、TPターゲットに活用
- EMA, RSI, ATRなどのテクニカル指標を参考に
- サポート/レジスタンスレベルを意識（H1/H4レベルの重要な水準）
- ローソク足のパターンや勢いを見る
- トレンドフォロー、反転、レンジブレイクなど多様な手法でチャンスを探す
- RSIの買われすぎ/売られすぎだけでNO_TRADEにしない。他の根拠と組み合わせて判断する
- BTCはボラティリティが高いため、急騰急落のモメンタムにも注目

【SL/TP設定 - 最重要ルール】
- SL/TPは必ず提供されたローソク足データの実際の価格構造に基づいて設定すること
- 絶対に等間隔（100刻み等）で適当に設定してはならない
- SLの設定根拠:
  - BUYの場合: 直近のスイングロー（安値）の少し下に置く
  - SELLの場合: 直近のスイングハイ（高値）の少し上に置く
  - M5/M15の直近ローソク足のOHLCデータを見て、実際の高値/安値を確認して決める
- TPの設定根拠:
  - TP1: M15レベルの直近サポレジ（堅実な利確）
  - TP2: H1レベルのサポレジ/EMAライン（標準的な利確）
  - TP3: H4レベルの大きなサポレジ/トレンドターゲット（大きく伸ばす利確）
  - ATRを考慮して現実的な目標を設定
  - TP1/TP2/TP3はそれぞれ異なる時間軸の根拠に基づくこと（等間隔禁止）
- BUYの場合: SL < Entry < TP1 < TP2 < TP3
- SELLの場合: TP3 < TP2 < TP1 < Entry < SL

必ず有効なJSONのみで返答してください。"""

USER_PROMPT_TEMPLATE = """以下のBTCUSD市場データを分析し、エントリーすべきか判断してください。

【現在価格】{current_price}

【M5（5分足）テクニカル指標】
{m5_summary}

【M5 直近ローソク足（SL/TP設定の参考に）】
{m5_ohlc}

【M15（15分足）テクニカル指標】
{m15_summary}

【M15 直近ローソク足】
{m15_ohlc}

【H1（1時間足）コンテキスト】
{h1_summary}

【H4（4時間足）トレンド】
{h4_summary}

【本日のシグナル状況】
- 発行済みシグナル数: {signals_today}
- 直近の結果: {recent_results}

エントリーする場合（SL/TPは上記ローソク足の高値/安値を根拠に設定すること。等間隔は禁止）:
{{
  "symbol": "BTCUSD",
  "decision": "BUY" or "SELL",
  "entry_type": "MARKET",
  "current_price": <現在価格>,
  "sl": <ストップロス（直近の高値/安値を根拠に）>,
  "tp1": <利確1（最寄りのサポレジ）>,
  "tp2": <利確2（次のサポレジ/EMAライン）>,
  "tp3": <利確3（さらに先のターゲット）>,
  "risk_reward_tp3": <リスクリワード比>,
  "confidence": <0-100>,
  "invalidate_if": "<無効条件>",
  "reason": "<エントリー理由とSL/TP根拠を日本語で簡潔に>"
}}

見送る場合:
{{
  "symbol": "BTCUSD",
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
        ("swing_high", "20本高値"), ("swing_low", "20本安値"),
        ("recent_high", "10本高値"), ("recent_low", "10本安値"),
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


def _format_recent_ohlc(df, num_candles: int = 10) -> str:
    """Format recent OHLC candle data for AI to analyze price structure."""
    if df is None or len(df) == 0:
        return "データなし"

    recent = df.tail(num_candles)
    lines = ["番号 | 始値 | 高値 | 安値 | 終値"]
    for i, (_, row) in enumerate(recent.iterrows(), 1):
        o = row.get("open", 0)
        h = row.get("high", 0)
        l = row.get("low", 0)
        c = row.get("close", 0)
        lines.append(f"{i} | {o:.1f} | {h:.1f} | {l:.1f} | {c:.1f}")
    return "\n".join(lines)


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
        m5_ohlc=_format_recent_ohlc(featured_data.get("M5"), 10),
        m15_summary=_format_candle_summary(m15_features),
        m15_ohlc=_format_recent_ohlc(featured_data.get("M15"), 8),
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
