"""
Position Tracker - Monitors open positions and detects TP/SL hits.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks open positions and checks if price hits TP or SL."""

    def __init__(self):
        # {signal_id: position_dict}
        self._open_positions: Dict[str, Dict] = {}

    def open_position(self, signal_id: str, signal: Dict):
        """Register a new open position from a signal."""
        decision = signal.get("decision", "").upper()
        if decision not in ("BUY", "SELL"):
            return

        position = {
            "signal_id": signal_id,
            "direction": decision,
            "entry_price": float(signal.get("current_price", 0)),
            "sl": float(signal.get("sl", 0)),
            "tp1": float(signal.get("tp1", 0)),
            "tp2": float(signal.get("tp2", 0)),
            "tp3": float(signal.get("tp3", 0)),
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "confidence": signal.get("confidence", 0),
        }
        self._open_positions[signal_id] = position
        logger.info(f"Position opened: {signal_id} {decision} @ {position['entry_price']:.1f}")

    def check_price(self, high: float, low: float, close: float) -> List[Dict]:
        """
        Check all open positions against current candle's high/low.
        Returns list of events: {signal_id, event_type, price, position}
        """
        events = []
        closed_ids = []

        for sig_id, pos in self._open_positions.items():
            direction = pos["direction"]
            sl = pos["sl"]
            tp1 = pos["tp1"]
            tp2 = pos["tp2"]
            tp3 = pos["tp3"]

            # Check SL hit
            sl_hit = False
            if direction == "BUY" and low <= sl:
                sl_hit = True
            elif direction == "SELL" and high >= sl:
                sl_hit = True

            if sl_hit:
                pnl = self._calc_pnl(pos, sl)
                events.append({
                    "signal_id": sig_id,
                    "event_type": "SL_HIT",
                    "exit_price": sl,
                    "pnl_pips": pnl,
                    "position": pos.copy(),
                })
                closed_ids.append(sig_id)
                continue

            # Check TP hits (progressive: TP1 → TP2 → TP3)
            if direction == "BUY":
                if not pos["tp1_hit"] and high >= tp1:
                    pos["tp1_hit"] = True
                    events.append({
                        "signal_id": sig_id,
                        "event_type": "TP1_HIT",
                        "exit_price": tp1,
                        "pnl_pips": self._calc_pnl(pos, tp1),
                        "position": pos.copy(),
                    })
                if not pos["tp2_hit"] and high >= tp2:
                    pos["tp2_hit"] = True
                    events.append({
                        "signal_id": sig_id,
                        "event_type": "TP2_HIT",
                        "exit_price": tp2,
                        "pnl_pips": self._calc_pnl(pos, tp2),
                        "position": pos.copy(),
                    })
                if not pos["tp3_hit"] and high >= tp3:
                    pos["tp3_hit"] = True
                    events.append({
                        "signal_id": sig_id,
                        "event_type": "TP3_HIT",
                        "exit_price": tp3,
                        "pnl_pips": self._calc_pnl(pos, tp3),
                        "position": pos.copy(),
                    })
                    closed_ids.append(sig_id)

            elif direction == "SELL":
                if not pos["tp1_hit"] and low <= tp1:
                    pos["tp1_hit"] = True
                    events.append({
                        "signal_id": sig_id,
                        "event_type": "TP1_HIT",
                        "exit_price": tp1,
                        "pnl_pips": self._calc_pnl(pos, tp1),
                        "position": pos.copy(),
                    })
                if not pos["tp2_hit"] and low <= tp2:
                    pos["tp2_hit"] = True
                    events.append({
                        "signal_id": sig_id,
                        "event_type": "TP2_HIT",
                        "exit_price": tp2,
                        "pnl_pips": self._calc_pnl(pos, tp2),
                        "position": pos.copy(),
                    })
                if not pos["tp3_hit"] and low <= tp3:
                    pos["tp3_hit"] = True
                    events.append({
                        "signal_id": sig_id,
                        "event_type": "TP3_HIT",
                        "exit_price": tp3,
                        "pnl_pips": self._calc_pnl(pos, tp3),
                        "position": pos.copy(),
                    })
                    closed_ids.append(sig_id)

        # Remove fully closed positions
        for sig_id in closed_ids:
            del self._open_positions[sig_id]
            logger.info(f"Position closed: {sig_id}")

        return events

    def get_open_positions(self) -> List[Dict]:
        return list(self._open_positions.values())

    def get_open_count(self) -> int:
        return len(self._open_positions)

    def _calc_pnl(self, pos: Dict, exit_price: float) -> float:
        """Calculate PnL in pips. BTCUSD: 1 pip = $1.0"""
        entry = pos["entry_price"]
        if pos["direction"] == "BUY":
            return (exit_price - entry) / 1.0
        else:
            return (entry - exit_price) / 1.0
