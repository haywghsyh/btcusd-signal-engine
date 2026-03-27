"""
BTCUSD Signal Engine - Main entry point.
Runs a Flask webhook server with scheduled AI analysis.
ChatGPT freely analyzes market data and decides entries (scalping style).
"""
import logging
import os
import threading
import time

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify

from src.config.settings import Settings
from src.data.historical import load_historical_data
from src.engine import SignalEngine
from src.utils.logger import setup_logger
from src.utils.time_utils import now_jst

# Initialize
settings = Settings()
setup_logger(settings)
logger = logging.getLogger(__name__)

engine = SignalEngine(settings)

# Analysis interval in seconds (default: 30 minutes)
ANALYSIS_INTERVAL = int(os.getenv("ANALYSIS_INTERVAL_SECONDS", "300"))


def warmup_historical_data():
    """Load historical data on startup."""
    logger.info("Loading historical BTCUSD data...")
    try:
        loaded = load_historical_data(engine.receiver, settings.timeframes)
        if loaded:
            status = engine.receiver.get_status()
            logger.info(f"Buffer status after warmup: {status}")
        else:
            logger.warning("Historical data warmup returned no data")
    except Exception as e:
        logger.error(f"Historical data warmup failed: {e}", exc_info=True)


def retry_missing_historical_data():
    """Retry loading historical data for timeframes with insufficient candles."""
    status = engine.receiver.get_status()
    missing_tfs = [
        tf for tf in settings.timeframes
        if status.get(tf, 0) < settings.min_candles.get(tf, 50)
    ]
    if not missing_tfs:
        return

    logger.info(f"Retrying historical data for: {missing_tfs}")
    try:
        loaded = load_historical_data(engine.receiver, missing_tfs)
        if loaded:
            new_status = engine.receiver.get_status()
            logger.info(f"Buffer status after retry: {new_status}")
    except Exception as e:
        logger.warning(f"Historical data retry failed: {e}")


def scheduled_analysis():
    """
    Periodically run AI analysis.
    ChatGPT decides freely whether to enter or not.
    Target: ~3 signals per day during trading sessions.
    """
    logger.info(f"Scheduled analysis started (interval: {ANALYSIS_INTERVAL}s)")
    while True:
        try:
            time.sleep(ANALYSIS_INTERVAL)

            # Retry loading historical data for any timeframes still lacking data
            retry_missing_historical_data()

            jst_now = now_jst()
            session = settings.get_active_session(jst_now.hour, jst_now.minute)

            if session == "CLOSED":
                logger.debug(f"Market closed at {jst_now.strftime('%H:%M')} JST - skipping")
                continue

            buffer_status = engine.receiver.get_status()
            price_available = engine.receiver.get_current_price() is not None
            logger.info(
                f"Running scheduled analysis ({session} session, "
                f"{jst_now.strftime('%H:%M')} JST) "
                f"buffers={buffer_status} price={'yes' if price_available else 'NO'}"
            )
            result = engine.run_analysis()

            if result:
                decision = result.get("decision", "NO_TRADE")
                reason = result.get("reason", "N/A")
                logger.info(f"Scheduled analysis result: {decision} - {reason}")
            else:
                logger.info("Scheduled analysis: no result (insufficient data)")

        except Exception as e:
            logger.error(f"Scheduled analysis error: {e}", exc_info=True)

app = Flask(__name__)

# Run warmup in background so gunicorn can bind the port immediately
warmup_thread = threading.Thread(target=warmup_historical_data, daemon=True)
warmup_thread.start()


@app.route("/webhook/tradingview", methods=["POST"])
def tradingview_webhook():
    """
    Receive TradingView alert webhook (for price data ingestion).
    Analysis is handled by the scheduler, not triggered by webhooks.
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if payload is None:
            return jsonify({"error": "Invalid JSON"}), 400

        logger.info(f"Webhook received: {payload.get('timeframe', '?')} candle")

        success = engine.process_webhook(payload)
        if not success:
            return jsonify({"status": "rejected", "reason": "Invalid payload"}), 400

        return jsonify({"status": "ok", "message": "Data ingested"}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/batch", methods=["POST"])
def batch_webhook():
    """Receive multiple candles at once (for initial data loading)."""
    try:
        payload = request.get_json(force=True, silent=True)
        if payload is None:
            return jsonify({"error": "Invalid JSON"}), 400

        timeframe = payload.get("timeframe", "").upper()
        candles = payload.get("candles", [])

        if not timeframe or not candles:
            return jsonify({"error": "Missing timeframe or candles"}), 400

        loaded = engine.receiver.add_batch_candles(timeframe, candles)

        return jsonify({"status": "ok", "loaded": loaded, "timeframe": timeframe}), 200

    except Exception as e:
        logger.error(f"Batch webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/status", methods=["GET"])
def status():
    """Health check and engine status."""
    return jsonify(engine.get_status()), 200


@app.route("/signals/recent", methods=["GET"])
def recent_signals():
    """Get recent signals."""
    limit = request.args.get("limit", 10, type=int)
    signals = engine.db.get_recent_signals(limit)
    return jsonify({"signals": signals}), 200


@app.route("/analyze", methods=["POST"])
def manual_analyze():
    """Manually trigger AI analysis."""
    result = engine.run_analysis()
    if result is None:
        return jsonify({"status": "no_data", "message": "Insufficient data for analysis"}), 200
    return jsonify({"status": "ok", "signal": result}), 200


@app.route("/positions", methods=["GET"])
def open_positions():
    """Get currently open positions."""
    positions = engine.tracker.get_open_positions()
    return jsonify({"open_positions": positions, "count": len(positions)}), 200


@app.route("/x/sentiment", methods=["GET"])
def x_sentiment():
    """Get current X (Twitter) BTC sentiment."""
    if engine.x_scraper is None:
        return jsonify({"status": "disabled", "message": "X scraping is disabled"}), 200

    force = request.args.get("force", "false").lower() == "true"
    summary = engine.x_scraper.get_sentiment(force_refresh=force)
    return jsonify({
        "status": "ok",
        "sentiment": summary.sentiment_label,
        "score": summary.avg_sentiment_score,
        "total_posts": summary.total_posts,
        "bullish": summary.bullish_count,
        "bearish": summary.bearish_count,
        "neutral": summary.neutral_count,
        "whale_alerts": summary.whale_alerts[:5],
        "top_posts": [
            {"user": p.username, "text": p.text[:200], "engagement": p.engagement}
            for p in summary.top_posts[:5]
        ],
        "scraper_status": engine.x_scraper.get_status(),
    }), 200


@app.route("/performance", methods=["GET"])
def performance():
    """Get trading performance stats."""
    stats = engine.get_performance()
    return jsonify(stats), 200


@app.route("/performance/telegram", methods=["POST"])
def send_performance_telegram():
    """Send performance dashboard to Telegram."""
    stats = engine.get_performance()
    if not stats or stats.get("total_trades", 0) == 0:
        return jsonify({"status": "no_data", "message": "No closed trades yet"}), 200
    sent = engine.notifier.send_dashboard(stats)
    return jsonify({"status": "sent" if sent else "failed"}), 200


# Start scheduled analysis in background thread
analysis_thread = threading.Thread(target=scheduled_analysis, daemon=True)
analysis_thread.start()


if __name__ == "__main__":
    logger.info("Starting BTCUSD Signal Engine (AI Free Analysis Mode)...")
    logger.info(f"Symbol: {settings.symbol}")
    logger.info(f"AI Model: {settings.ai_model}")
    logger.info(f"Analysis interval: {ANALYSIS_INTERVAL}s")

    engine.notifier.send_startup_message()

    app.run(
        host=settings.webhook_host,
        port=settings.webhook_port,
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
