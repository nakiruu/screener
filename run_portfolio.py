#!/usr/bin/env python3
"""
QQQ CANSLIM Portfolio Manager
==============================
Analyses your stock holdings using FA + TA and recommends specific actions
per position (ADD / HOLD / TRIM / SELL / STOP LOSS) and per option leg.

Usage:
  python run_portfolio.py --portfolio portfolio.json
  python run_portfolio.py --portfolio portfolio.json --refresh
  python run_portfolio.py --portfolio portfolio.json --output json

Portfolio JSON format (see portfolio/sample_portfolio.json):
  {
    "positions": [
      {
        "ticker":     "NVDA",
        "shares":     100,
        "cost_basis": 850.00,
        "options": [
          {
            "type":         "call",
            "strike":       950.00,
            "contracts":    2,
            "expiry":       "2026-06-20",
            "premium_paid": 45.00
          }
        ]
      }
    ]
  }
"""

import argparse
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

REQUIRED = {"yfinance": "yfinance", "pandas": "pandas",
            "numpy": "numpy", "requests": "requests"}
import importlib.util as _ilu
missing = [pkg for imp, pkg in REQUIRED.items()
           if not _ilu.find_spec(imp)]
if missing:
    print(f"[!] Missing: pip install {' '.join(missing)}")
    sys.exit(1)

from portfolio.manager import analyse_portfolio

URGENCY_ICON = {"URGENT": "🚨", "HIGH": "⚠️ ", "ELEVATED": "⚡", "NORMAL": "  "}
URGENCY_ORDER = {"URGENT": 0, "HIGH": 1, "ELEVATED": 2, "NORMAL": 3}


def parse_args():
    p = argparse.ArgumentParser(description="CANSLIM Portfolio Manager")
    p.add_argument("--portfolio", required=True,
                   help="Path to portfolio JSON file")
    p.add_argument("--refresh",  action="store_true",
                   help="Bypass cache and re-fetch all data")
    p.add_argument("--output",   choices=["text", "json"], default="text")
    p.add_argument("--period",   default="6mo",
                   help="Price history period for TA (default 6mo)")
    return p.parse_args()


def main():
    args    = parse_args()
    port_path = Path(args.portfolio)

    if not port_path.exists():
        print(f"[!] Portfolio file not found: {port_path}")
        sys.exit(1)

    portfolio = json.loads(port_path.read_text())
    positions = portfolio.get("positions", [])
    if not positions:
        print("[!] No positions found in portfolio file.")
        sys.exit(1)

    start = datetime.now()
    print("\n" + "=" * 65)
    print("  CANSLIM PORTFOLIO MANAGER")
    print(f"  {port_path.name}  |  {len(positions)} positions  |  "
          f"{start.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    print("\n[...] Fetching market gate + scoring positions...\n")
    result = analyse_portfolio(positions, refresh=args.refresh,
                               period=args.period)

    if args.output == "json":
        print(json.dumps(result, indent=2, default=str))
        return

    _print_market(result["market"])
    _print_summary(result["summary"])
    _print_positions(result["positions"])

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n  Done in {elapsed:.1f}s\n")


# ── OUTPUT FORMATTERS ─────────────────────────────────────────

def _print_market(m: dict) -> None:
    gate = "OPEN  ✓" if m.get("gate_open") else "CLOSED ✗"
    print(f"  Market gate : {gate}  |  {m.get('market_note','?')}")
    print(f"  Dist days   : {m.get('dist_days','?')} / 25  |  "
          f"XLK 20d: {m.get('trend_20',0)*100:+.1f}%  |  "
          f"M score: {m.get('M_score','?')}/5\n")


def _print_summary(s: dict) -> None:
    pnl_pct = s.get("total_pnl_pct", 0) * 100
    pnl_d   = s.get("total_pnl_dollar", 0)
    sign    = "+" if pnl_d >= 0 else ""
    print(f"  Portfolio P&L : {sign}${pnl_d:,.0f}  ({sign}{pnl_pct:.1f}%)")
    print(f"  Cost basis    : ${s.get('total_cost_basis',0):,.0f}  →  "
          f"Market value: ${s.get('total_mkt_value',0):,.0f}")

    urg = s.get("urgency_counts", {})
    flags = []
    if urg.get("URGENT"):  flags.append(f"🚨 {urg['URGENT']} URGENT")
    if urg.get("HIGH"):    flags.append(f"⚠️  {urg['HIGH']} HIGH")
    if urg.get("ELEVATED"):flags.append(f"⚡ {urg['ELEVATED']} ELEVATED")
    if flags:
        print(f"  Alerts        : {' | '.join(flags)}")
    print()


def _print_positions(positions: list[dict]) -> None:
    # Sort: URGENT first, then by urgency, then by P&L descending
    def _sort_key(r):
        return (URGENCY_ORDER.get(r.get("urgency", "NORMAL"), 3),
                -(r.get("pnl_pct") or 0))

    sorted_pos = sorted(positions, key=_sort_key)

    print("  " + "─" * 63)
    print(f"  {'TICKER':<7} {'SCORE':>5}  {'SIGNAL':<10}  "
          f"{'P&L':>8}  {'BK%':>5}  {'ACTION'}")
    print("  " + "─" * 63)

    for r in sorted_pos:
        icon    = URGENCY_ICON.get(r.get("urgency", "NORMAL"), "  ")
        ticker  = r["ticker"]
        score   = r.get("composite", 0)
        signal  = r.get("signal", "?")
        action  = r.get("stock_action", "?")
        bk      = f"{r['breakout_pct']:.0f}%" if r.get("breakout_pct") is not None else "  n/a"
        pnl_pct = r.get("pnl_pct")
        pnl_str = f"{pnl_pct*100:+.1f}%" if pnl_pct is not None else "    n/a"
        price   = r.get("price")

        print(f"  {icon}{ticker:<7} {score:>5.1f}  {signal:<10}  "
              f"{pnl_str:>8}  {bk:>5}  {action}")
        print(f"          {r.get('stock_rationale','')}")

        # Key levels
        if r.get("price") and r.get("cost_basis"):
            stop = r.get("stop_price")
            t1   = r.get("t1_price")
            t2   = r.get("t2_price")
            pv   = r.get("base_pivot")
            pv_s = f"  Pivot ${pv:.2f}" if pv else ""
            print(f"          Price ${price:.2f}  |  Stop ${stop:.2f}  |  "
                  f"T1 ${t1:.2f}  |  T2 ${t2:.2f}{pv_s}")

        # Scores breakdown
        c  = r.get("C_score", 0)
        a  = r.get("A_score", 0)
        ns = (r.get("N_score", 0) or 0) + (r.get("S_score", 0) or 0)
        l  = r.get("L_score", 0)
        rs = r.get("rs_pct")
        rs_s = f"  RS {rs:.0f}th" if rs is not None else ""
        print(f"          FA: C={c:.0f} A={a:.0f} I={r.get('I_score',0):.0f}  |  "
              f"TA: NS={ns:.1f} L={l:.0f}{rs_s}")

        # Options
        for oa in r.get("option_actions", []):
            strike  = oa.get("strike")
            otype   = oa.get("type", "?").upper()
            dte     = oa.get("dte")
            dte_s   = f"{dte}d" if dte is not None else "?"
            itm_s   = "ITM" if oa.get("itm") else "OTM"
            intr    = oa.get("intrinsic")
            intr_s  = f"  intrinsic ${intr:.2f}" if intr else ""
            oa_act  = oa.get("action", "?")
            print(f"          ├─ {otype} ${strike:.0f}  {itm_s}  {dte_s} to expiry"
                  f"{intr_s}  →  {oa_act}")
            print(f"          │  {oa.get('rationale','')}")

        print()


if __name__ == "__main__":
    main()
