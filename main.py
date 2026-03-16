"""
XAUUSD Signal Engine - Main entry point.
Runs a Flask webhook server that receives TradingView alerts
and triggers the signal analysis pipeline.
"""
import logging
import os

from flask import Flask, request, jsonify

from src.config.settings import Settings
from src.engine import SignalEngine
from src.utils.logger import setup_logger

# Initialize
settings = Settings()
setup_logger(settings)
logger = logging.getLogger(__name__)

engine = SignalEngine(settings)

app = Flask(__name__)


@app.route("/webhook/tradingview", methods=["POST"])
def tradingview_webhook():
    """
    Receive TradingView alert webhook.
    Expected JSON payload:
    {
        "symbol": "XAUUSD",
        "timestamp": "2025-01-01T00:00:00Z",
        "open": 3030.0,
        "high": 3035.0,
        "low": 3028.0,
        "close": 3033.0,
        "volume": 1234,
        "timeframe": "M5"
    }
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if payload is None:
            return jsonify({"error": "Invalid JSON"}), 400

        logger.info(f"Webhook received: {payload.get('timeframe', '?')} candle")

        # Process the candle data
        success = engine.process_webhook(payload)
        if not success:
            return jsonify({"status": "rejected", "reason": "Invalid payload"}), 400

        # Run analysis after receiving data
        result = engine.run_analysis()

        if result is None:
            return jsonify({"status": "ok", "signal": "insufficient_data"}), 200

        decision = result.get("decision", "NO_TRADE")
        response = {
            "status": "ok",
            "signal": decision,
        }
        if decision in ("BUY", "SELL"):
            response.update({
                "entry": result.get("current_price"),
                "sl": result.get("sl"),
                "tp1": result.get("tp1"),
                "tp2": result.get("tp2"),
                "tp3": result.get("tp3"),
                "confidence": result.get("confidence"),
            })

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/batch", methods=["POST"])
def batch_webhook():
    """
    Receive multiple candles at once (for initial data loading).
    Expected JSON:
    {
        "timeframe": "H4",
        "candles": [
            {"timestamp": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...},
            ...
        ]
    }
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if payload is None:
            return jsonify({"error": "Invalid JSON"}), 400

        timeframe = payload.get("timeframe", "").upper()
        candles = payload.get("candles", [])

        if not timeframe or not candles:
            return jsonify({"error": "Missing timeframe or candles"}), 400

        from datetime import datetime, timezone
        loaded = 0
        for c in candles:
            ts_raw = c.get("timestamp")
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            elif isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts = datetime.now(timezone.utc)

            candle = {
                "time": ts,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c.get("volume", 0)),
            }
            engine.receiver._buffers[timeframe].add(candle)
            loaded += 1

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
    """Manually trigger signal analysis."""
    result = engine.run_analysis()
    if result is None:
        return jsonify({"status": "no_data", "message": "Insufficient data for analysis"}), 200
    return jsonify({"status": "ok", "signal": result}), 200


if __name__ == "__main__":
    logger.info("Starting XAUUSD Signal Engine...")
    logger.info(f"Symbol: {settings.symbol}")
    logger.info(f"AI Model: {settings.ai_model}")
    logger.info(f"Webhook: http://{settings.webhook_host}:{settings.webhook_port}/webhook/tradingview")

    # Send startup notification
    engine.notifier.send_startup_message()

    app.run(
        host=settings.webhook_host,
        port=settings.webhook_port,
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
