"""
live/market_hours.py
NYSE market hours gate — pure datetime logic, no network.
"""

from __future__ import annotations
from datetime import datetime, time, timedelta

try:
    import zoneinfo
    _ET = zoneinfo.ZoneInfo("America/New_York")
    def _now_et() -> datetime:
        return datetime.now(_ET)
except Exception:
    # Python < 3.9 fallback: crude UTC offset (EST = -5, EDT = -4)
    import time as _time
    def _now_et() -> datetime:   # type: ignore[misc]
        offset = -4 if _time.daylight and _time.localtime().tm_isdst else -5
        return datetime.utcnow() + timedelta(hours=offset)

NYSE_OPEN  = time(9, 30)
NYSE_CLOSE = time(16, 0)


def market_status() -> dict:
    """
    Returns status dict:
      open     bool
      status   'PRE_MARKET' | 'OPEN' | 'AFTER_HOURS' | 'CLOSED'
      now_et   datetime (ET)
      label    human-readable string
    """
    now = _now_et()
    wd  = now.weekday()   # 0=Mon … 6=Sun
    t   = now.time().replace(second=0, microsecond=0)

    if wd >= 5:
        return {"open": False, "status": "CLOSED",
                "now_et": now, "label": "Weekend — market closed"}

    if t < NYSE_OPEN:
        mins = int((datetime.combine(now.date(), NYSE_OPEN) -
                    datetime.combine(now.date(), t)).total_seconds() / 60)
        return {"open": False, "status": "PRE_MARKET",
                "now_et": now, "label": f"Pre-market — opens in {mins}m"}

    if t >= NYSE_CLOSE:
        return {"open": False, "status": "AFTER_HOURS",
                "now_et": now, "label": "After-hours"}

    mins_left = int((datetime.combine(now.date(), NYSE_CLOSE) -
                     datetime.combine(now.date(), t)).total_seconds() / 60)
    return {"open": True, "status": "OPEN",
            "now_et": now, "label": f"Market OPEN — {mins_left}m remaining"}


def is_market_open() -> bool:
    return market_status()["open"]
