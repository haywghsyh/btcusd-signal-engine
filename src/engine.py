"""
Signal Engine Orchestrator - Coordinates the full signal pipeline.

Flow: Data → Features → Classify → Candidate → AI Judge → Risk Filter → Notify → Log
"""
import logging
from typing import Dict, Optional

from src.config.settings import Settings
from src.data.receiver import MarketDataReceiver
from src.features.engine import compute_all_features, get_latest_features
from src.classifier.market_state import classify_all
from src.signals.generator import generate_candidate
from src.ai.judge import evaluate_candidate
from src.risk.filter import validate_signal, enrich_signal
from src.notifier.telegram import TelegramNotifier
from src.storage.database import SignalDatabase
from src.tracker.position import PositionTracker
from src.utils.time_utils import now_jst

logger = logging.getLogger(__name__)


class SignalEngine:
    """Main orchestrator for the XAUUSD signal pipeline."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.receiver = MarketDataReceiver(settings)
        self.notifier = TelegramNotifier(settings)
        self.db = SignalDatabase(settings)
        self.tracker = PositionTracker()
        self._restore_open_positions()

    def process_webhook(self, payload: Dict) -> bool:
        """Process a TradingView webhook and potentially trigger signal analysis."""
        success = self.receiver.process_webhook(payload)

        # Check open positions against new price data
        if success and payload.get("timeframe", "").upper() == "M5":
            high = float(payload.get("high", 0))
            low = float(payload.get("low", 0))
            close = float(payload.get("close", 0))
            if high > 0 and low > 0:
                self._check_positions(high, low, close)

        return success

    def run_analysis(self) -> Optional[Dict]:
        """
        Run the full signal pipeline. Returns the signal dict or None.
        Should be called after enough data has been accumulated.
        """
        # Step 0: Check trading session
        jst_now = now_jst()
        if not self.settings.is_trading_session(jst_now.hour, jst_now.minute):
            session = self.settings.get_active_session(jst_now.hour, jst_now.minute)
            logger.info(f"Outside trading session ({session}) - NO_TRADE")
            no_trade = {
                "symbol": "XAUUSD",
                "decision": "NO_TRADE",
                "reason": f"Outside trading session: {session}",
                "confidence": 0,
            }
            self.db.save_signal(no_trade)
            return no_trade

        # Step 1: Get data
        data = self.receiver.get_all_dataframes()
        if data is None:
            logger.warning("Insufficient data for analysis")
            return None

        current_price = self.receiver.get_current_price()
        if current_price is None:
            logger.warning("No current price available")
            return None

        # Step 2: Compute features
        featured_data = compute_all_features(data)
        if featured_data is None:
            logger.error("Feature computation failed")
            return None

        # Step 3: Classify market states
        states = classify_all(featured_data)
        if states is None:
            logger.error("Market state classification failed")
            return None

        # Step 4: Generate signal candidate
        candidate = generate_candidate(states, featured_data, current_price, self.settings)
        if candidate is None:
            no_trade = {
                "symbol": "XAUUSD",
                "decision": "NO_TRADE",
                "reason": "No valid signal candidate",
                "confidence": 0,
            }
            self.db.save_signal(no_trade, market_context=states)
            logger.info("No signal candidate generated")
            return no_trade

        # Step 5: AI evaluation
        ai_output = evaluate_candidate(candidate, featured_data, self.settings)
        if ai_output is None:
            logger.error("AI evaluation failed")
            no_trade = {
                "symbol": "XAUUSD",
                "decision": "NO_TRADE",
                "reason": "AI evaluation failed",
                "confidence": 0,
            }
            self.db.save_signal(no_trade, market_context=states)
            return no_trade

        # Step 6: Risk filter
        spread = current_price.get("spread", 0)
        is_valid, rejection_reason = validate_signal(ai_output, self.settings, spread)

        if not is_valid:
            logger.warning(f"Signal rejected by risk filter: {rejection_reason}")
            ai_output["decision"] = "NO_TRADE"
            ai_output["reason"] = f"Risk filter: {rejection_reason}"
            self.db.save_signal(
                ai_output, market_context=states,
                features=self._collect_features_snapshot(featured_data),
            )
            return ai_output

        # Enrich with computed fields
        ai_output = enrich_signal(ai_output)

        # Step 7: Duplicate check
        decision = ai_output.get("decision", "").upper()
        price = float(ai_output.get("current_price", 0))

        if decision in ("BUY", "SELL"):
            if self.db.is_duplicate(decision, price, self.settings.signal_cooldown_seconds):
                logger.info("Duplicate signal - skipping notification")
                self.db.save_signal(
                    ai_output, market_context=states,
                    features=self._collect_features_snapshot(featured_data),
                    notification_sent=False,
                )
                return ai_output

        # Step 8: Telegram notification
        notification_sent = False
        if decision in ("BUY", "SELL"):
            notification_sent = self.notifier.send_signal(ai_output)

        # Step 9: Save to database
        signal_id = self.db.save_signal(
            ai_output, market_context=states,
            features=self._collect_features_snapshot(featured_data),
            notification_sent=notification_sent,
        )

        # Step 10: Register position for tracking
        if decision in ("BUY", "SELL") and signal_id:
            self.tracker.open_position(signal_id, ai_output)

        logger.info(
            f"Signal pipeline complete: {decision} "
            f"(notified={notification_sent})"
        )
        return ai_output

    def get_status(self) -> Dict:
        """Get engine status for health checks."""
        jst_now = now_jst()
        return {
            "symbol": self.settings.symbol,
            "data_status": self.receiver.get_status(),
            "trading_session": self.settings.get_active_session(jst_now.hour, jst_now.minute),
            "time_jst": jst_now.isoformat(),
            "recent_signals": len(self.db.get_recent_signals(5)),
        }

    def _check_positions(self, high: float, low: float, close: float):
        """Check open positions against price and send notifications."""
        events = self.tracker.check_price(high, low, close)
        for event in events:
            event_type = event["event_type"]
            signal_id = event["signal_id"]

            # Update database
            self.db.update_trade_event(
                signal_id, event_type,
                event["exit_price"], event["pnl_pips"],
            )

            # Send Telegram notification
            if event_type == "SL_HIT":
                self.notifier.send_sl_hit(event)
            elif event_type in ("TP1_HIT", "TP2_HIT", "TP3_HIT"):
                self.notifier.send_tp_hit(event)

    def _restore_open_positions(self):
        """Restore open positions from database on startup."""
        open_trades = self.db.get_open_trades()
        for trade in open_trades:
            signal_id = trade["signal_id"]
            signal = {
                "decision": trade["decision"],
                "current_price": trade["entry_price"],
                "sl": trade["sl"],
                "tp1": trade["tp1"],
                "tp2": trade["tp2"],
                "tp3": trade["tp3"],
                "confidence": trade.get("confidence", 0),
            }
            self.tracker.open_position(signal_id, signal)
            # Restore TP hit state
            pos = self.tracker._open_positions.get(signal_id)
            if pos:
                pos["tp1_hit"] = bool(trade.get("tp1_hit"))
                pos["tp2_hit"] = bool(trade.get("tp2_hit"))
                pos["tp3_hit"] = bool(trade.get("tp3_hit"))
        if open_trades:
            logger.info(f"Restored {len(open_trades)} open positions from database")

    def get_performance(self) -> Dict:
        """Get trading performance statistics."""
        return self.db.get_performance_stats()

    def _collect_features_snapshot(self, featured_data: Dict) -> Dict:
        """Collect latest features from all timeframes for logging."""
        snapshot = {}
        for tf, df in featured_data.items():
            snapshot[tf] = get_latest_features(df)
        return snapshot
