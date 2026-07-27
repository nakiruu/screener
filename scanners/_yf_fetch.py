"""
scanners/_yf_fetch.py
Thread-safe yfinance wrappers with rate limiting and retry on 401 errors.

Yahoo Finance aggressively rate-limits free API access, returning HTTP 401
("Invalid Crumb") when hit too fast. This module adds:
  - A global rate limiter (MIN_INTERVAL between any two yfinance calls)
  - Exponential-backoff retries on 401 / crumb / rate-limit errors
"""

import threading
import time

import yfinance as yf

MIN_INTERVAL = 0.12          # seconds between yfinance calls (global)
MAX_RETRIES  = 3
BASE_DELAY   = 1.5           # initial retry delay (seconds)

_lock       = threading.Lock()
_last_call  = 0.0


def _throttle():
    """Block until MIN_INTERVAL has elapsed since the last yfinance call."""
    global _last_call
    with _lock:
        now   = time.monotonic()
        wait  = MIN_INTERVAL - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _is_retryable(exc: Exception) -> bool:
    """Check if the exception is a transient Yahoo Finance error worth retrying."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("401", "unauthorized", "crumb", "rate"))


def download(ticker: str, **kwargs) -> "pd.DataFrame | None":
    """yf.download() with rate limiting and retry."""
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            df = yf.download(ticker, **kwargs)
            if df is not None and len(df) > 0:
                return df
            if attempt < MAX_RETRIES:
                time.sleep(BASE_DELAY * (2 ** attempt))
                continue
            return df
        except Exception as e:
            if attempt < MAX_RETRIES and _is_retryable(e):
                time.sleep(BASE_DELAY * (2 ** attempt))
                continue
            raise
    return None


def ticker_info(ticker: str) -> dict:
    """Fetch yf.Ticker(ticker).info with rate limiting and retry."""
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            info = yf.Ticker(ticker).info
            if info:
                return info
            if attempt < MAX_RETRIES:
                time.sleep(BASE_DELAY * (2 ** attempt))
                continue
            return info or {}
        except Exception as e:
            if attempt < MAX_RETRIES and _is_retryable(e):
                time.sleep(BASE_DELAY * (2 ** attempt))
                continue
            raise
    return {}


def ticker_history(ticker: str, **kwargs) -> "pd.DataFrame":
    """Fetch yf.Ticker(ticker).history() with rate limiting and retry."""
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            hist = yf.Ticker(ticker).history(**kwargs)
            if hist is not None and len(hist) > 0:
                return hist
            if attempt < MAX_RETRIES:
                time.sleep(BASE_DELAY * (2 ** attempt))
                continue
            return hist
        except Exception as e:
            if attempt < MAX_RETRIES and _is_retryable(e):
                time.sleep(BASE_DELAY * (2 ** attempt))
                continue
            raise
    import pandas as pd
    return pd.DataFrame()
