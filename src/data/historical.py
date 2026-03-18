"""
Historical Data Loader - Fetches past XAUUSD OHLCV data on startup.
Uses yfinance (Gold Futures GC=F) to warm up candle buffers so signals
can be generated immediately without waiting hours for data accumulation.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """Fetches historical XAUUSD data via yfinance on startup."""

    # yfinance ticker for Gold Futures (closely tracks XAUUSD)
    TICKER = "GC=F"

    # How much history to fetch per timeframe
    FETCH_CONFIG = {
        "H4": {"yf_interval": "1h", "yf_period": "60d", "agg_bars": 4},
        "H1": {"yf_interval": "1h", "yf_period": "60d", "agg_bars": 1},
        "M15": {"yf_interval": "15m", "yf_period": "60d", "agg_bars": 1},
        "M5": {"yf_interval": "5m", "yf_period": "60d", "agg_bars": 1},
    }

    def fetch_all(self, timeframes: List[str]) -> Dict[str, List[Dict]]:
        """
        Fetch historical candles for given timeframes.
        Returns dict of timeframe -> list of candle dicts.
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
            return {}

        results = {}
        for tf in timeframes:
            config = self.FETCH_CONFIG.get(tf)
            if not config:
                logger.warning(f"No historical config for {tf}, skipping")
                continue

            try:
                candles = self._fetch_timeframe(yf, tf, config)
                if candles:
                    results[tf] = candles
                    logger.info(f"Historical {tf}: {len(candles)} candles fetched")
                else:
                    logger.warning(f"Historical {tf}: no data returned")
            except Exception as e:
                logger.error(f"Historical {tf} fetch failed: {e}")

        return results

    def _fetch_timeframe(self, yf, timeframe: str, config: dict) -> Optional[List[Dict]]:
        """Fetch and process data for a single timeframe."""
        ticker = yf.Ticker(self.TICKER)
        df = ticker.history(
            period=config["yf_period"],
            interval=config["yf_interval"],
        )

        if df is None or df.empty:
            return None

        # Standardize columns
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = df.dropna()

        if df.empty:
            return None

        # Aggregate if needed (e.g., 1h -> H4)
        agg_bars = config["agg_bars"]
        if agg_bars > 1:
            df = self._aggregate(df, agg_bars)

        # Convert to list of candle dicts
        candles = []
        for idx, row in df.iterrows():
            ts = idx
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            candles.append({
                "time": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })

        return candles

    @staticmethod
    def _aggregate(df: pd.DataFrame, n_bars: int) -> pd.DataFrame:
        """Aggregate rows into larger timeframe candles."""
        # Trim so we have clean groups
        trim = len(df) % n_bars
        if trim > 0:
            df = df.iloc[trim:]

        groups = []
        for i in range(0, len(df), n_bars):
            chunk = df.iloc[i:i + n_bars]
            if len(chunk) < n_bars:
                continue
            groups.append({
                "time": chunk.index[0],
                "open": chunk["open"].iloc[0],
                "high": chunk["high"].max(),
                "low": chunk["low"].min(),
                "close": chunk["close"].iloc[-1],
                "volume": chunk["volume"].sum(),
            })

        result = pd.DataFrame(groups)
        if not result.empty:
            result = result.set_index("time")
        return result


def load_historical_data(receiver, timeframes: List[str]) -> Dict[str, int]:
    """
    Convenience function: fetch historical data and load into receiver buffers.
    Returns dict of timeframe -> count loaded.
    """
    loader = HistoricalDataLoader()
    all_data = loader.fetch_all(timeframes)

    loaded = {}
    for tf, candles in all_data.items():
        count = receiver.load_initial_data(tf, candles)
        loaded[tf] = count

    if loaded:
        logger.info(f"Historical data loaded: {loaded}")
    else:
        logger.warning("No historical data could be loaded")

    return loaded
