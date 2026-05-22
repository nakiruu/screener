#!/usr/bin/env python3
"""
QQQ CANSLIM Live Portfolio Monitor
====================================
Watches your portfolio in real time: refreshes prices every N seconds,
recomputes P&L and action recommendations, and alerts on stop-loss triggers.

CANSLIM fundamentals (C/A/I) and technicals (N/S/L, breakout) are computed
once at startup from cache and held frozen between refreshes.  Only price
and derived P&L fields update on each tick.

Usage:
  python run_live.py --portfolio portfolio/sample_portfolio.json
  python run_live.py --portfolio my_positions.json --interval 60
  python run_live.py --portfolio my_positions.json --once
  python run_live.py --portfolio my_positions.json --refresh   # force cache refresh at startup
"""

import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

from portfolio.manager  import analyse_portfolio
from live.price_feed    import fetch_live_prices
from live.refresher     import build_live_snapshot
from live.display       import print_dashboard
from live.market_hours  import market_status, is_market_open

CACHE_REFRESH_INTERVAL = 4 * 3600   # re-run full CANSLIM score every 4h


def parse_args():
    p = argparse.ArgumentParser(description="CANSLIM Live Portfolio Monitor")
    p.add_argument("--portfolio", required=True,
                   help="Path to portfolio JSON (same format as run_portfolio.py)")
    p.add_argument("--interval",  type=int, default=30,
                   help="Seconds between price refreshes (default: 30)")
    p.add_argument("--once",      action="store_true",
                   help="Run once and exit (no loop)")
    p.add_argument("--refresh",   action="store_true",
                   help="Force re-fetch all CANSLIM data at startup (bypass cache)")
    p.add_argument("--period",    default="6mo",
                   help="Price history period for TA at startup (default: 6mo)")
    return p.parse_args()


def main():
    args = parse_args()

    port_path = Path(args.portfolio)
    if not port_path.exists():
        print(f"[!] Portfolio file not found: {port_path}")
        sys.exit(1)

    portfolio  = json.loads(port_path.read_text())
    positions  = portfolio.get("positions", [])
    if not positions:
        print("[!] No positions found.")
        sys.exit(1)

    tickers = [p["ticker"].upper() for p in positions]

    # ── Startup: full CANSLIM score (slow, cached after first run) ─
    print(f"\n  Loading CANSLIM scores for {len(tickers)} positions…", end="", flush=True)
    base_result    = analyse_portfolio(positions, refresh=args.refresh,
                                       period=args.period)
    last_full_scan = time.time()
    print(" done.\n")

    # ── Main loop ────────────────────────────────────────────────
    iteration = 0
    while True:
        iteration += 1
        mkt = market_status()

        # Fetch live prices
        live_prices = fetch_live_prices(tickers)

        # Overlay live prices onto frozen CANSLIM snapshot
        snapshot = build_live_snapshot(base_result, live_prices)

        # Render dashboard
        print_dashboard(snapshot, mkt, datetime.now())

        # Footer: interval / next refresh info
        if not args.once:
            next_tick = args.interval
            if not mkt["open"]:
                next_tick = max(args.interval, 300)   # slow down outside hours
            print(f"  {_dim()}Refreshing every {next_tick}s  |  "
                  f"Press Ctrl+C to exit{_reset()}")

        if args.once:
            break

        # Re-run full CANSLIM every 4h to pick up cache updates
        if time.time() - last_full_scan > CACHE_REFRESH_INTERVAL:
            print(f"\n  {_dim()}Re-running full CANSLIM score (4h cache refresh)…{_reset()}",
                  end="", flush=True)
            base_result    = analyse_portfolio(positions, refresh=False,
                                               period=args.period)
            last_full_scan = time.time()
            print(" done.")

        time.sleep(next_tick)


def _dim()   -> str: return "\033[2m"
def _reset() -> str: return "\033[0m"


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Exiting live monitor.\n")
        sys.exit(0)
