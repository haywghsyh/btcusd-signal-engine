"""
Signal Logger / Storage - SQLite database for signal history.
"""
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.config.settings import Settings

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    entry_price REAL,
    sl REAL,
    tp1 REAL,
    tp2 REAL,
    tp3 REAL,
    risk_reward REAL,
    confidence INTEGER,
    reason TEXT,
    invalidate_if TEXT,
    market_context TEXT,
    features_snapshot TEXT,
    ai_input TEXT,
    ai_output TEXT,
    notification_sent INTEGER DEFAULT 0
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_decision ON signals(decision);
"""


class SignalDatabase:
    """SQLite-based signal storage."""

    def __init__(self, settings: Settings):
        self.db_path = settings.db_path
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(CREATE_TABLE_SQL)
            for sql in CREATE_INDEX_SQL.strip().split(";"):
                sql = sql.strip()
                if sql:
                    conn.execute(sql)
            conn.commit()
            conn.close()
            logger.info(f"Database initialized: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Database init error: {e}")

    def save_signal(self, signal: Dict, market_context: Dict = None,
                    features: Dict = None, notification_sent: bool = False) -> str:
        """Save a signal to the database. Returns signal_id."""
        signal_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()

        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO signals (
                    signal_id, timestamp, symbol, decision, entry_price,
                    sl, tp1, tp2, tp3, risk_reward, confidence,
                    reason, invalidate_if, market_context, features_snapshot,
                    ai_input, ai_output, notification_sent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal_id, now,
                    signal.get("symbol", "XAUUSD"),
                    signal.get("decision", "UNKNOWN"),
                    signal.get("current_price"),
                    signal.get("sl"),
                    signal.get("tp1"),
                    signal.get("tp2"),
                    signal.get("tp3"),
                    signal.get("risk_reward_tp3"),
                    signal.get("confidence"),
                    signal.get("reason"),
                    signal.get("invalidate_if"),
                    json.dumps(market_context) if market_context else None,
                    json.dumps(features, default=str) if features else None,
                    signal.get("_ai_input"),
                    signal.get("_ai_raw_output"),
                    1 if notification_sent else 0,
                ),
            )
            conn.commit()
            conn.close()
            logger.info(f"Signal saved: {signal_id} ({signal.get('decision')})")
            return signal_id

        except sqlite3.Error as e:
            logger.error(f"Database save error: {e}")
            return ""

    def get_recent_signals(self, limit: int = 10) -> List[Dict]:
        """Get most recent signals."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except sqlite3.Error as e:
            logger.error(f"Database read error: {e}")
            return []

    def get_last_signal_by_direction(self, direction: str) -> Optional[Dict]:
        """Get the most recent signal for a given direction."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM signals WHERE decision = ? ORDER BY timestamp DESC LIMIT 1",
                (direction,),
            )
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Database read error: {e}")
            return None

    def is_duplicate(self, direction: str, price: float,
                     cooldown_seconds: int) -> bool:
        """Check if a similar signal was recently sent."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM signals
                   WHERE decision = ? AND notification_sent = 1
                   ORDER BY timestamp DESC LIMIT 1""",
                (direction,),
            )
            row = cursor.fetchone()
            conn.close()

            if row is None:
                return False

            last = dict(row)
            last_time = datetime.fromisoformat(last["timestamp"])
            now = datetime.now(timezone.utc)

            # Time check
            elapsed = (now - last_time).total_seconds()
            if elapsed < cooldown_seconds:
                # Price proximity check (within 2 pips = 0.2 USD)
                last_price = last.get("entry_price", 0) or 0
                if abs(price - last_price) < 2.0:
                    logger.info(
                        f"Duplicate signal detected: {direction} at {price:.1f} "
                        f"(last: {last_price:.1f}, {elapsed:.0f}s ago)"
                    )
                    return True

            return False

        except (sqlite3.Error, Exception) as e:
            logger.error(f"Duplicate check error: {e}")
            return False
