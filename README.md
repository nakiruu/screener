# QQQ CANSLIM Scanner

A quantitative stock screener that scores every Nasdaq-100 (QQQ) constituent using a reverse-engineered [CANSLIM](https://en.wikipedia.org/wiki/CAN_SLIM) composite model. Produces ranked buy/watch/pass signals with full score decomposition, HTML dashboards, and CSV/JSON exports.

Also includes a **portfolio manager** that scores your existing holdings and recommends specific actions (ADD / HOLD / TRIM / SELL / STOP LOSS) per position — including option legs.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run a full QQQ scan (outputs HTML + JSON + CSV)
python run_scanner.py

# Show only the top 20 tickers
python run_scanner.py --top 20

# Deep-dive a single ticker
python run_scanner.py --ticker NVDA

# Analyse your portfolio
python run_portfolio.py --portfolio portfolio/sample_portfolio.json
```

## How It Works

### The CANSLIM Score (0–100)

Each ticker is scored across 7 criteria derived from William O'Neil's CANSLIM methodology, calibrated against a 38-instrument audit dataset:

```
Score = C + A + N + S + L + I + M

C  (0–25)  Current quarterly EPS growth
A  (0–20)  Annual earnings CAGR + ROE quality
N  (0–15)  New catalyst / near all-time-high (breakout quality)
S  (0–15)  Supply & demand / volume confirmation
L  (0–15)  Relative strength leadership rank (cross-sectional)
I  (0– 5)  Institutional ownership quality
M  (0– 5)  Market direction gate (XLK distribution days)
─────────
   0–100   Total
```

The N and S scores are jointly driven by **Breakout%** — how far the stock has moved above its base pivot:

```
N+S combined ≈ (breakout_pct / 74) × 30 pts
```

The L score requires a **cross-sectional ranking pass** across all scanned tickers (12-minus-1-month momentum percentile), so it's computed in a second pass after all individual tickers are scored.

### Signal Tiers

| Score     | Signal       | Meaning                          |
|-----------|-------------|----------------------------------|
| 88–100    | STRONG BUY  | Elite leader — ideal entry       |
| 80–87     | BUY         | Strong setup — watch for entry   |
| 72–79     | WATCH       | Solid — monitor for improvement  |
| 65–71     | MONITOR     | Neutral — no action              |
| < 65      | PASS        | Weak/avoid                       |

### Breakout% Tiers

| Breakout% | Interpretation                        |
|-----------|---------------------------------------|
| < 5%      | Still in base — ideal entry zone      |
| 5–19%     | Early / buyable                       |
| 20–39%    | Healthy move above pivot              |
| 40–59%    | Extended but still trending           |
| >= 60%    | Highly extended — climax top risk     |

### Market Gate (M Score)

The M criterion acts as a **gate** on the entire scan. It uses XLK (tech sector ETF) as the primary gauge:

- **Distribution day** = index down > 0.2% on higher volume than prior session
- <= 4 dist. days in 25 sessions + uptrend = **Confirmed uptrend** (4–5 pts, gate OPEN)
- 5–7 dist. days = **Under pressure** (2–3 pts, gate CLOSED)
- >= 8 dist. days or price below 50-day MA = **Downtrend** (0–1 pts, gate CLOSED)

When the gate is closed, every stock's composite score is suppressed, reflecting the O'Neil principle of avoiding new longs in a distribution market.

## Scanner Usage

```bash
python run_scanner.py [options]
```

| Flag             | Default | Description                                    |
|------------------|---------|------------------------------------------------|
| `--top N`        | all     | Show only top N results                        |
| `--min-score N`  | 0       | Filter by minimum composite score              |
| `--output FMT`   | all     | Output format: `html`, `json`, `csv`, `all`, `none` |
| `--refresh`      | off     | Bypass cache, re-fetch everything from yfinance |
| `--ticker SYM`   | —       | Single-ticker deep-dive mode                   |
| `--workers N`    | 6       | Number of parallel fetch threads               |
| `--period P`     | 6mo     | yfinance period for price history               |
| `--quiet`        | off     | Suppress per-ticker progress output            |

### Output Files

Each scan produces timestamped output in `output/`:

- `qqq_scan_YYYYMMDD_HHMMSS.json` — full results with metadata
- `qqq_scan_YYYYMMDD_HHMMSS.csv` — flat table for Excel/Sheets
- `qqq_scan_YYYYMMDD_HHMMSS.html` — interactive dark-themed dashboard

These files are gitignored — they're regenerated on every run.

### Example Output

```
  TOP 10 RESULTS:
  #   Ticker  Score  BK%    C    A    NS   L    I   M    Signal
  -----------------------------------------------------------------
    1 WDC       75.7 24%    25.0 17.5 12.2 15.0 3.0 3.0  WATCH
    2 STX       68.3 11%    25.0 17.5  5.8 14.0 3.0 3.0  MONITOR
    3 MU        66.7 4%     25.0 17.5  3.2 15.0 3.0 3.0  MONITOR
    4 ARM       66.1 3%     25.0 17.5  2.6 15.0 3.0 3.0  MONITOR
    5 LRCX      63.6 12%    19.0 18.0  6.6 14.0 3.0 3.0  PASS
```

## Portfolio Manager

Scores your existing holdings and produces actionable recommendations.

```bash
python run_portfolio.py --portfolio portfolio/sample_portfolio.json
python run_portfolio.py --portfolio portfolio/sample_portfolio.json --refresh
python run_portfolio.py --portfolio portfolio/sample_portfolio.json --output json
```

### Portfolio JSON Format

```json
{
  "positions": [
    {
      "ticker": "NVDA",
      "shares": 50,
      "cost_basis": 850.00,
      "options": [
        {
          "type": "call",
          "strike": 950.00,
          "contracts": 1,
          "expiry": "2026-06-20",
          "premium_paid": 45.00
        }
      ]
    },
    {
      "ticker": "MRVL",
      "shares": 200,
      "cost_basis": 72.50
    }
  ]
}
```

**Required fields per position:** `ticker`, `shares`, `cost_basis`

**Optional fields:** `options` (array of option legs), `date_opened`

**Option leg fields:** `type` (call/put), `strike`, `contracts`, `expiry` (YYYY-MM-DD), `premium_paid`

### Stock Action Ladder

The portfolio manager assigns one of these actions to each stock position:

| Action        | When                                                   | Urgency  |
|---------------|--------------------------------------------------------|----------|
| STOP LOSS     | Down >= 7.5% from cost basis (O'Neil hard stop)       | URGENT   |
| TRIM 50%      | Breakout% >= 60% (climax top risk)                    | HIGH     |
| ADD           | STRONG BUY or BUY within buy zone (< 8% above pivot)  | NORMAL   |
| HOLD          | Healthy position, good score                           | NORMAL   |
| HOLD + TRAIL  | Extended move on elite leader — tighten trailing stop  | NORMAL   |
| TRIM 25%      | Score slipping or moderate extension                   | ELEVATED |
| TRIM 75%      | PASS-rated but sitting on large gain (> +50%)          | HIGH     |
| SELL          | PASS or MONITOR on loser                               | HIGH     |

### Option Action Ladder

Each option leg gets its own recommendation:

| Action         | When                                                 |
|----------------|------------------------------------------------------|
| SELL TO CLOSE  | ITM with large gain, or OTM on weak stock            |
| EXERCISE       | Deep ITM call near expiry on strong stock            |
| ROLL           | ITM/ATM with < 21 days, still bullish                |
| HOLD           | ITM or bullish OTM with time remaining               |
| LET EXPIRE     | OTM near expiry, no recovery expected                |

## Architecture

```
run_scanner.py              Main scanner CLI (full QQQ scan)
run_portfolio.py            Portfolio manager CLI

scanners/
  qqq_holdings.py           Fetches QQQ constituents (yfinance → Wikipedia → hardcoded)
  fundamental.py            C + A + I scoring (EPS growth, CAGR, ROE, institutional)
  technical.py              N + S + L scoring (breakout%, volume, RS rank)
  market_gate.py            M scoring (XLK distribution days, trend, MA position)

models/
  scorer.py                 Combines sub-scores into composite; tier classification
  swing_trade.py            Swing trade entry/exit engine (setup classification,
                            entry zones, stops, targets, risk/reward)

output/
  report.py                 HTML dashboard builder
  export.py                 JSON / CSV export utilities

portfolio/
  manager.py                Portfolio analysis engine (action recommendations)
  sample_portfolio.json     Example portfolio file

tests/
  test_scorer.py            Scoring model unit tests (12 tests)
  test_portfolio.py         Portfolio action engine tests (27 tests)
  test_swing_trade.py       Swing trade engine tests (26 tests)
```

### Data Flow

```
                    ┌─────────────────────┐
                    │   QQQ Holdings      │
                    │  (101 tickers)      │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌───────────┐  ┌──────────┐  ┌───────────┐
        │Fundamental│  │Technical │  │Market Gate│
        │  C, A, I  │  │ N, S, L  │  │     M     │
        └─────┬─────┘  └────┬─────┘  └─────┬─────┘
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌─────────────────┐
                    │   Scorer        │
                    │  Composite 0–100│
                    └────────┬────────┘
                             │
                    ┌────────┼────────┐
                    ▼        ▼        ▼
                  JSON     CSV      HTML
```

### Scoring Pipeline Detail

1. **Fetch holdings** — QQQ constituents from yfinance, Wikipedia fallback, or hardcoded snapshot
2. **Market gate** — computed once, shared across all tickers
3. **Per-ticker scoring** — fundamentals (C, A, I) and technicals (N, S, raw momentum) fetched in parallel (6 threads default)
4. **RS ranking pass** — after all tickers are scored, raw momentum values are ranked cross-sectionally to produce L scores (percentile-based)
5. **Final composite** — all 7 sub-scores summed, clamped to [0, 100], mapped to signal tier
6. **Export** — sorted results written to JSON, CSV, and HTML

## Caching

All data is cached locally to avoid redundant API calls:

| Cache              | Location                     | TTL      | Purpose                    |
|--------------------|------------------------------|----------|----------------------------|
| Fundamental        | `data/fund_cache/{TICKER}.json` | 24 hours | EPS, CAGR, ROE, institutional |
| Technical          | `data/tech_cache/{TICKER}_6mo.json` | 4 hours | Price, volume, breakout%   |
| Market gate        | `data/market_gate_cache.json`   | 1 hour   | Distribution days, trend   |
| QQQ holdings       | `data/qqq_holdings_cache.json`  | 24 hours | Nasdaq-100 ticker list     |

Use `--refresh` to bypass all caches and re-fetch from yfinance.

All cache files are gitignored — they are ephemeral and regenerated on each run.

## Scoring Formulas (Detail)

### C — Current Quarterly EPS Growth (0–25 pts)

Primary source: `yfinance earningsQuarterlyGrowth` (trailing quarterly YoY).
Fallback: 3-month price return as proxy.

| EPS Growth   | Score |
|-------------|-------|
| >= 100%     | 25.0  |
| >= 75%      | 23.0  |
| >= 50%      | 21.0  |
| >= 35%      | 19.0  |
| >= 25%      | 17.0  |
| >= 15%      | 13.0  |
| >= 5%       | 8.0   |
| >= 0%       | 4.0   |
| >= -10%     | 2.0   |
| < -10%      | 0.0   |

O'Neil's minimum for CANSLIM candidates: **25% quarterly EPS growth** (17 pts).

### A — Annual Earnings CAGR + ROE (0–20 pts)

Two sub-components:

**CAGR sub-score (0–15 pts):** Sourced from `yfinance earningsGrowth` (trailing annual). Fallback: 1-year price return × 0.5.

**ROE sub-score (0–5 pts):** Sourced from `yfinance returnOnEquity`. O'Neil's threshold: 17% ROE minimum.

### I — Institutional Ownership (0–5 pts)

Sweet spot is 50–80% institutional ownership. Too low = no sponsorship. Too high = over-owned (big funds maxed out, limited upside buyers).

| Inst. Ownership | Score |
|----------------|-------|
| 50–80%         | 5.0   |
| 40–50%         | 4.0   |
| 80–90%         | 3.0   |
| 30–40%         | 2.5   |
| 90–100%        | 2.0   |
| 15–30%         | 1.5   |
| < 15%          | 1.0   |

### N+S — Breakout Quality + Volume (0–30 pts combined)

Driven primarily by **Breakout%** — how far the current price is above the detected base pivot:

```
combined = min(30, breakout_pct / 74 × 30)
N = combined × 0.50 + near-ATH bonus
S = combined × 0.50 + volume bonuses/penalties
```

**N bonuses:** Within 5% of 52-week high adds +1.5 pts; within 10% adds +0.75 pts.

**S bonuses/penalties:** Up/down volume ratio >= 1.5 adds +2.0 pts (accumulation). Volume surge >= 1.5× 20-day average adds +1.0 pts. U/D ratio < 0.9 subtracts -1.5 pts (distribution).

### L — Relative Strength Rank (0–15 pts)

Computed as a cross-sectional percentile rank of 12-minus-1-month momentum across all scanned tickers:

| RS Percentile | Score |
|--------------|-------|
| >= 95th      | 15.0  |
| >= 90th      | 14.0  |
| >= 85th      | 13.0  |
| >= 80th      | 11.5  |
| >= 75th      | 10.0  |
| >= 70th      | 8.5   |
| >= 60th      | 7.0   |
| >= 50th      | 5.5   |
| >= 40th      | 4.0   |
| >= 25th      | 2.5   |
| < 25th       | 1.0   |

O'Neil's minimum for CANSLIM candidates: **RS >= 80th percentile** (11.5 pts).

## Data Source

All data comes from [yfinance](https://github.com/ranaroussi/yfinance) (free, no API key needed). QQQ holdings are fetched from yfinance ETF data, with Wikipedia's Nasdaq-100 page as a fallback, and a hardcoded snapshot as a last resort.

Known limitation: yfinance periodically returns HTTP 401 ("Invalid Crumb") errors for some tickers due to Yahoo Finance rate limiting. These tickers are skipped and reported as errors. Re-running usually resolves it — the cache means previously successful fetches are reused.

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

65 tests across 3 test files covering the scoring model, portfolio action engine, and swing trade engine.

## Requirements

- Python 3.11+
- Dependencies: `yfinance`, `pandas`, `numpy`, `requests`, `beautifulsoup4`, `lxml`

```bash
pip install -r requirements.txt
```
