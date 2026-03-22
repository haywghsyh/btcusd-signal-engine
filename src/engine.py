"""
Signal Engine Orchestrator - ChatGPT freely analyzes market and decides entries.

Flow: Data → Features → AI (free analysis) → Risk Filter → Notify → Log
No hardcoded entry conditions. AI has full autonomy.
"""
import logging
from datetime import datetime
from typing import Dict, Optional

from src.config.settings import Settings
from src.data.receiver import MarketDataReceiver
from src.features.engine import compute_all_features
from src.ai.judge import analyze_market
from src.risk.filter import validate_signal, enrich_signal
from src.notifier.telegram import TelegramNotifier
from src.storage.database import SignalDatabase
from src.tracker.position import PositionTracker
from src.utils.time_utils import now_jst

logger = logging.getLogger(__name__)


class SignalEngine:
    """Main orchestrator - lets ChatGPT freely analyze BTCUSD."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.receiver = MarketDataReceiver(settings)
        self.notifier = TelegramNotifier(settings)
        self.db = SignalDatabase(settings)
        self.tracker = PositionTracker()
        self._restore_open_positions()

    def process_webhook(self, payload: Dict) -> bool:
        """Process a TradingView webhook and check positions."""
        success = self.receiver.process_webhook(payload)

        if success and payload.get("timeframe", "").upper() == "M5":
            high = float(payload.get("high", 0))
            low = float(payload.get("low", 0))
            close = float(payload.get("close", 0))
            if high > 0 and low > 0:
                self._check_positions(high, low, close)

        return success

    def run_analysis(self) -> Optional[Dict]:
        """
        Run AI-driven analysis. ChatGPT freely decides BUY/SELL/NO_TRADE.
        No hardcoded filters - AI sees raw market data and decides.
        """
        # Step 0: Check trading session
        jst_now = now_jst()
        if not self.settings.is_trading_session(jst_now.hour, jst_now.minute):
            session = self.settings.get_active_session(jst_now.hour, jst_now.minute)
            logger.info(f"Outside trading session ({session}) - skipping")
            return None

        # Step 1: Get data
        data = self.receiver.get_all_dataframes()
        if data is None:
            logger.warning("Insufficient data for analysis")
            return None

        current_price_data = self.receiver.get_current_price()
        if current_price_data is None:
            logger.warning("No current price available")
            return None

        current_price = current_price_data.get("bid", 0)
        if current_price <= 0:
            logger.warning("Invalid current price")
            return None

        # Step 2: Compute features (technical indicators)
        featured_data = compute_all_features(data)
        if featured_data is None:
            logger.error("Feature computation failed")
            return None

        # Step 3: Get context for AI
        signals_today = self._count_signals_today()
        recent_results = self._get_recent_results_summary()

        # Step 4: Let ChatGPT freely analyze and decide
        ai_output = analyze_market(
            featured_data=featured_data,
            current_price=current_price,
            settings=self.settings,
            signals_today=signals_today,
            recent_results=recent_results,
        )

        if ai_output is None:
            logger.error("AI analysis failed")
            return None

        decision = ai_output.get("decision", "").upper()

        # NO_TRADE - just log and return
        if decision == "NO_TRADE":
            self.db.save_signal(ai_output)
            logger.info(f"AI decided NO_TRADE: {ai_output.get('reason', 'N/A')}")
            return ai_output

        # Step 5: Light risk filter (only validate numbers make sense)
        spread = current_price_data.get("spread", 0)
        is_valid, rejection_reason = validate_signal(ai_output, self.settings, spread)

        if not is_valid:
            logger.warning(f"Signal rejected by risk filter: {rejection_reason}")
            ai_output["decision"] = "NO_TRADE"
            ai_output["reason"] = f"Risk filter: {rejection_reason}"
            self.db.save_signal(ai_output)
            return ai_output

        # Enrich with computed fields
        ai_output = enrich_signal(ai_output)

        # Step 6: Duplicate check
        price = float(ai_output.get("current_price", 0))
        if self.db.is_duplicate(decision, price, self.settings.signal_cooldown_seconds):
            logger.info("Duplicate signal - skipping notification")
            self.db.save_signal(ai_output, notification_sent=False)
            return ai_output

        # Step 7: Telegram notification
        notification_sent = self.notifier.send_signal(ai_output)

        # Step 8: Save to database
        signal_id = self.db.save_signal(
            ai_output, notification_sent=notification_sent,
        )

        # Step 9: Register position for tracking
        if signal_id:
            self.tracker.open_position(signal_id, ai_output)

        logger.info(
            f"Signal pipeline complete: {decision} "
            f"(notified={notification_sent})"
        )
        return ai_output

    def _count_signals_today(self) -> int:
        """Count BUY/SELL signals sent today."""
        try:
            recent = self.db.get_recent_signals(50)
            today = now_jst().date()
            count = 0
            for s in recent:
                ts = s.get("timestamp", "")
                decision = s.get("decision", "")
                if decision in ("BUY", "SELL") and str(today) in str(ts):
                    count += 1
            return count
        except Exception:
            return 0

    def _get_recent_results_summary(self) -> str:
        """Get a brief summary of recent trade results for AI context."""
        try:
            stats = self.db.get_performance_stats()
            if not stats or stats.get("total_trades", 0) == 0:
                return "まだトレード実績なし"

            win_rate = stats.get("win_rate", 0)
            total = stats.get("total_trades", 0)
            wins = stats.get("wins", 0)
            losses = stats.get("losses", 0)
            return f"勝率{win_rate}%（{wins}勝{losses}敗 / {total}トレード）"
        except Exception:
            return "取得エラー"

    def get_status(self) -> Dict:
        """Get engine status for health checks."""
        jst_now = now_jst()
        return {
            "symbol": self.settings.symbol,
            "data_status": self.receiver.get_status(),
            "trading_session": self.settings.get_active_session(jst_now.hour, jst_now.minute),
            "time_jst": jst_now.isoformat(),
            "signals_today": self._count_signals_today(),
            "recent_signals": len(self.db.get_recent_signals(5)),
        }

    def _check_positions(self, high: float, low: float, close: float):
        """Check open positions against price and send notifications."""
        events = self.tracker.check_price(high, low, close)
        for event in events:
            event_type = event["event_type"]
            signal_id = event["signal_id"]

            self.db.update_trade_event(
                signal_id, event_type,
                event["exit_price"], event["pnl_pips"],
            )

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
