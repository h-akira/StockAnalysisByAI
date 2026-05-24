"""yfinance wrapper with a daily on-disk cache.

Caches a full daily-price history per ticker as a CSV under
cache/prices/{sec_code}.csv with a 1-day TTL (see init_plan.md §3.6). The cache
is the full series — callers pick the dates they need (typically fiscal
year-ends).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts import paths

PRICE_TTL_SECONDS = 24 * 60 * 60  # 1 day


def price_csv_path(sec_code: str) -> Path:
    return paths.PRICES_DIR / f"{sec_code}.csv"


def _cache_is_fresh(path: Path, ttl_seconds: int = PRICE_TTL_SECONDS) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age < ttl_seconds


def fetch_history(sec_code: str, *, period: str = "max", force_refresh: bool = False) -> pd.DataFrame:
    """Return a DataFrame of daily prices for a TSE ticker.

    Uses yfinance with ``auto_adjust=False`` (matches pre-research step5 so
    that Yahoo's split adjustment is preserved without yfinance's extra
    dividend adjustment). Cached as CSV with a 1-day TTL.

    Returns columns: Open, High, Low, Close, Volume, Dividends, Stock Splits
    (whichever yfinance provides). Index is a tz-naive DatetimeIndex.

    Raises RuntimeError if yfinance returns no data.
    """
    paths.ensure_cache_dirs()
    out_path = price_csv_path(sec_code)
    if not force_refresh and _cache_is_fresh(out_path):
        df = pd.read_csv(out_path, parse_dates=["Date"]).set_index("Date")
        df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
        return df

    import yfinance as yf  # imported lazily so unit tests don't require yfinance

    ticker = f"{sec_code}.T"
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if hist.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    hist.index = hist.index.tz_localize(None).normalize()
    hist.index.name = "Date"
    hist.to_csv(out_path)
    return hist


def closes_at_or_before(history: pd.DataFrame, period_ends: pd.DatetimeIndex) -> pd.Series:
    """For each fiscal year-end, return the closing price on the nearest
    trading day at or before that date. NaN if the cache has no earlier data.
    """
    closes = history["Close"]
    prices: dict[pd.Timestamp, float] = {}
    for pe in period_ends:
        eligible = closes.loc[:pe]
        prices[pe] = float(eligible.iloc[-1]) if not eligible.empty else float("nan")
    return pd.Series(prices, name="StockPrice")
