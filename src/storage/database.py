"""
Signal Logger / Storage - SQLite database for signal history and trade results.
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
    notification_sent INTEGER DEFAULT 0,
    status TEXT DEFAULT 'open',
    tp1_hit INTEGER DEFAULT 0,
    tp2_hit INTEGER DEFAULT 0,
    tp3_hit INTEGER DEFAULT 0,
    sl_hit INTEGER DEFAULT 0,
    exit_price REAL,
    exit_time TEXT,
    pnl_pips REAL,
    result TEXT
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_decision ON signals(decision);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
"""

MIGRATION_COLUMNS = [
    ("status", "TEXT DEFAULT 'open'"),
    ("tp1_hit", "INTEGER DEFAULT 0"),
    ("tp2_hit", "INTEGER DEFAULT 0"),
    ("tp3_hit", "INTEGER DEFAULT 0"),
    ("sl_hit", "INTEGER DEFAULT 0"),
    ("exit_price", "REAL"),
    ("exit_time", "TEXT"),
    ("pnl_pips", "REAL"),
    ("result", "TEXT"),
]


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
            # Migrate existing tables: add new columns if missing
            cursor = conn.execute("PRAGMA table_info(signals)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            for col_name, col_def in MIGRATION_COLUMNS:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Added column: {col_name}")
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

    def update_trade_event(self, signal_id: str, event_type: str,
                           exit_price: float, pnl_pips: float) -> bool:
        """Update a signal with TP/SL hit event."""
        try:
            conn = sqlite3.connect(self.db_path)
            now = datetime.now(timezone.utc).isoformat()

            if event_type == "SL_HIT":
                conn.execute(
                    """UPDATE signals SET sl_hit = 1, status = 'closed',
                       exit_price = ?, exit_time = ?, pnl_pips = ?, result = 'LOSS'
                       WHERE signal_id = ?""",
                    (exit_price, now, pnl_pips, signal_id),
                )
            elif event_type == "TP1_HIT":
                conn.execute(
                    "UPDATE signals SET tp1_hit = 1 WHERE signal_id = ?",
                    (signal_id,),
                )
            elif event_type == "TP2_HIT":
                conn.execute(
                    "UPDATE signals SET tp2_hit = 1 WHERE signal_id = ?",
                    (signal_id,),
                )
            elif event_type == "TP3_HIT":
                conn.execute(
                    """UPDATE signals SET tp3_hit = 1, status = 'closed',
                       exit_price = ?, exit_time = ?, pnl_pips = ?, result = 'WIN'
                       WHERE signal_id = ?""",
                    (exit_price, now, pnl_pips, signal_id),
                )

            conn.commit()
            conn.close()
            logger.info(f"Trade event updated: {signal_id} {event_type}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Trade event update error: {e}")
            return False

    def get_open_trades(self) -> List[Dict]:
        """Get all open (active) trades."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM signals
                   WHERE status = 'open' AND decision IN ('BUY', 'SELL')
                   ORDER BY timestamp DESC""",
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except sqlite3.Error as e:
            logger.error(f"Get open trades error: {e}")
            return []

    def get_performance_stats(self) -> Dict:
        """Calculate trading performance statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            # All closed trades
            cursor = conn.execute(
                """SELECT * FROM signals
                   WHERE status = 'closed' AND decision IN ('BUY', 'SELL')
                   ORDER BY exit_time DESC""",
            )
            trades = [dict(r) for r in cursor.fetchall()]
            conn.close()

            if not trades:
                return {
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "total_pnl_pips": 0.0,
                    "avg_win_pips": 0.0,
                    "avg_loss_pips": 0.0,
                    "best_trade_pips": 0.0,
                    "worst_trade_pips": 0.0,
                    "current_streak": 0,
                    "tp1_hit_rate": 0.0,
                    "tp2_hit_rate": 0.0,
                    "tp3_hit_rate": 0.0,
                }

            total = len(trades)
            wins = [t for t in trades if t["result"] == "WIN"]
            losses = [t for t in trades if t["result"] == "LOSS"]
            win_pnls = [t["pnl_pips"] for t in wins if t["pnl_pips"] is not None]
            loss_pnls = [t["pnl_pips"] for t in losses if t["pnl_pips"] is not None]
            all_pnls = [t["pnl_pips"] for t in trades if t["pnl_pips"] is not None]

            # Current streak
            streak = 0
            if trades:
                streak_result = trades[0].get("result")
                for t in trades:
                    if t.get("result") == streak_result:
                        streak += 1 if streak_result == "WIN" else -1
                    else:
                        break

            # TP hit rates (across all closed trades)
            tp1_hits = sum(1 for t in trades if t.get("tp1_hit"))
            tp2_hits = sum(1 for t in trades if t.get("tp2_hit"))
            tp3_hits = sum(1 for t in trades if t.get("tp3_hit"))

            return {
                "total_trades": total,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / total * 100, 1) if total else 0.0,
                "total_pnl_pips": round(sum(all_pnls), 1),
                "avg_win_pips": round(sum(win_pnls) / len(win_pnls), 1) if win_pnls else 0.0,
                "avg_loss_pips": round(sum(loss_pnls) / len(loss_pnls), 1) if loss_pnls else 0.0,
                "best_trade_pips": round(max(all_pnls), 1) if all_pnls else 0.0,
                "worst_trade_pips": round(min(all_pnls), 1) if all_pnls else 0.0,
                "current_streak": streak,
                "tp1_hit_rate": round(tp1_hits / total * 100, 1) if total else 0.0,
                "tp2_hit_rate": round(tp2_hits / total * 100, 1) if total else 0.0,
                "tp3_hit_rate": round(tp3_hits / total * 100, 1) if total else 0.0,
            }
        except sqlite3.Error as e:
            logger.error(f"Performance stats error: {e}")
            return {}

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
