"""
live/price_feed.py
Fast live price fetcher using yf.Ticker.fast_info — no auth required.
Falls back to yf.download 1m bar if fast_info is unavailable.
"""

from __future__ import annotations
import time
import warnings
warnings.filterwarnings("ignore")


def fetch_live_prices(tickers: list[str],
                      delay: float = 0.05) -> dict[str, float | None]:
    """
    Fetch latest price for each ticker. Never raises.
    delay: seconds between requests to avoid rate-limiting.
    """
    result: dict[str, float | None] = {}
    for t in tickers:
        result[t] = fetch_single_price(t)
        if delay:
            time.sleep(delay)
    return result


def fetch_single_price(ticker: str) -> float | None:
    """
    Try fast_info first (no auth), then fall back to 1m download.
    Returns None on any failure.
    """
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass

    # Fallback: last close from 1-day 1m history
    try:
        import yfinance as yf
        hist = yf.download(ticker, period="1d", interval="1m",
                           progress=False, threads=False, auto_adjust=True)
        if hist is not None and len(hist) > 0:
            try:
                hist.columns = hist.columns.droplevel(1)
            except Exception:
                pass
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass

    return None
