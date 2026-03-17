"""
Market Data Receiver - Stores OHLCV candle data received from TradingView webhooks.
Maintains in-memory candle buffers per timeframe.
"""
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class CandleBuffer:
    """Thread-safe candle buffer for a single timeframe."""

    def __init__(self, max_candles: int = 1500):
        self.max_candles = max_candles
        self._candles: List[Dict] = []
        self._lock = threading.Lock()

    def add(self, candle: Dict) -> None:
        with self._lock:
            # Check for duplicate timestamp - update if exists
            ts = candle.get("time")
            for i, c in enumerate(self._candles):
                if c.get("time") == ts:
                    self._candles[i] = candle
                    return
            self._candles.append(candle)
            # Trim to max
            if len(self._candles) > self.max_candles:
                self._candles = self._candles[-self.max_candles:]

    def to_dataframe(self) -> Optional[pd.DataFrame]:
        with self._lock:
            if not self._candles:
                return None
            df = pd.DataFrame(self._candles)
            df = df.sort_values("time").reset_index(drop=True)
            return df

    def count(self) -> int:
        with self._lock:
            return len(self._candles)


class MarketDataReceiver:
    """Manages candle buffers for all timeframes. Receives data from TradingView webhooks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._buffers: Dict[str, CandleBuffer] = {}
        for tf in settings.timeframes:
            max_c = settings.min_candles.get(tf, 1500)
            self._buffers[tf] = CandleBuffer(max_candles=max_c)
        self._current_price: Optional[Dict] = None
        self._lock = threading.Lock()

    def process_webhook(self, payload: Dict) -> bool:
        """
        Process a TradingView webhook payload.
        Expected keys: symbol, timestamp, open, high, low, close, volume, timeframe
        Returns True if processed successfully.
        """
        try:
            symbol = payload.get("symbol", "").upper()
            if symbol != self.settings.symbol:
                logger.warning(f"Ignoring symbol: {symbol}")
                return False

            raw_tf = payload.get("timeframe", "")
            # Map TradingView interval values to internal timeframe names
            tf_map = {
                "5": "M5", "15": "M15", "60": "H1", "240": "H4",
                "M5": "M5", "M15": "M15", "H1": "H1", "H4": "H4",
            }
            timeframe = tf_map.get(str(raw_tf).upper(), str(raw_tf).upper())
            if timeframe not in self._buffers:
                logger.warning(f"Ignoring timeframe: {timeframe}")
                return False

            ts_raw = payload.get("timestamp")
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            elif isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts = datetime.now(timezone.utc)

            candle = {
                "time": ts,
                "open": float(payload["open"]),
                "high": float(payload["high"]),
                "low": float(payload["low"]),
                "close": float(payload["close"]),
                "volume": float(payload.get("volume", 0)),
            }

            self._buffers[timeframe].add(candle)

            # Auto-aggregate M5 candles into higher timeframes
            if timeframe == "M5":
                self._aggregate_higher_timeframes()

            # Update current price from latest close
            with self._lock:
                self._current_price = {
                    "bid": candle["close"],
                    "ask": candle["close"] + 0.3,  # estimated spread
                    "spread": 0.3,
                    "time": ts,
                }

            logger.info(
                f"Received {timeframe} candle: O={candle['open']:.1f} "
                f"H={candle['high']:.1f} L={candle['low']:.1f} C={candle['close']:.1f}"
            )
            return True

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Webhook payload error: {e}")
            return False

    def _aggregate_higher_timeframes(self) -> None:
        """Aggregate M5 candles into M15, H1, H4 automatically."""
        m5_df = self._buffers["M5"].to_dataframe()
        if m5_df is None or len(m5_df) < 3:
            return

        agg_map = {"M15": 3, "H1": 12, "H4": 48}  # number of M5 candles per period

        for tf, n_bars in agg_map.items():
            if tf not in self._buffers:
                continue
            if len(m5_df) < n_bars:
                continue

            # Group M5 candles into chunks of n_bars from the end
            # Align to clean boundaries
            total = len(m5_df)
            # Work backwards from the latest candle
            start = total % n_bars
            for i in range(start, total, n_bars):
                chunk = m5_df.iloc[i:i + n_bars]
                if len(chunk) < n_bars:
                    continue
                agg_candle = {
                    "time": chunk.iloc[0]["time"],
                    "open": chunk.iloc[0]["open"],
                    "high": chunk["high"].max(),
                    "low": chunk["low"].min(),
                    "close": chunk.iloc[-1]["close"],
                    "volume": chunk["volume"].sum(),
                }
                self._buffers[tf].add(agg_candle)

    def get_all_dataframes(self) -> Optional[Dict[str, pd.DataFrame]]:
        """Get DataFrames for all timeframes. Returns None if any has insufficient data."""
        result = {}
        for tf in self.settings.timeframes:
            df = self._buffers[tf].to_dataframe()
            min_required = 50  # minimum for analysis
            if df is None or len(df) < min_required:
                logger.warning(
                    f"{tf}: insufficient data ({0 if df is None else len(df)}/{min_required})"
                )
                return None
            result[tf] = df
        return result

    def get_current_price(self) -> Optional[Dict]:
        with self._lock:
            return self._current_price

    def get_status(self) -> Dict:
        """Return buffer sizes per timeframe."""
        return {tf: buf.count() for tf, buf in self._buffers.items()}

    def load_initial_data(self, timeframe: str, candles: List[Dict]) -> int:
        """Bulk load historical candles (e.g. from CSV or API). Returns count loaded."""
        if timeframe not in self._buffers:
            return 0
        count = 0
        for c in candles:
            self._buffers[timeframe].add(c)
            count += 1
        logger.info(f"Loaded {count} historical candles for {timeframe}")
        return count
