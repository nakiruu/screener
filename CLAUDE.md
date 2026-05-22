# CLAUDE.md — QQQ CANSLIM Scanner

## Project Overview
This project scans every stock in the QQQ ETF (Nasdaq-100) and scores each one
using the reverse-engineered CANSLIM model from the Portfolio/Watchlist Audit.

## Reverse-Engineered Scoring Formula
```
CANSLIM Score = FundamentalBase(C+A+I) + TechnicalBoost(N+S) + Leadership(L) + MarketGate(M)
```

Point allocations:
- C (Current quarterly EPS)   : 0–25 pts
- A (Annual EPS CAGR + ROE)   : 0–20 pts
- N (New catalyst / near ATH) : 0–15 pts  ← driven by breakout%
- S (Supply/demand / volume)  : 0–15 pts  ← driven by breakout%
- L (RS leadership rank)      : 0–15 pts
- I (Institutional ownership) : 0–5  pts
- M (Market direction gate)   : 0–5  pts
Total max: 100

N+S combined ≈ (breakout_pct / 74) × 30 pts
Breakout% = (current_price − base_pivot) / base_pivot × 100

## Project Entry Point
```bash
python run_scanner.py                  # Full QQQ scan, HTML + JSON output
python run_scanner.py --top 20         # Show only top 20
python run_scanner.py --min-score 75   # Filter by minimum score
python run_scanner.py --output json    # JSON only
python run_scanner.py --refresh        # Force re-fetch all data (ignore cache)
python run_scanner.py --ticker NVDA    # Single ticker deep dive
```

## Architecture
```
run_scanner.py           Main orchestrator
scanners/
  qqq_holdings.py        Fetches current QQQ holdings from Wikipedia/yfinance
  fundamental.py         C + A + I criteria (yfinance earnings/ROE/institutional)
  technical.py           N + S + L + M criteria (price, volume, breakout, RS)
  market_gate.py         M criterion: XLK distribution days, trend
models/
  scorer.py              Combines all sub-scores into final CANSLIM score
  breakout.py            Base pivot detection and breakout% calculation
  relative_strength.py   RS rating computation (cross-sectional rank)
data/
  cache.py               Simple JSON file cache (TTL=4hrs for prices, 24hrs for fundamentals)
output/
  report.py              HTML dashboard builder
  export.py              JSON/CSV export
tests/
  test_scorer.py         Unit tests for the scoring model
```

## Key Parameters (tunable)
All in `models/scorer.py`:
- `BREAKOUT_MAX_PCT = 74`     — denominator for N+S normalization (from regression)
- `NS_MAX_PTS = 30`           — max combined N+S points
- `L_MAX_PTS = 15`            — max leadership points
- `C_MAX_PTS = 25`            — max current earnings points
- `A_MAX_PTS = 20`            — max annual earnings points
- `I_MAX_PTS = 5`             — max institutional points
- `M_MAX_PTS = 5`             — max market gate points
- `CACHE_TTL_PRICE = 14400`   — price cache TTL in seconds (4 hrs)
- `CACHE_TTL_FUND = 86400`    — fundamental cache TTL in seconds (24 hrs)

## Score Tier Interpretation
- 88–100: Elite leader         → STRONG BUY candidate
- 80–87:  Strong               → BUY / watch closely
- 72–79:  Solid                → WATCH
- 65–71:  Neutral              → monitor only
- <65:    Weak/avoid           → PASS

## Breakout% Tiers
- ≥60%:    Highly extended — risk of climax top
- 40–59%:  Extended but still trending
- 20–39%:  Healthy move
- 5–19%:   Early / buyable
- <5%:     Still in base — ideal entry zone

## Data Notes
- yfinance is the primary data source (free, no API key)
- QQQ holdings fetched from Wikipedia Nasdaq-100 page or via yfinance ETF info
- Fundamental data (EPS, ROE, institutional) has 24hr cache
- Price/volume data has 4hr cache
- All models handle missing data gracefully with fallbacks and explicit logging

## Running in Claude Code
Open this folder and interact naturally:
- "Run the scanner and show me everything above 80"
- "Why is NVDA scoring lower than CRDO?"
- "Add a sector-neutralized RS calculation"
- "Export results to CSV for Excel"
- "Show me the base chart for AXON"
- "Re-run with a 90-day breakout window instead of 52-week"
