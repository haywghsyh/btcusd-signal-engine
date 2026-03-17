"""
Telegram Notifier - Sends signal notifications to Telegram.
"""
import logging
from typing import Dict, Optional

import requests

from src.config.settings import Settings

logger = logging.getLogger(__name__)

SIGNAL_TEMPLATE = """🔔 【XAUUSD SIGNAL】

📊 Direction: {decision}
💰 Entry: MARKET
💲 Price: {current_price}

🛑 SL: {sl}
🎯 TP1: {tp1}
🎯 TP2: {tp2}
🎯 TP3: {tp3}

📈 RR(TP3): {risk_reward_tp3}
🔒 Confidence: {confidence}%

⚠️ Invalidate: {invalidate_if}

📝 {reason}"""

TP_HIT_TEMPLATE = """✅ 【TP{tp_level} HIT】

📊 {direction} @ {entry_price}
🎯 TP{tp_level}: {exit_price}
💰 +{pnl_pips:.1f} pips

{progress}"""

SL_HIT_TEMPLATE = """❌ 【SL HIT】

📊 {direction} @ {entry_price}
🛑 SL: {exit_price}
💸 {pnl_pips:.1f} pips

{tp_status}"""

DASHBOARD_TEMPLATE = """📊 【XAUUSD 成績レポート】

🏆 勝率: {win_rate}% ({wins}W / {losses}L)
📈 合計: {total_pnl_pips:+.1f} pips ({total_trades}トレード)

💰 平均利益: +{avg_win_pips:.1f} pips
💸 平均損失: {avg_loss_pips:.1f} pips
🔥 ベスト: +{best_trade_pips:.1f} pips
❄️ ワースト: {worst_trade_pips:.1f} pips

🎯 TP1到達率: {tp1_hit_rate}%
🎯 TP2到達率: {tp2_hit_rate}%
🎯 TP3到達率: {tp3_hit_rate}%

{streak_text}"""


def format_signal_message(signal: Dict) -> str:
    """Format a signal dict into a Telegram message string."""
    return SIGNAL_TEMPLATE.format(
        decision=signal.get("decision", "N/A"),
        current_price=f"{float(signal.get('current_price', 0)):.1f}",
        sl=f"{float(signal.get('sl', 0)):.1f}",
        tp1=f"{float(signal.get('tp1', 0)):.1f}",
        tp2=f"{float(signal.get('tp2', 0)):.1f}",
        tp3=f"{float(signal.get('tp3', 0)):.1f}",
        risk_reward_tp3=f"{float(signal.get('risk_reward_tp3', 0)):.2f}",
        confidence=signal.get("confidence", 0),
        invalidate_if=signal.get("invalidate_if", "N/A"),
        reason=signal.get("reason", "N/A"),
    )


class TelegramNotifier:
    """Sends messages to Telegram via Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self, settings: Settings):
        self.token = settings.telegram_token
        self.chat_id = settings.telegram_chat_id
        self._enabled = bool(self.token and self.chat_id)
        if not self._enabled:
            logger.warning("Telegram not configured - notifications disabled")

    def send_signal(self, signal: Dict) -> bool:
        """Send a formatted signal to Telegram. Returns True on success."""
        decision = signal.get("decision", "").upper()
        if decision == "NO_TRADE":
            logger.info("NO_TRADE - skipping Telegram notification")
            return False

        if not self._enabled:
            logger.warning("Telegram disabled - would have sent signal")
            return False

        message = format_signal_message(signal)
        return self._send_message(message)

    def send_tp_hit(self, event: Dict) -> bool:
        """Send TP hit notification."""
        if not self._enabled:
            return False

        pos = event.get("position", {})
        tp_level = event["event_type"].replace("TP", "").replace("_HIT", "")

        # Build progress bar
        progress_parts = []
        for i in range(1, 4):
            hit = pos.get(f"tp{i}_hit", False)
            progress_parts.append(f"TP{i} {'✅' if hit else '⬜'}")
        progress = " | ".join(progress_parts)

        message = TP_HIT_TEMPLATE.format(
            tp_level=tp_level,
            direction=pos.get("direction", "?"),
            entry_price=f"{pos.get('entry_price', 0):.1f}",
            exit_price=f"{event.get('exit_price', 0):.1f}",
            pnl_pips=event.get("pnl_pips", 0),
            progress=progress,
        )
        return self._send_message(message)

    def send_sl_hit(self, event: Dict) -> bool:
        """Send SL hit notification."""
        if not self._enabled:
            return False

        pos = event.get("position", {})

        # Show which TPs were hit before SL
        tp_parts = []
        for i in range(1, 4):
            if pos.get(f"tp{i}_hit"):
                tp_parts.append(f"TP{i} ✅")
        tp_status = "到達済み: " + ", ".join(tp_parts) if tp_parts else "TP未到達"

        message = SL_HIT_TEMPLATE.format(
            direction=pos.get("direction", "?"),
            entry_price=f"{pos.get('entry_price', 0):.1f}",
            exit_price=f"{event.get('exit_price', 0):.1f}",
            pnl_pips=event.get("pnl_pips", 0),
            tp_status=tp_status,
        )
        return self._send_message(message)

    def send_dashboard(self, stats: Dict) -> bool:
        """Send performance dashboard."""
        if not self._enabled:
            return False

        streak = stats.get("current_streak", 0)
        if streak > 0:
            streak_text = f"🔥 現在 {streak}連勝中！"
        elif streak < 0:
            streak_text = f"❄️ 現在 {abs(streak)}連敗中"
        else:
            streak_text = ""

        message = DASHBOARD_TEMPLATE.format(
            **stats,
            streak_text=streak_text,
        )
        return self._send_message(message)

    def send_raw(self, text: str) -> bool:
        """Send a raw text message."""
        if not self._enabled:
            return False
        return self._send_message(text)

    def _send_message(self, text: str) -> bool:
        url = f"{self.BASE_URL.format(token=self.token)}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
                return False
        except requests.RequestException as e:
            logger.error(f"Telegram request error: {e}")
            return False

    def send_startup_message(self) -> bool:
        return self.send_raw("🟢 XAUUSD Signal Engine started.")

    def send_error(self, error_msg: str) -> bool:
        return self.send_raw(f"🔴 Signal Engine Error:\n{error_msg}")
