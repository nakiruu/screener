#!/usr/bin/env python3
"""
build_cache_from_mcp.py
Writes fund_cache entries from raw MCP API data dicts.

Usage: called by Claude after fetching MCP data.
  python build_cache_from_mcp.py <json_file>

The JSON file is a list of:
  {
    "ticker": "NVDA",
    "q_growth": { <income-statement-growth quarterly response[0]> },
    "a_growth": { <income-statement-growth annual response[0]> },
    "metrics":  { <key-metrics-ttm response[0]> },
    "profile":  { <company profile-symbol response[0]> }   # optional
  }
"""

import json
import sys
import time
from pathlib import Path

CACHE_DIR = Path("data/fund_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

C_MAX, A_MAX, I_MAX = 25, 20, 5


def score_eps_growth(g):
    if g is None: return 0.0
    g = float(g)
    if g >= 1.00: return 25.0
    if g >= 0.75: return 23.0
    if g >= 0.50: return 21.0
    if g >= 0.35: return 19.0
    if g >= 0.25: return 17.0
    if g >= 0.15: return 13.0
    if g >= 0.05: return  8.0
    if g >= 0.00: return  4.0
    if g >= -0.10: return 2.0
    return 0.0


def score_annual(cagr, roe):
    cagr = float(cagr or 0)
    if cagr >= 0.50: cagr_pts = 15.0
    elif cagr >= 0.35: cagr_pts = 13.0
    elif cagr >= 0.25: cagr_pts = 11.0
    elif cagr >= 0.15: cagr_pts = 8.0
    elif cagr >= 0.05: cagr_pts = 5.0
    elif cagr >= 0.00: cagr_pts = 2.0
    else: cagr_pts = 0.0

    if roe is None:
        roe_pts = 2.5
    else:
        r = float(roe)
        if r >= 0.40: roe_pts = 5.0
        elif r >= 0.25: roe_pts = 4.0
        elif r >= 0.17: roe_pts = 3.0
        elif r >= 0.10: roe_pts = 2.0
        elif r >= 0.00: roe_pts = 1.0
        else: roe_pts = 0.0
    return round(min(A_MAX, cagr_pts + roe_pts), 2)


def score_institutional(inst):
    if inst is None: return 3.0
    i = float(inst)
    if 0.50 <= i <= 0.80: return 5.0
    if 0.40 <= i < 0.50:  return 4.0
    if 0.80 < i <= 0.90:  return 3.0
    if 0.30 <= i < 0.40:  return 2.5
    if 0.90 < i <= 1.00:  return 2.0
    if 0.15 <= i < 0.30:  return 1.5
    return 1.0


def build_entry(ticker, q_growth, a_growth, metrics, profile=None):
    q  = q_growth or {}
    a  = a_growth or {}
    m  = metrics  or {}
    p  = profile  or {}

    eps_growth_q = q.get("growthEPS") or q.get("growthNetIncome")
    eps_cagr_a   = a.get("growthEPS") or a.get("growthNetIncome")
    roe          = m.get("returnOnEquityTTM")
    inst_pct     = None   # FMP free tier doesn't provide institutional %

    c_score = score_eps_growth(eps_growth_q)
    a_score = score_annual(eps_cagr_a, roe)
    i_score = score_institutional(inst_pct)

    entry = {
        "_cached_at": time.time(),
        "ticker":     ticker,
        "C_score":    c_score,
        "A_score":    a_score,
        "I_score":    i_score,
        "eps_growth": float(eps_growth_q) if eps_growth_q is not None else None,
        "eps_cagr":   float(eps_cagr_a)   if eps_cagr_a   is not None else None,
        "roe":        float(roe)           if roe          is not None else None,
        "inst_pct":   None,
        "price":      p.get("price"),
        "sector":     p.get("sector",   "Unknown"),
        "industry":   p.get("industry", "Unknown"),
        "method":     "fmp_mcp",
        "M_score":    4.0,
    }
    return entry


def process_file(path):
    data = json.loads(Path(path).read_text())
    count = 0
    for item in data:
        ticker = item["ticker"]
        entry = build_entry(
            ticker,
            item.get("q_growth"),
            item.get("a_growth"),
            item.get("metrics"),
            item.get("profile"),
        )
        out = CACHE_DIR / f"{ticker}.json"
        out.write_text(json.dumps(entry, indent=2))
        print(f"  {ticker:6s}  C={entry['C_score']:5.1f}  A={entry['A_score']:5.1f}  "
              f"EPS_q={entry['eps_growth'] and f\"{entry['eps_growth']*100:.0f}%\" or 'n/a':6s}  "
              f"CAGR={entry['eps_cagr'] and f\"{entry['eps_cagr']*100:.0f}%\" or 'n/a':6s}  "
              f"ROE={entry['roe'] and f\"{entry['roe']*100:.0f}%\" or 'n/a'}")
        count += 1
    print(f"\n  Wrote {count} cache entries.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python build_cache_from_mcp.py <data.json>")
        sys.exit(1)
    process_file(sys.argv[1])
