"""
scanners/market_gate.py
Scores the M criterion (market direction gate).

M — Market direction (0–5 pts)
    Confirmed uptrend  → 4–5 pts (gate open, longs permitted)
    Under pressure     → 2–3 pts (caution, reduce size)
    Downtrend          → 0–1 pts (gate closed, avoid new longs)

Distribution day methodology (O'Neil):
  A distribution day = index down > 0.2% on volume > prior day.
  ≤4 dist. days in 25 sessions → confirmed uptrend
  5–7 dist. days               → under pressure
  ≥8 dist. days / price below 50-day MA → downtrend / correction

Uses XLK (tech sector ETF) as primary gauge with QQQ as secondary.
"""

import json
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

CACHE_FILE = Path("data/market_gate_cache.json")
CACHE_TTL  = 3_600    # 1 hour (market conditions change intraday)


def score_market(refresh: bool = False) -> dict:
    """
    Compute M criterion score for current market conditions.
    Returns dict with M_score, gate_open, dist_days, trend_20, etc.
    """
    CACHE_FILE.parent.mkdir(exist_ok=True)

    if not refresh and CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            age  = time.time() - data.get("_cached_at", 0)
            if age < CACHE_TTL:
                return data
        except Exception:
            pass

    result = {
        "_cached_at":  time.time(),
        "M_score":     4.0,
        "gate_open":   True,
        "dist_days":   0,
        "trend_20":    0.0,
        "trend_50":    0.0,
        "above_50ma":  True,
        "above_200ma": True,
        "market_note": "",
    }

    try:
        import yfinance as yf
        import numpy as np

        # ── Fetch XLK (primary) + QQQ (secondary) ─────────────
        xlk = yf.download("XLK", period="6mo",
                          auto_adjust=True, progress=False, threads=False)
        qqq = yf.download("QQQ", period="6mo",
                          auto_adjust=True, progress=False, threads=False)

        # Flatten multi-index if present
        for df in [xlk, qqq]:
            try:
                df.columns = df.columns.droplevel(1)
            except Exception:
                pass

        if xlk is None or len(xlk) < 30:
            # If XLK fails, try QQQ
            xlk = qqq

        if xlk is None or len(xlk) < 30:
            result["market_note"] = "insufficient_data"
            return result

        closes  = xlk["Close"].values.astype(float)
        volumes = xlk["Volume"].values.astype(float) if "Volume" in xlk.columns else None

        # ── Distribution days (last 25 sessions) ─────────────
        n = len(closes)
        dist_days = 0
        window    = min(25, n - 1)
        returns   = (closes[1:] / closes[:-1]) - 1

        for i in range(max(0, len(returns) - window), len(returns)):
            r = returns[i]
            if r < -0.002:   # down > 0.2%
                if volumes is not None and i > 0:
                    # Volume confirmation: today's vol > prior session
                    if volumes[i + 1] > volumes[i]:
                        dist_days += 1
                else:
                    # No volume data: count any day down > 0.3%
                    if r < -0.003:
                        dist_days += 1

        # ── Price trend ───────────────────────────────────────
        trend_20 = (closes[-1] / closes[-21] - 1) if n >= 21 else 0.0
        trend_50 = (closes[-1] / closes[-51] - 1) if n >= 51 else 0.0

        # 50-day and 200-day MA
        ma50  = closes[-50:].mean()  if n >= 50  else closes.mean()
        ma200 = closes[-200:].mean() if n >= 200 else closes.mean()

        above_50ma  = float(closes[-1]) > float(ma50)
        above_200ma = float(closes[-1]) > float(ma200)

        result["dist_days"]   = int(dist_days)
        result["trend_20"]    = float(trend_20)
        result["trend_50"]    = float(trend_50)
        result["above_50ma"]  = bool(above_50ma)
        result["above_200ma"] = bool(above_200ma)

        # ── M score ───────────────────────────────────────────
        m_score, gate_open, note = _score_M(
            dist_days, trend_20, above_50ma, above_200ma
        )
        result["M_score"]     = m_score
        result["gate_open"]   = gate_open
        result["market_note"] = note

    except Exception as e:
        result["_error"]      = str(e)
        result["market_note"] = f"error: {e}"

    # ── Cache ─────────────────────────────────────────────────
    try:
        CACHE_FILE.write_text(json.dumps(result, indent=2))
    except Exception:
        pass

    return result


def _score_M(dist_days: int, trend_20: float,
             above_50ma: bool, above_200ma: bool) -> tuple[float, bool, str]:
    """
    Map market conditions to M score (0–5 pts), gate status, and label.
    """
    # ── Confirmed uptrend ──────────────────────────────────────
    if (dist_days <= 4 and trend_20 > 0.01
            and above_50ma and above_200ma):
        return 5.0, True, "Confirmed uptrend"

    if dist_days <= 4 and trend_20 > 0 and above_50ma:
        return 4.0, True, "Confirmed uptrend (mild)"

    # ── Under pressure ────────────────────────────────────────
    if dist_days <= 7 and above_50ma:
        return 3.0, False, "Market under pressure"

    if dist_days <= 7 and not above_50ma and above_200ma:
        return 2.0, False, "Under pressure / below 50MA"

    # ── Downtrend / correction ────────────────────────────────
    if not above_50ma and not above_200ma:
        return 0.0, False, "Downtrend — avoid new longs"

    if dist_days >= 8:
        return 1.0, False, "Distribution phase"

    # Default
    return 3.0, False, "Uncertain — caution"
