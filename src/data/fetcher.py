"""
Market Data Fetcher - Retrieves OHLCV + Bid/Ask/Spread data for XAUUSD.
Supports MetaTrader5 and a demo/random data provider for testing.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class DataProvider(ABC):
    """Abstract base class for market data providers."""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, count: int) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data.
        Returns DataFrame with columns: time, open, high, low, close, volume
        """
        ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[Dict]:
        """
        Returns dict with keys: bid, ask, spread, time
        """
        ...


class MT5Provider(DataProvider):
    """MetaTrader5 data provider."""

    TIMEFRAME_MAP = {
        "M1": None,   # Will be set after import
        "M5": None,
        "M15": None,
        "M30": None,
        "H1": None,
        "H4": None,
        "D1": None,
    }

    def __init__(self):
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
            self.TIMEFRAME_MAP = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            if not mt5.initialize():
                raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
            logger.info("MT5 initialized successfully")
        except ImportError:
            raise ImportError("MetaTrader5 package not installed. Install with: pip install MetaTrader5")

    def fetch_ohlcv(self, symbol: str, timeframe: str, count: int) -> Optional[pd.DataFrame]:
        tf = self.TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            logger.error(f"Unsupported timeframe: {timeframe}")
            return None

        rates = self._mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            logger.error(f"Failed to fetch {timeframe} data for {symbol}: {self._mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={
            "tick_volume": "volume",
        })
        return df[["time", "open", "high", "low", "close", "volume"]].copy()

    def get_current_price(self, symbol: str) -> Optional[Dict]:
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"Failed to get tick for {symbol}")
            return None
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round(tick.ask - tick.bid, 2),
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
        }


class DemoProvider(DataProvider):
    """Demo/random data provider for testing without MT5."""

    def __init__(self, base_price: float = 3030.0):
        self.base_price = base_price
        self._rng = np.random.default_rng(42)

    def fetch_ohlcv(self, symbol: str, timeframe: str, count: int) -> Optional[pd.DataFrame]:
        tf_minutes = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        minutes = tf_minutes.get(timeframe, 60)

        now = datetime.now(timezone.utc)
        times = pd.date_range(end=now, periods=count, freq=f"{minutes}min")

        price = self.base_price
        data = []
        for t in times:
            change = self._rng.normal(0, 2.0)
            o = price
            h = o + abs(self._rng.normal(0, 3.0))
            l = o - abs(self._rng.normal(0, 3.0))
            c = o + change
            price = c
            vol = int(self._rng.integers(100, 10000))
            data.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": vol})

        return pd.DataFrame(data)

    def get_current_price(self, symbol: str) -> Optional[Dict]:
        spread = round(self._rng.uniform(0.1, 0.5), 2)
        return {
            "bid": self.base_price,
            "ask": round(self.base_price + spread, 2),
            "spread": spread,
            "time": datetime.now(timezone.utc),
        }


class MarketDataFetcher:
    """High-level data fetcher that manages multiple timeframe data."""

    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.data_provider == "mt5":
            self.provider = MT5Provider()
        else:
            self.provider = DemoProvider()
        self._cache: Dict[str, pd.DataFrame] = {}

    def fetch_all_timeframes(self) -> Optional[Dict[str, pd.DataFrame]]:
        """Fetch data for all configured timeframes. Returns None if any fails."""
        result = {}
        for tf in self.settings.timeframes:
            count = self.settings.min_candles.get(tf, 500)
            df = self.provider.fetch_ohlcv(self.settings.symbol, tf, count)
            if df is None or len(df) < 50:
                logger.error(f"Insufficient data for {tf}: got {len(df) if df is not None else 0} candles")
                return None
            result[tf] = df
            logger.info(f"Fetched {len(df)} candles for {tf}")
        self._cache = result
        return result

    def get_current_price(self) -> Optional[Dict]:
        return self.provider.get_current_price(self.settings.symbol)

    def validate_data(self, data: Dict[str, pd.DataFrame]) -> bool:
        """Check for data quality issues."""
        for tf, df in data.items():
            if df.isnull().any().any():
                logger.warning(f"NaN values found in {tf} data")
                return False
            min_required = min(50, self.settings.min_candles.get(tf, 50))
            if len(df) < min_required:
                logger.warning(f"Insufficient {tf} data: {len(df)} < {min_required}")
                return False
        return True
