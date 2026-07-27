"""
scanners/fundamental.py
Scores the C, A, and I criteria from yfinance data.

C — Current quarterly EPS growth (0–25 pts)
    Primary:  yfinance earningsQuarterlyGrowth (trailing quarterly YoY)
    Fallback: 3-month price return as proxy

A — Annual EPS CAGR + ROE (0–20 pts)
    Primary:  yfinance earningsGrowth + returnOnEquity
    Fallback: 12-month return as crude CAGR proxy

I — Institutional ownership quality (0–5 pts)
    Primary:  yfinance heldPercentInstitutions
    Fallback: 3 pts (neutral assumption)

All results are cached per-ticker in data/fund_cache/ (TTL: 24 hrs).
"""

import json
import time
from pathlib import Path

CACHE_DIR  = Path("data/fund_cache")
CACHE_TTL  = 86_400   # 24 hours

# ── Score weights (must sum to 50 for fundamentals) ───────────
C_MAX =  25
A_MAX =  20
I_MAX =   5


def score_fundamentals(ticker: str, refresh: bool = False) -> dict:
    """
    Fetch and score C, A, I criteria for a single ticker.
    Returns dict with C_score, A_score, I_score plus raw fields.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{ticker}.json"

    # ── Cache check ───────────────────────────────────────────
    if not refresh and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            age  = time.time() - data.get("_cached_at", 0)
            if age < CACHE_TTL:
                return data
        except Exception:
            pass

    result = {
        "_cached_at":  time.time(),
        "ticker":      ticker,
        "C_score":     0.0,
        "A_score":     0.0,
        "I_score":     3.0,      # neutral default
        "eps_growth":  None,
        "eps_cagr":    None,
        "roe":         None,
        "inst_pct":    None,
        "price":       None,
        "sector":      None,
        "industry":    None,
        "method":      "unknown",
    }

    try:
        from scanners import _yf_fetch
        info = _yf_fetch.ticker_info(ticker)

        # ── Price / meta ──────────────────────────────────────
        result["price"]    = info.get("currentPrice") or info.get("regularMarketPrice")
        result["sector"]   = info.get("sector",   "Unknown")
        result["industry"] = info.get("industry", "Unknown")

        # ── C: Current Quarterly EPS ──────────────────────────
        eq_growth = info.get("earningsQuarterlyGrowth")
        if eq_growth is not None:
            growth = float(eq_growth)
            result["eps_growth"] = growth
            result["method"]     = "yfinance_quarterly"
        else:
            # Fallback: 3-month price return
            try:
                hist   = _yf_fetch.ticker_history(ticker, period="3mo", auto_adjust=True)
                if len(hist) > 10:
                    growth = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1
                    result["eps_growth"] = growth
                    result["method"]     = "price_proxy_3mo"
                else:
                    growth = 0.0
                    result["method"]     = "insufficient_data"
            except Exception:
                growth = 0.0
                result["method"]     = "error_fallback"

        # Score C: 0 pts if ≤0%, scales to 25 pts at 100%+ growth
        # Thresholds: <0=0, 0-15%=5, 15-25%=12, 25-50%=18, 50-100%=22, >100%=25
        result["C_score"] = _score_eps_growth(growth)

        # ── A: Annual EPS CAGR + ROE ──────────────────────────
        eg      = info.get("earningsGrowth")      # trailing annual
        roe     = info.get("returnOnEquity")

        # Estimate CAGR: use earningsGrowth as annual proxy
        if eg is not None:
            cagr = float(eg)
        else:
            # fallback: 1-yr price return × 0.5
            try:
                hist  = _yf_fetch.ticker_history(ticker, period="1y", auto_adjust=True)
                if len(hist) > 200:
                    cagr = ((hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1) * 0.5
                else:
                    cagr = 0.0
            except Exception:
                cagr = 0.0

        result["eps_cagr"] = cagr
        result["roe"]      = float(roe) if roe is not None else None

        result["A_score"]  = _score_annual(cagr, result["roe"])

        # ── I: Institutional Ownership ────────────────────────
        inst = info.get("heldPercentInstitutions")
        if inst is not None:
            inst = float(inst)
            result["inst_pct"] = inst
            result["I_score"]  = _score_institutional(inst)
        else:
            result["inst_pct"] = None
            result["I_score"]  = 3.0    # neutral when unavailable

    except Exception as e:
        result["_error"] = str(e)
        # Keep defaults (all zeros / neutrals)

    # ── Cache ─────────────────────────────────────────────────
    try:
        cache_file.write_text(json.dumps(result, indent=2))
    except Exception:
        pass

    return result


# ── SCORING FUNCTIONS ─────────────────────────────────────────

def _score_eps_growth(growth: float) -> float:
    """
    Map quarterly EPS growth (as decimal) to 0–25 pts.
    Calibrated from the reverse-engineered model:
      Elite held leaders (CRDO, NVDA) had growth implying C≈22–24 pts
      Watchlist mid-tier implied C≈15–18 pts
      ETF/macro implied C≈10–14 pts
    """
    if growth is None:
        return 0.0
    g = float(growth)
    if g >= 1.00:   return 25.0   # ≥100% growth → full marks
    if g >= 0.75:   return 23.0
    if g >= 0.50:   return 21.0
    if g >= 0.35:   return 19.0
    if g >= 0.25:   return 17.0   # O'Neil's minimum threshold
    if g >= 0.15:   return 13.0
    if g >= 0.05:   return  8.0
    if g >= 0.00:   return  4.0
    if g >= -0.10:  return  2.0
    return 0.0                    # negative growth → 0


def _score_annual(cagr: float, roe: float | None) -> float:
    """
    Map annual EPS CAGR + ROE to 0–20 pts.
    CAGR contributes up to 15 pts; ROE quality adds up to 5 pts.
    """
    if cagr is None:
        cagr = 0.0
    cagr = float(cagr)

    # CAGR sub-score (0–15)
    if cagr >= 0.50:   cagr_pts = 15.0
    elif cagr >= 0.35: cagr_pts = 13.0
    elif cagr >= 0.25: cagr_pts = 11.0   # O'Neil's threshold
    elif cagr >= 0.15: cagr_pts =  8.0
    elif cagr >= 0.05: cagr_pts =  5.0
    elif cagr >= 0.00: cagr_pts =  2.0
    else:              cagr_pts =  0.0

    # ROE sub-score (0–5)
    if roe is None:
        roe_pts = 2.5   # neutral
    else:
        r = float(roe)
        if r >= 0.40:   roe_pts = 5.0
        elif r >= 0.25: roe_pts = 4.0
        elif r >= 0.17: roe_pts = 3.0   # O'Neil's threshold
        elif r >= 0.10: roe_pts = 2.0
        elif r >= 0.00: roe_pts = 1.0
        else:           roe_pts = 0.0

    return round(min(A_MAX, cagr_pts + roe_pts), 2)


def _score_institutional(inst_pct: float) -> float:
    """
    Map institutional ownership % to 0–5 pts.
    Sweet spot: 40–85%. Too low = no sponsorship. Too high = maxed out.
    O'Neil prefers below 85% to avoid stocks where all big money is in.
    """
    if inst_pct is None:
        return 3.0
    i = float(inst_pct)
    if 0.50 <= i <= 0.80:  return 5.0   # ideal zone
    if 0.40 <= i <  0.50:  return 4.0
    if 0.80 <  i <= 0.90:  return 3.0   # slightly crowded
    if 0.30 <= i <  0.40:  return 2.5
    if 0.90 <  i <= 1.00:  return 2.0   # over-owned (big funds maxed)
    if 0.15 <= i <  0.30:  return 1.5
    return 1.0
