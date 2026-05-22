"""
scanners/technical.py
Scores the N, S, and L criteria from price/volume data.

N — New catalyst / near ATH / breakout quality (0–15 pts)
    = f(breakout_pct, dist_from_52wk_hi, base_tightness)

S — Supply/demand / volume confirmation (0–15 pts)
    = f(breakout_pct, up_vol/dn_vol ratio, volume_surge)

    N+S combined are proxied by Breakout% (from regression):
      N+S ≈ (breakout_pct / BREAKOUT_NORM) × NS_COMBINED_MAX

L — Leader / Laggard: relative strength rank (0–15 pts)
    = f(12-1 month RS percentile within QQQ universe)

Results cached in data/tech_cache/ (TTL: 4 hrs for prices).
"""

import json
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

CACHE_DIR        = Path("data/tech_cache")
CACHE_TTL        = 14_400    # 4 hours

# Calibrated from regression on the 38-instrument audit dataset
BREAKOUT_NORM    = 74.0      # normalizer (max observed breakout%)
NS_COMBINED_MAX  = 30.0      # max combined N+S pts
N_MAX            = 15.0
S_MAX            = 15.0
L_MAX            = 15.0

# RS calculation universe cache (shared across all tickers in a run)
_RS_UNIVERSE_CACHE: dict = {}


def score_technical(ticker: str, period: str = "1y",
                    refresh: bool = False) -> dict:
    """
    Compute N, S, L scores for one ticker.
    Returns dict with scores and supporting metrics.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{ticker}_{period}.json"

    if not refresh and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            age  = time.time() - data.get("_cached_at", 0)
            if age < CACHE_TTL:
                return data
        except Exception:
            pass

    result = {
        "_cached_at":   time.time(),
        "ticker":       ticker,
        "N_score":      0.0,
        "S_score":      0.0,
        "L_score":      0.0,
        "breakout_pct": None,
        "base_pivot":   None,
        "dist_from_hi": None,
        "rs_pct":       50.0,   # default: 50th percentile
        "ud_ratio":     None,
        "vol_surge":    None,
        "swing":        None,   # populated by swing_trade engine
    }

    try:
        import yfinance as yf

        # ── Price + volume history ────────────────────────────
        hist = yf.download(ticker, period=period,
                           auto_adjust=True, progress=False, threads=False)
        if hist is None or len(hist) < 60:
            result["_error"] = "insufficient_price_data"
            return result

        # Flatten MultiIndex columns if present
        if isinstance(hist.columns, type(None.__class__)):
            pass
        try:
            hist.columns = hist.columns.droplevel(1)
        except Exception:
            pass

        closes  = hist["Close"].values.astype(float)
        volumes = hist["Volume"].values.astype(float) if "Volume" in hist.columns else None
        highs   = hist["High"].values.astype(float)   if "High"   in hist.columns else closes
        lows    = hist["Low"].values.astype(float)    if "Low"    in hist.columns else closes

        # Store raw arrays for swing engine (not written to JSON cache)
        result["_closes"]  = closes
        result["_highs"]   = highs
        result["_lows"]    = lows
        result["_volumes"] = volumes

        current_price = float(closes[-1])

        # ── Base pivot detection ──────────────────────────────
        pivot, bk_pct = _detect_breakout(closes, highs, lows)
        result["base_pivot"]   = float(pivot) if pivot else None
        result["breakout_pct"] = float(bk_pct) if bk_pct is not None else None

        # ── 52-week high distance ─────────────────────────────
        hi52 = float(np.max(closes[-252:])) if len(closes) >= 252 else float(np.max(closes))
        dist = (hi52 - current_price) / hi52
        result["dist_from_hi"] = float(dist)

        # ── N score ───────────────────────────────────────────
        result["N_score"] = _score_N(bk_pct, dist)

        # ── S score (volume confirmation) ─────────────────────
        ud_ratio, vol_surge = None, None
        if volumes is not None and len(volumes) >= 20:
            r60   = np.diff(np.log(np.maximum(closes[-61:], 1e-6)))
            v60   = volumes[-60:] if len(volumes) >= 60 else volumes
            v60   = v60[:len(r60)]
            up_m  = r60 > 0
            dn_m  = r60 < 0
            up_vol = v60[up_m].mean() if up_m.any() else 0
            dn_vol = v60[dn_m].mean() if dn_m.any() else 1
            ud_ratio  = float(up_vol / max(dn_vol, 1))
            # Volume surge: avg vol on breakout window vs 20d average
            avg20 = volumes[-20:].mean() if len(volumes) >= 20 else volumes.mean()
            recent5 = volumes[-5:].mean() if len(volumes) >= 5 else volumes.mean()
            vol_surge = float(recent5 / max(avg20, 1))
            result["ud_ratio"]  = ud_ratio
            result["vol_surge"] = vol_surge

        result["S_score"] = _score_S(bk_pct, ud_ratio, vol_surge)

        # ── L score (RS percentile) ───────────────────────────
        # 12-1 month momentum (skip last month to avoid reversal)
        if len(closes) >= 252:
            r12 = (closes[-1] / closes[0])   - 1
            r1  = (closes[-1] / closes[-22]) - 1
            mom = r12 - r1
        elif len(closes) > 22:
            mom = (closes[-1] / closes[0]) - 1
        else:
            mom = 0.0

        result["_mom_raw"] = float(mom)

        # RS percentile will be assigned after all tickers are scored
        # For now, store the raw momentum for later ranking
        result["L_score"] = 7.5   # placeholder; updated in scorer.py

    except Exception as e:
        result["_error"] = str(e)

    # ── Cache ─────────────────────────────────────────────────
    try:
        cache_file.write_text(json.dumps(result, indent=2))
    except Exception:
        pass

    return result


# ── BASE PIVOT DETECTION ──────────────────────────────────────

def _detect_breakout(closes: np.ndarray, highs: np.ndarray,
                     lows: np.ndarray) -> tuple[float | None, float | None]:
    """
    Detect the most recent price base and compute breakout%.

    Algorithm:
      1. Find the lowest 20-day low in the trailing 6 months (base bottom)
      2. Find the highest high in the 10 weeks before the most recent high
         (this approximates the cup-with-handle pivot)
      3. Breakout% = (current − pivot) / pivot × 100

    Falls back to 52-week high × 0.95 as a simple pivot estimate
    if the pattern is ambiguous.
    """
    n = len(closes)
    if n < 40:
        return None, None

    current = float(closes[-1])

    # Look back window: up to 6 months (126 trading days)
    lookback = min(126, n - 1)
    window   = closes[-(lookback+1):-1]   # exclude current bar

    # Find approximate base: lowest point in lookback
    base_idx = int(np.argmin(window))
    base_low = float(window[base_idx])

    # Pivot = highest high between base bottom and 10 days before today
    # (the "right side" of the cup forms the pivot)
    right_start = base_idx
    right_end   = len(window) - 10
    if right_end <= right_start:
        right_end = len(window)

    right_highs = highs[-(lookback+1)+right_start:-(10) if right_end < len(window)-1 else None]
    if len(right_highs) < 3:
        # Simple fallback: use 52-week high as pivot
        pivot = float(np.max(closes[-252:])) if n >= 252 else float(np.max(closes))
        bk    = (current / pivot - 1) * 100
        return pivot, max(0.0, bk)

    pivot = float(np.max(right_highs))

    # Breakout% — if current is below pivot, stock hasn't broken out
    bk = (current / max(pivot, 1e-6) - 1) * 100
    bk = max(0.0, float(bk))   # clamp to 0 minimum

    return pivot, bk


# ── SCORING FUNCTIONS ─────────────────────────────────────────

def _score_N(bk_pct: float | None, dist_from_hi: float | None) -> float:
    """
    N criterion (0–15 pts): new catalyst confirmed by price breakout.
    High breakout% = strong N signal. Near 52-week high = additional confirmation.
    """
    if bk_pct is None:
        bk_pct = 0.0
    bk_pct = float(bk_pct)

    # N+S combined = (bk_pct / BREAKOUT_NORM) × NS_COMBINED_MAX
    # Split equally between N and S; can adjust ratio here
    combined = (bk_pct / BREAKOUT_NORM) * NS_COMBINED_MAX
    combined = min(combined, NS_COMBINED_MAX)

    # N gets 50% of the combined N+S score
    n_pts = combined * 0.50

    # Bonus: within 5% of 52-week high → near-ATH confirmation
    if dist_from_hi is not None and dist_from_hi <= 0.05:
        n_pts = min(N_MAX, n_pts + 1.5)
    elif dist_from_hi is not None and dist_from_hi <= 0.10:
        n_pts = min(N_MAX, n_pts + 0.75)

    return round(min(N_MAX, n_pts), 2)


def _score_S(bk_pct: float | None, ud_ratio: float | None,
             vol_surge: float | None) -> float:
    """
    S criterion (0–15 pts): supply/demand confirmed by volume.
    Volume surge on up days > down days = institutional accumulation.
    """
    if bk_pct is None:
        bk_pct = 0.0
    bk_pct = float(bk_pct)

    combined = (bk_pct / BREAKOUT_NORM) * NS_COMBINED_MAX
    combined = min(combined, NS_COMBINED_MAX)

    # S gets 50% of the combined N+S
    s_pts = combined * 0.50

    # Bonus: up-day volume > down-day volume (accumulation signal)
    if ud_ratio is not None:
        if ud_ratio >= 1.5:   s_pts = min(S_MAX, s_pts + 2.0)
        elif ud_ratio >= 1.2: s_pts = min(S_MAX, s_pts + 1.0)
        elif ud_ratio < 0.9:  s_pts = max(0, s_pts - 1.5)   # distribution penalty

    # Volume surge confirmation
    if vol_surge is not None:
        if vol_surge >= 1.5:  s_pts = min(S_MAX, s_pts + 1.0)

    return round(min(S_MAX, s_pts), 2)


def score_L_from_ranks(results: list[dict]) -> list[dict]:
    """
    Compute L scores after all tickers have been scored
    (requires cross-sectional ranking of momentum).
    Called from scorer.py once the full results list is available.
    """
    moms = [(r["ticker"], r.get("_mom_raw", 0.0)) for r in results
            if not r.get("error")]
    all_vals = [m[1] for m in moms]
    if not all_vals:
        return results

    for r in results:
        if r.get("error"):
            continue
        mom   = r.get("_mom_raw", 0.0)
        pct   = sum(1 for v in all_vals if v <= mom) / len(all_vals) * 100
        r["rs_pct"]  = float(pct)
        r["L_score"] = _score_L_from_pct(pct)

    return results


def _score_L_from_pct(pct: float) -> float:
    """
    Map RS percentile rank (0–100) to 0–15 pts.
    O'Neil requires RS ≥ 80 as a minimum for CANSLIM candidates.
    """
    if pct >= 95:   return 15.0
    if pct >= 90:   return 14.0
    if pct >= 85:   return 13.0
    if pct >= 80:   return 11.5   # O'Neil's minimum threshold
    if pct >= 75:   return 10.0
    if pct >= 70:   return  8.5
    if pct >= 60:   return  7.0
    if pct >= 50:   return  5.5
    if pct >= 40:   return  4.0
    if pct >= 25:   return  2.5
    return 1.0
