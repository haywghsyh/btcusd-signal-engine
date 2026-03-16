"""
Telegram Notifier - Sends signal notifications to Telegram.
"""
import logging
from typing import Dict, Optional

import requests

from src.config.settings import Settings

logger = logging.getLogger(__name__)

SIGNAL_TEMPLATE = """🔔 【XAUUSD SIGNAL】

📊 Decision: {decision}
💰 Entry: MARKET
💲 Current Price: {current_price}

🛑 SL: {sl}
🎯 TP1: {tp1}
🎯 TP2: {tp2}
🎯 TP3: {tp3}

📈 RR(TP3): {risk_reward_tp3}
🔒 Confidence: {confidence}%

⚠️ Invalidate: {invalidate_if}

📝 Reason: {reason}"""


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
