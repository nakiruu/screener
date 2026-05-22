#!/usr/bin/env python3
"""
Intraday Entry Scanner — QQQ Tickers
=====================================
Runs pre-market or intraday to find the best setup candidates today.

For each ticker:
  - Loads FA score from cache (C+A+I)
  - Fetches last 5 days of 5m bars → yesterday VWAP, EMAs, range
  - Fetches current price via fast_info
  - Scores setup quality and outputs ranked entry plan

Usage:
  python run_intraday.py              # all QQQ, top 15 printed
  python run_intraday.py --top 20
  python run_intraday.py --ticker NVDA AAPL
  python run_intraday.py --min-score 50
"""

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np

# ── ANSI ────────────────────────────────────────────────────────
R  = "\033[1;31m"
Y  = "\033[0;33m"
G  = "\033[0;32m"
C  = "\033[0;36m"
B  = "\033[1m"
D  = "\033[2m"
RS = "\033[0m"

# ── Constants ───────────────────────────────────────────────────
FUND_CACHE = Path("data/fund_cache")
QQQ_CACHE  = Path("data/qqq_holdings_cache.json")

STOP_PCT   = 0.075
T1_PCT     = 0.20


def get_tickers(specified: list[str] | None = None) -> list[str]:
    if specified:
        return [t.upper() for t in specified]
    if QQQ_CACHE.exists():
        d = json.loads(QQQ_CACHE.read_text())
        return d.get("tickers", d.get("holdings", []))
    from scanners.qqq_holdings import get_qqq_holdings
    return get_qqq_holdings()


def load_fa_scores() -> dict[str, dict]:
    """Load fundamental scores (C+A+I+M) from cache."""
    scores = {}
    for f in FUND_CACHE.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            scores[f.stem] = d
        except Exception:
            pass
    return scores


# ── Intraday data helpers ────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def fetch_intraday(ticker: str) -> dict | None:
    """
    Fetch 5-day 5m bars and compute key intraday levels.
    Returns dict with yesterday/today stats, or None on failure.
    """
    try:
        raw = yf.download(
            ticker, period="5d", interval="5m",
            progress=False, threads=False, auto_adjust=True,
        )
        if raw is None or len(raw) < 10:
            return None

        # Flatten MultiIndex columns if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(1)

        # Split into yesterday vs today (or most recent two sessions)
        raw.index = pd.to_datetime(raw.index)
        days = sorted(raw.index.normalize().unique())
        if len(days) < 2:
            return None

        yesterday_date = days[-2]
        today_date     = days[-1]

        yest  = raw[raw.index.normalize() == yesterday_date].copy()
        today = raw[raw.index.normalize() == today_date].copy()

        if len(yest) < 5:
            return None

        # ── Yesterday levels ──────────────────────────────────
        yest_close = float(yest["Close"].iloc[-1])
        yest_high  = float(yest["High"].max())
        yest_low   = float(yest["Low"].min())
        yest_open  = float(yest["Open"].iloc[0])

        # VWAP (yesterday)
        tp    = (yest["High"] + yest["Low"] + yest["Close"]) / 3
        vol   = yest["Volume"]
        vwap  = float((tp * vol).sum() / vol.sum()) if vol.sum() > 0 else yest_close

        # EMAs on yesterday's close series
        closes_all = raw["Close"]
        ema9_all   = _ema(closes_all, 9)
        ema20_all  = _ema(closes_all, 20)
        ema9_yest  = float(ema9_all[yest.index[-1]])
        ema20_yest = float(ema20_all[yest.index[-1]])

        # Yesterday volume profile
        yest_vol   = int(yest["Volume"].sum())
        avg5d_vol  = int(raw["Volume"].sum() / max(len(days), 1))

        # ── Today/pre-market ─────────────────────────────────
        pm_high = pm_low = pm_price = None
        if len(today) > 0:
            pm_high  = float(today["High"].max())
            pm_low   = float(today["Low"].min())
            pm_price = float(today["Close"].iloc[-1])

        return {
            "yest_close":  yest_close,
            "yest_high":   yest_high,
            "yest_low":    yest_low,
            "yest_open":   yest_open,
            "vwap":        vwap,
            "ema9":        ema9_yest,
            "ema20":       ema20_yest,
            "yest_vol":    yest_vol,
            "avg5d_vol":   avg5d_vol,
            "pm_high":     pm_high,
            "pm_low":      pm_low,
            "pm_price":    pm_price,
            "today_bars":  len(today),
        }
    except Exception:
        return None


def fetch_current_price(ticker: str) -> float | None:
    """Fast pre-market / live price via fast_info."""
    try:
        fi = yf.Ticker(ticker).fast_info
        p  = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
        if p and float(p) > 0:
            return float(p)
    except Exception:
        pass
    return None


# ── Setup scoring ────────────────────────────────────────────────

def score_setup(fa: dict, intra: dict, cur_price: float | None) -> dict:
    """
    Combine FA fundamentals + intraday technicals into a setup score (0–100).
    Higher = better entry opportunity today.
    """
    C_score = fa.get("C_score", 0)
    A_score = fa.get("A_score", 0)
    I_score = fa.get("I_score", 0)
    M_score = fa.get("M_score", 0)
    fa_total = C_score + A_score + I_score + M_score   # 0–55

    yest_close  = intra["yest_close"]
    vwap        = intra["vwap"]
    ema9        = intra["ema9"]
    ema20       = intra["ema20"]
    pm_price    = cur_price or intra.get("pm_price") or yest_close

    # ── Gap direction & size ──────────────────────────────────
    gap_pct = (pm_price - yest_close) / yest_close      # negative = gap down

    # ── Price vs key levels ───────────────────────────────────
    vs_vwap  = (pm_price - vwap)  / vwap
    vs_ema9  = (pm_price - ema9)  / ema9
    vs_ema20 = (pm_price - ema20) / ema20

    # ── Intraday setup quality score (0–45) ───────────────────
    setup_score = 0.0
    flags       = []

    # 1) Gap quality (max 15 pts)
    #    Best: small gap-up (+0.5% to +2%) or flat
    #    OK: gap up 2-5% or gap down < 1%
    #    Bad: gap > 7% (runaway), gap down > 3%
    if 0.005 <= gap_pct <= 0.02:
        setup_score += 15; flags.append("clean gap-up")
    elif 0.0 <= gap_pct < 0.005:
        setup_score += 13; flags.append("flat-open")
    elif 0.02 < gap_pct <= 0.05:
        setup_score += 10; flags.append("gap-up 2-5%")
    elif -0.01 <= gap_pct < 0:
        setup_score += 8;  flags.append("slight gap-down")
    elif 0.05 < gap_pct <= 0.08:
        setup_score += 6;  flags.append("gap-up 5-8%")
    elif -0.03 <= gap_pct < -0.01:
        setup_score += 4;  flags.append("gap-down 1-3%")
    elif gap_pct > 0.08:
        setup_score += 2;  flags.append(f"runaway +{gap_pct*100:.0f}%")
    else:
        setup_score += 0;  flags.append(f"large gap-dn {gap_pct*100:.1f}%")

    # 2) Price vs VWAP (max 15 pts) — near or just above VWAP is ideal
    if -0.005 <= vs_vwap <= 0.01:
        setup_score += 15; flags.append("at VWAP")
    elif 0.01 < vs_vwap <= 0.03:
        setup_score += 12; flags.append("just above VWAP")
    elif -0.02 <= vs_vwap < -0.005:
        setup_score += 8;  flags.append("just below VWAP")
    elif 0.03 < vs_vwap <= 0.06:
        setup_score += 7;  flags.append("extended above VWAP")
    elif -0.05 <= vs_vwap < -0.02:
        setup_score += 4;  flags.append("below VWAP")
    elif vs_vwap > 0.06:
        setup_score += 2;  flags.append("far above VWAP")
    else:
        setup_score += 1;  flags.append("far below VWAP")

    # 3) EMA alignment (max 15 pts)
    #    Price above 9-EMA, 9>20 = trending
    ema_trending = ema9 > ema20
    if pm_price > ema9 > ema20:
        setup_score += 15; flags.append("above both EMAs")
    elif pm_price > ema9 and not ema_trending:
        setup_score += 10; flags.append("above 9-EMA (flat)")
    elif ema9 > ema20 and pm_price < ema9 * 1.01:
        setup_score += 8;  flags.append("pullback to 9-EMA")
    elif pm_price > ema20:
        setup_score += 6;  flags.append("above 20-EMA")
    else:
        setup_score += 2;  flags.append("below 20-EMA")

    # ── Total ─────────────────────────────────────────────────
    # Normalize setup to 0–45 (already max 45 from three categories)
    total = fa_total + setup_score

    # ── Entry plan ───────────────────────────────────────────
    stop     = round(pm_price * (1 - STOP_PCT), 2)
    t1       = round(pm_price * (1 + T1_PCT), 2)
    risk_r   = round(T1_PCT / STOP_PCT, 1)

    # Best entry price:
    # - If gapping up cleanly: buy on first 5m pullback to VWAP or 9-EMA
    # - If flat/slight gap-dn: buy on reclaim of yesterday's close
    if gap_pct > 0.01:
        entry_desc = f"pullback to VWAP ${vwap:,.2f} or 9-EMA ${ema9:,.2f}"
        entry_low  = round(min(vwap, ema9) * 0.998, 2)
        entry_high = round(max(vwap, ema9) * 1.005, 2)
    elif gap_pct >= -0.005:
        entry_desc = f"reclaim ${yest_close:,.2f} prev-close + hold"
        entry_low  = round(yest_close * 0.999, 2)
        entry_high = round(yest_close * 1.01, 2)
    else:
        entry_desc = f"VWAP reclaim ${vwap:,.2f}"
        entry_low  = round(vwap * 0.998, 2)
        entry_high = round(vwap * 1.01, 2)

    return {
        "fa_pts":      round(fa_total, 1),
        "setup_pts":   round(setup_score, 1),
        "total":       round(total, 1),
        "gap_pct":     round(gap_pct * 100, 2),
        "pm_price":    round(pm_price, 2),
        "vwap":        round(vwap, 2),
        "ema9":        round(ema9, 2),
        "ema20":       round(ema20, 2),
        "vs_vwap":     round(vs_vwap * 100, 2),
        "entry_low":   entry_low,
        "entry_high":  entry_high,
        "entry_desc":  entry_desc,
        "stop":        stop,
        "t1":          t1,
        "risk_r":      risk_r,
        "flags":       flags,
        "yest_close":  intra["yest_close"],
        "yest_high":   intra["yest_high"],
        "yest_low":    intra["yest_low"],
    }


# ── Rendering ────────────────────────────────────────────────────

def _tier_color(score: float) -> str:
    if score >= 80: return G
    if score >= 65: return C
    if score >= 50: return Y
    return D


def render_results(results: list[dict], top_n: int) -> None:
    import shutil
    cols = shutil.get_terminal_size((120, 40)).columns

    from live.market_hours import market_status
    mkt = market_status()
    now = datetime.now().strftime("%H:%M:%S")

    print(f"\n{B}  QQQ INTRADAY ENTRY SCANNER{RS}  "
          f"{C}{mkt['status']}{RS}  {D}{mkt['label']}{RS}  "
          f"{D}run {now}{RS}")
    print("─" * cols)

    ranked = sorted(results, key=lambda x: x["total"], reverse=True)
    show   = ranked[:top_n]

    # Header
    print(f"  {'#':>2}  {'TICKER':<7} {'SCORE':>5}  {'FA':>4}  {'SETUP':>5}  "
          f"{'CUR':>9}  {'GAP%':>6}  {'VWAP':>9}  {'9-EMA':>9}  {'vsVWAP':>7}  FLAGS")
    print("  " + "─" * (cols - 2))

    for i, r in enumerate(show, 1):
        tc  = _tier_color(r["total"])
        g_c = G if r["gap_pct"] >= 0 else R
        v_c = G if r["vs_vwap"] >= 0 else Y
        g_s = f"{'+' if r['gap_pct']>=0 else ''}{r['gap_pct']:.1f}%"
        v_s = f"{'+' if r['vs_vwap']>=0 else ''}{r['vs_vwap']:.1f}%"

        print(f"  {i:>2}  {tc}{r['ticker']:<7}{RS} "
              f"{tc}{r['total']:>5.1f}{RS}  "
              f"{r['fa_pts']:>4.0f}  "
              f"{r['setup_pts']:>5.0f}  "
              f"${r['pm_price']:>8,.2f}  "
              f"{g_c}{g_s:>6}{RS}  "
              f"${r['vwap']:>8,.2f}  "
              f"${r['ema9']:>8,.2f}  "
              f"{v_c}{v_s:>7}{RS}  "
              f"{D}{', '.join(r['flags'])}{RS}")

    print("\n" + "─" * cols)
    print(f"{B}  TOP SETUPS — ENTRY PLANS{RS}")
    print("─" * cols)

    for i, r in enumerate(show[:10], 1):
        tc  = _tier_color(r["total"])
        g_c = G if r["gap_pct"] >= 0 else R

        print(f"\n  {tc}{B}#{i} {r['ticker']}{RS}  "
              f"score {tc}{r['total']:.0f}{RS}  "
              f"current ${r['pm_price']:,.2f}  "
              f"gap {g_c}{'+' if r['gap_pct']>=0 else ''}{r['gap_pct']:.1f}%{RS}")
        print(f"  {D}  Entry : {r['entry_desc']}{RS}")
        print(f"  {D}  Zone  : ${r['entry_low']:,.2f} – ${r['entry_high']:,.2f}{RS}")
        print(f"  {D}  Stop  : ${r['stop']:,.2f}  →  T1 ${r['t1']:,.2f}  "
              f"(R/R {r['risk_r']}x){RS}")
        print(f"  {D}  Levels: yest-close ${r['yest_close']:,.2f}  "
              f"VWAP ${r['vwap']:,.2f}  "
              f"9-EMA ${r['ema9']:,.2f}  "
              f"20-EMA ${r['ema20']:,.2f}{RS}")

    print(f"\n{'─'*cols}\n")


# ── Main ─────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="QQQ Intraday Entry Scanner")
    p.add_argument("--ticker", nargs="+", help="Specific tickers to scan")
    p.add_argument("--top", type=int, default=15, help="Show top N results (default 15)")
    p.add_argument("--min-score", type=float, default=0, help="Minimum total score filter")
    p.add_argument("--delay", type=float, default=0.1,
                   help="Seconds between requests (default 0.1)")
    return p.parse_args()


def main():
    args = parse_args()
    tickers = get_tickers(args.ticker)
    fa_cache = load_fa_scores()

    print(f"\n  Scanning {len(tickers)} tickers for intraday setups…")
    print(f"  FA scores loaded from cache: {len(fa_cache)}")
    print(f"  Fetching 5m intraday data + pre-market prices…\n")

    results = []
    errors  = 0

    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i:>3}/{len(tickers)}] {ticker:<8}", end="", flush=True)

        fa = fa_cache.get(ticker, {})
        if not fa:
            print(f"  {D}no FA cache — skipping{RS}")
            errors += 1
            continue

        intra = fetch_intraday(ticker)
        if intra is None:
            print(f"  {D}no intraday data{RS}")
            errors += 1
            if args.delay:
                time.sleep(args.delay)
            continue

        cur = fetch_current_price(ticker)
        setup = score_setup(fa, intra, cur)

        result = {
            "ticker":   ticker,
            "sector":   fa.get("sector", ""),
            **setup,
        }

        if result["total"] >= args.min_score:
            results.append(result)
            tc = _tier_color(result["total"])
            print(f"  score {tc}{result['total']:.0f}{RS}  gap {'+' if result['gap_pct']>=0 else ''}{result['gap_pct']:.1f}%  {D}{', '.join(result['flags'][:2])}{RS}")
        else:
            print(f"  {D}score {result['total']:.0f} — below min{RS}")

        if args.delay:
            time.sleep(args.delay)

    print(f"\n  Done. {len(results)} setups scored, {errors} skipped.\n")

    if not results:
        print("  No results to display.")
        return

    render_results(results, args.top)

    # Save to JSON for reference
    out = Path("data/intraday_setups.json")
    out.write_text(json.dumps(
        sorted(results, key=lambda x: x["total"], reverse=True),
        indent=2
    ))
    print(f"  Saved to {out}\n")


if __name__ == "__main__":
    main()
