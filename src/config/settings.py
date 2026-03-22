"""
BTCUSD Signal Engine - Configuration Settings
All values can be overridden via environment variables.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SessionTime:
    """Trading session time window (JST hours/minutes)."""
    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int

    def contains(self, hour: int, minute: int) -> bool:
        start = self.start_hour * 60 + self.start_minute
        end = self.end_hour * 60 + self.end_minute
        current = hour * 60 + minute
        if end < start:  # crosses midnight
            return current >= start or current < end
        return start <= current < end


@dataclass
class Settings:
    symbol: str = "BTCUSD"
    timeframes: List[str] = field(default_factory=lambda: ["H4", "H1", "M15", "M5"])

    min_candles: Dict[str, int] = field(default_factory=lambda: {
        "H4": 50, "H1": 50, "M15": 50, "M5": 50,
    })

    # AI
    ai_model: str = "gpt-4o-mini"
    openai_api_key: str = ""

    # Risk (relaxed - AI decides freely, only sanity checks)
    max_sl_pips: float = 500.0
    min_rr: float = 0.5
    spread_threshold_pips: float = 50.0

    # Cooldown (shorter for scalping)
    signal_cooldown_seconds: int = 600

    # Sessions (BTC trades 24/7 - cover all hours)
    session_times: List[SessionTime] = field(default_factory=lambda: [
        SessionTime("Asia", 0, 0, 8, 0),
        SessionTime("London", 8, 0, 16, 0),
        SessionTime("NewYork", 16, 0, 24, 0),
    ])

    # Telegram
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # Storage
    db_path: str = "signals.db"

    # Logging
    log_level: str = "INFO"
    log_file: str = "signal_engine.log"

    # Webhook server
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    def __post_init__(self):
        env_map = {
            "TELEGRAM_TOKEN": "telegram_token",
            "TELEGRAM_CHAT_ID": "telegram_chat_id",
            "OPENAI_API_KEY": "openai_api_key",
            "DB_PATH": "db_path",
            "LOG_LEVEL": "log_level",
            "AI_MODEL": "ai_model",
            "WEBHOOK_HOST": "webhook_host",
        }
        for env_key, attr in env_map.items():
            val = os.getenv(env_key)
            if val:
                setattr(self, attr, val)

        float_env = {"MAX_SL_PIPS": "max_sl_pips", "MIN_RR": "min_rr",
                      "SPREAD_THRESHOLD_PIPS": "spread_threshold_pips"}
        for env_key, attr in float_env.items():
            val = os.getenv(env_key)
            if val:
                setattr(self, attr, float(val))

        int_env = {"WEBHOOK_PORT": "webhook_port", "SIGNAL_COOLDOWN": "signal_cooldown_seconds"}
        for env_key, attr in int_env.items():
            val = os.getenv(env_key)
            if val:
                setattr(self, attr, int(val))

    def is_trading_session(self, hour_jst: int, minute_jst: int) -> bool:
        return any(s.contains(hour_jst, minute_jst) for s in self.session_times)

    def get_active_session(self, hour_jst: int, minute_jst: int) -> str:
        for s in self.session_times:
            if s.contains(hour_jst, minute_jst):
                return s.name
        return "CLOSED"


# BTCUSD: 1 pip = 1.0 USD
BTCUSD_PIP_SIZE = 1.0


def price_to_pips(price_diff: float) -> float:
    return abs(price_diff) / BTCUSD_PIP_SIZE


def pips_to_price(pips: float) -> float:
    return pips * BTCUSD_PIP_SIZE
