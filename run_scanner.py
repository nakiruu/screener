#!/usr/bin/env python3
"""
QQQ CANSLIM Scanner
===================
Scans every Nasdaq-100 (QQQ) constituent and scores each using the
reverse-engineered CANSLIM composite model.

Score Formula (reverse-engineered from Portfolio/Watchlist Audit):
  Score = FundamentalBase(C+A+I) + TechnicalBoost(N+S) + Leadership(L) + MarketGate(M)

  C  (0–25): Current quarterly EPS growth
  A  (0–20): Annual EPS CAGR + ROE quality
  N  (0–15): New catalyst / near ATH (proxied via Breakout%)
  S  (0–15): Supply/demand / volume confirmation (proxied via Breakout%)
  L  (0–15): Relative strength leadership rank
  I  (0– 5): Institutional ownership quality
  M  (0– 5): Market direction gate

Usage:
  python run_scanner.py                   Full scan, HTML + JSON output
  python run_scanner.py --top 20          Show top 20 only
  python run_scanner.py --min-score 75    Filter by min score
  python run_scanner.py --output json     JSON only (no HTML)
  python run_scanner.py --output html     HTML only
  python run_scanner.py --refresh         Bypass cache, re-fetch everything
  python run_scanner.py --ticker NVDA     Deep-dive single ticker
  python run_scanner.py --workers 8       Parallel fetch threads (default 6)
"""

import argparse
import json
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Dependency check ──────────────────────────────────────────
REQUIRED = {
    "yfinance": "yfinance",
    "pandas": "pandas",
    "numpy": "numpy",
    "requests": "requests",
    "bs4": "beautifulsoup4",
}
missing = []
for imp, pkg in REQUIRED.items():
    try:
        __import__(imp)
    except ImportError:
        missing.append(pkg)
if missing:
    print(f"[!] Missing packages. Run:\n    pip install {' '.join(missing)}")
    sys.exit(1)

import numpy as np
import pandas as pd

from scanners.qqq_holdings import get_qqq_holdings
from scanners.fundamental  import score_fundamentals
from scanners.technical    import score_technical
from scanners.market_gate  import score_market
from models.scorer         import build_composite_score, SCORE_TIERS, M_MAX
from output.report         import build_html_report
from output.export         import export_json, export_csv


# ── CLI ───────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="QQQ CANSLIM Scanner")
    p.add_argument("--top",        type=int,   default=None,
                   help="Show only top N results")
    p.add_argument("--min-score",  type=float, default=0,
                   help="Minimum composite score to include")
    p.add_argument("--output",     choices=["html","json","csv","all","none"],
                   default="all", help="Output format")
    p.add_argument("--refresh",    action="store_true",
                   help="Bypass cache and re-fetch all data")
    p.add_argument("--ticker",     type=str,   default=None,
                   help="Single ticker deep-dive mode")
    p.add_argument("--workers",    type=int,   default=6,
                   help="Parallel fetch threads (default 6)")
    p.add_argument("--period",     default="6mo",
                   help="yfinance period for price history (default 6mo)")
    p.add_argument("--quiet",      action="store_true",
                   help="Suppress per-ticker progress output")
    return p.parse_args()


# ── SINGLE TICKER PROCESSOR ───────────────────────────────────
def process_ticker(ticker: str, period: str, refresh: bool, quiet: bool) -> dict:
    """
    Run the full CANSLIM scoring pipeline for one ticker.
    Returns a result dict with all sub-scores and metadata.
    """
    result = {
        "ticker":     ticker,
        "error":      None,
        "C_score":    0, "C_eps_growth": None, "C_method": "unknown",
        "A_score":    0, "A_cagr": None,       "A_roe": None,
        "N_score":    0, "S_score": 0,
        "breakout_pct": None, "base_pivot": None,
        "L_score":    0, "rs_pct": None, "dist_from_hi": None,
        "I_score":    0, "inst_pct": None,
        "M_score":    0,
        "composite":  0,
        "price":      None,
        "sector":     None,
        "industry":   None,
        "signal":     "NEUTRAL",
    }

    try:
        # ── Fundamentals (C, A, I) ────────────────────────────
        fund = score_fundamentals(ticker, refresh=refresh)
        result.update({
            "C_score":    fund["C_score"],
            "C_eps_growth": fund.get("eps_growth"),
            "C_method":   fund.get("method", "unknown"),
            "A_score":    fund["A_score"],
            "A_cagr":     fund.get("eps_cagr"),
            "A_roe":      fund.get("roe"),
            "I_score":    fund["I_score"],
            "inst_pct":   fund.get("inst_pct"),
            "price":      fund.get("price"),
            "sector":     fund.get("sector"),
            "industry":   fund.get("industry"),
        })

        # ── Technical (N, S, L) ───────────────────────────────
        tech = score_technical(ticker, period=period, refresh=refresh)
        result.update({
            "N_score":      tech["N_score"],
            "S_score":      tech["S_score"],
            "breakout_pct": tech.get("breakout_pct"),
            "base_pivot":   tech.get("base_pivot"),
            "L_score":      tech["L_score"],
            "rs_pct":       tech.get("rs_pct"),
            "dist_from_hi": tech.get("dist_from_hi"),
        })

        # ── Market gate (M) ───────────────────────────────────
        # Note: market gate is fetched once and shared; pass through
        result["M_score"] = fund.get("M_score", 4)

        # ── Composite ─────────────────────────────────────────
        composite = build_composite_score(result)
        result["composite"] = composite
        result["signal"]    = _signal(composite)

        if not quiet:
            tier = result["signal"]
            bk   = f"{result['breakout_pct']:.0f}%" if result["breakout_pct"] is not None else "n/a"
            print(f"  {ticker:6s}  score={composite:5.1f}  bk={bk:6s}  {tier}")

    except Exception as e:
        result["error"] = str(e)
        if not quiet:
            print(f"  {ticker:6s}  ERROR: {e}")

    return result


# ── SIGNAL LABEL ──────────────────────────────────────────────
def _signal(score: float) -> str:
    for lo, hi, label in SCORE_TIERS:
        if lo <= score < hi:
            return label
    return "NEUTRAL"


# ── SWING LEVELS ─────────────────────────────────────────────
def _print_swing_levels(r: dict) -> None:
    """Print buy zone, stop, and targets for a BUY / STRONG BUY result."""
    import yfinance as yf

    ticker = r["ticker"]
    pivot  = r.get("base_pivot")
    bk_pct = r.get("breakout_pct") or 0.0

    try:
        hist   = yf.Ticker(ticker).history(period="3mo")
        closes = hist["Close"].values.astype(float)
    except Exception:
        print(f"    [{ticker}] Could not fetch price data.")
        return

    if len(closes) < 21:
        return

    price = closes[-1]

    def _ema(s, p):
        k = 2 / (p + 1)
        e = np.zeros(len(s))
        e[p - 1] = np.mean(s[:p])
        for i in range(p, len(s)):
            e[i] = s[i] * k + e[i - 1] * (1 - k)
        return float(e[-1])

    e10    = _ema(closes, 10)
    e21    = _ema(closes, 21)
    hi3wk  = float(np.max(closes[-15:]))
    trail  = round(hi3wk * 0.925, 2)

    if pivot and bk_pct <= 5.0:
        setup   = "pivot breakout"
        entry   = round(pivot + 0.10, 2)
        zone_lo = round(pivot,         2)
        zone_hi = round(pivot * 1.05,  2)
    elif bk_pct > 40.0:
        setup   = "pullback to 21-EMA (too extended to chase)"
        entry   = round(e21 * 1.005, 2)
        zone_lo = round(e21 * 0.99,  2)
        zone_hi = round(e21 * 1.02,  2)
    else:
        setup   = f"at market ({bk_pct:.0f}% above pivot)"
        entry   = round(price, 2)
        zone_lo = round(price * 0.99,  2)
        zone_hi = round(price * 1.02,  2)

    stop   = round(entry * 0.925, 2)
    t1     = round(entry * 1.20,  2)
    t2     = round(entry * 1.50,  2)
    risk   = entry - stop
    reward = t1 - entry
    rr     = round(reward / risk, 2) if risk > 0 else 0.0

    print(f"\n  {ticker}  [{r['signal']}  {r['composite']:.1f} pts]")
    print(f"    Setup:      {setup}")
    print(f"    Buy zone:   ${zone_lo:.2f} - ${zone_hi:.2f}  (ideal: ${entry:.2f})")
    print(f"    Stop loss:  ${stop:.2f}  (-7.5%)")
    print(f"    Target 1:   ${t1:.2f}  (+20%)")
    print(f"    Target 2:   ${t2:.2f}  (+50%)")
    print(f"    R/R:        {rr:.1f}x")
    print(f"    EMAs:       10-EMA ${e10:.2f}  |  21-EMA ${e21:.2f}  |  3-wk trail ${trail:.2f}")
    print(f"    Watch:      Exit if price closes below 10-EMA (${e10:.2f}) 2 days in a row.")


# ── MAIN ──────────────────────────────────────────────────────
def main():
    args = parse_args()
    start_ts = datetime.now()

    print("\n" + "="*65)
    print("  QQQ CANSLIM SCANNER")
    print(f"  Started: {start_ts.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*65)

    # ── Get holdings ──────────────────────────────────────────
    if args.ticker:
        tickers = [args.ticker.upper()]
        print(f"\n[MODE] Single-ticker deep-dive: {tickers[0]}")
    else:
        print("\n[0] Fetching QQQ holdings...")
        tickers = get_qqq_holdings(refresh=args.refresh)
        print(f"     {len(tickers)} Nasdaq-100 constituents loaded")

    # ── Market gate (compute once for all tickers) ────────────
    print("\n[1] Computing market direction gate (XLK/QQQ)...")
    mkt = score_market(refresh=args.refresh)
    M_score = mkt["M_score"]
    print(f"     Gate: {'OPEN [OK]' if mkt['gate_open'] else 'CLOSED [X]'}  "
          f"Dist days: {mkt['dist_days']}  "
          f"XLK 20d: {mkt['trend_20']*100:+.1f}%  "
          f"M pts: {M_score}/5  ({round(M_score/5*M_MAX,1)}/{M_MAX} swing)")

    # ── Scan all tickers ──────────────────────────────────────
    print(f"\n[2] Scanning {len(tickers)} tickers "
          f"({'cache bypass' if args.refresh else 'using cache'}, "
          f"{args.workers} workers)...")
    print(f"     {'Ticker':6s}  {'Score':5s}  {'Breakout':6s}  Signal")
    print(f"     {'-'*45}")

    results = []
    errors  = []

    def _process(t):
        r = process_ticker(t, args.period, args.refresh, args.quiet)
        # Scale raw M_score (0–5) to swing M_MAX range before composite
        r["M_score"] = round(M_score / 5.0 * M_MAX, 1)
        r["composite"] = build_composite_score(r)
        r["signal"]    = _signal(r["composite"])
        return r

    if args.workers == 1:
        for t in tickers:
            results.append(_process(t))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(_process, t): t for t in tickers}
            for fut in as_completed(futures):
                r = fut.result()
                results.append(r)
                if r["error"]:
                    errors.append(r["ticker"])

    # ── Sort & filter ─────────────────────────────────────────
    results.sort(key=lambda r: -r["composite"])
    if args.min_score > 0:
        results = [r for r in results if r["composite"] >= args.min_score]
    if args.top:
        results = results[:args.top]

    # ── Summary ───────────────────────────────────────────────
    elapsed = (datetime.now() - start_ts).total_seconds()
    valid   = [r for r in results if not r["error"]]
    scores  = [r["composite"] for r in valid]

    print(f"\n{'='*65}")
    print(f"  SCAN COMPLETE  ({elapsed:.1f}s  ·  {len(errors)} errors)")
    print(f"{'='*65}")

    if scores:
        print(f"\n  Tickers scanned:    {len(tickers)}")
        print(f"  Valid results:      {len(valid)}")
        print(f"  Score range:        {min(scores):.1f} – {max(scores):.1f}")
        print(f"  Mean score:         {np.mean(scores):.1f}")
        print(f"  Median score:       {np.median(scores):.1f}")

        # Tier breakdown
        tier_counts = {}
        for r in valid:
            tier_counts[r["signal"]] = tier_counts.get(r["signal"], 0) + 1
        print(f"\n  Signal breakdown:")
        order = ["STRONG BUY", "BUY", "WATCH", "MONITOR", "PASS"]
        for sig in order:
            n = tier_counts.get(sig, 0)
            bar = "#" * n
            print(f"    {sig:12s} {n:3d}  {bar}")

    # ── Print top results ─────────────────────────────────────
    top_n = min(20, len(valid))
    print(f"\n  TOP {top_n} RESULTS:")
    print(f"  {'#':3s} {'Ticker':7s} {'Score':6s} {'BK%':6s} "
          f"{'C':4s} {'A':4s} {'NS':4s} {'L':4s} {'I':3s} {'M':3s}  Signal")
    print(f"  {'-'*65}")
    for i, r in enumerate(valid[:top_n], 1):
        ns  = r["N_score"] + r["S_score"]
        bk  = f"{r['breakout_pct']:.0f}%" if r["breakout_pct"] is not None else "n/a"
        print(f"  {i:3d} {r['ticker']:7s} {r['composite']:6.1f} {bk:6s} "
              f"{r['C_score']:4.1f} {r['A_score']:4.1f} {ns:4.1f} "
              f"{r['L_score']:4.1f} {r['I_score']:3.1f} {r['M_score']:3.1f}  "
              f"{r['signal']}")

    # ── Swing levels for actionable tickers ──────────────────
    actionable = [r for r in valid if r["signal"] in ("STRONG BUY", "BUY")]
    if actionable:
        print(f"\n  ACTIONABLE SETUPS — BUY / STRONG BUY ({len(actionable)}):")
        print(f"  {'-'*65}")
        for r in actionable:
            _print_swing_levels(r)

    if errors:
        print(f"\n  Errors ({len(errors)}): {errors[:10]}"
              + (" ..." if len(errors) > 10 else ""))

    # ── Output ────────────────────────────────────────────────
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    ts_str  = start_ts.strftime("%Y%m%d_%H%M%S")

    all_results = {
        "meta": {
            "run_time":      start_ts.isoformat(),
            "elapsed_s":     elapsed,
            "total_tickers": len(tickers),
            "valid_results": len(valid),
            "errors":        errors,
            "market":        mkt,
            "args":          vars(args),
        },
        "results": results,
    }

    if args.output in ("json", "all"):
        path = out_dir / f"qqq_scan_{ts_str}.json"
        export_json(all_results, str(path))
        print(f"\n  [OK] JSON: {path}")

    if args.output in ("csv", "all"):
        path = out_dir / f"qqq_scan_{ts_str}.csv"
        export_csv(results, str(path))
        print(f"  [OK] CSV:  {path}")

    if args.output in ("html", "all"):
        path = out_dir / f"qqq_scan_{ts_str}.html"
        build_html_report(all_results, str(path))
        print(f"  [OK] HTML: {path}  (open in browser)")

    print()
    return all_results


if __name__ == "__main__":
    main()
