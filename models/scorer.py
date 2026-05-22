"""
models/scorer.py
Combines all sub-scores into a single CANSLIM composite score.

Formula (reverse-engineered from the Portfolio/Watchlist Audit):
  Score = C + A + N + S + L + I + M

  C  (0–25): Current quarterly EPS
  A  (0–20): Annual earnings CAGR + ROE
  N  (0–15): New catalyst / breakout quality
  S  (0–15): Supply/demand / volume
  L  (0–15): RS leadership rank
  I  (0– 5): Institutional ownership
  M  (0– 5): Market direction gate
  ─────────
     0–100   Total

The L score requires cross-sectional ranking across the full universe,
so it is updated in a second pass after all tickers are processed.
"""

from __future__ import annotations

# ── Point maximums (must sum to 100) ──────────────────────────
C_MAX  = 25
A_MAX  = 20
N_MAX  = 15
S_MAX  = 15
L_MAX  = 15
I_MAX  =  5
M_MAX  =  5

# Calibration constants from regression on 38-instrument audit
BREAKOUT_NORM   = 74.0   # normalizing denominator for breakout%
NS_COMBINED_MAX = 30.0   # max combined N+S pts

# ── Signal tiers (lo, hi, label) ──────────────────────────────
# Calibrated from audit data:
#   CRDO/CIEN (92/90) → elite
#   TSM/ASML  (88/86) → strong
#   PANW/LRCX (84/84) → buy
#   WDC/AMD   (80/80) → watch
#   BWXT/STLD (74/73) → monitor
#   ENPH      (65)    → weak/avoid
SCORE_TIERS = [
    (88, 101, "STRONG BUY"),
    (80,  88, "BUY"),
    (72,  80, "WATCH"),
    (65,  72, "MONITOR"),
    (  0, 65, "PASS"),
]


def build_composite_score(result: dict) -> float:
    """
    Compute the composite CANSLIM score from individual sub-scores.
    All sub-scores must already be in the result dict.
    """
    def _get(key, default):
        v = result.get(key)
        return float(default if v is None else v)

    c = _get("C_score", 0)
    a = _get("A_score", 0)
    n = _get("N_score", 0)
    s = _get("S_score", 0)
    l = _get("L_score", 7.5)   # default midpoint when not yet ranked
    i = _get("I_score", 3.0)   # default neutral
    m = _get("M_score", 4.0)   # default uptrend

    # Clamp each component to its max
    c = min(c, C_MAX)
    a = min(a, A_MAX)
    n = min(n, N_MAX)
    s = min(s, S_MAX)
    l = min(l, L_MAX)
    i = min(i, I_MAX)
    m = min(m, M_MAX)

    total = c + a + n + s + l + i + m
    return round(min(100.0, max(0.0, total)), 1)


def get_signal(score: float) -> str:
    """Map composite score to signal label."""
    for lo, hi, label in SCORE_TIERS:
        if lo <= score < hi:
            return label
    return "PASS"


def get_fundamental_base(result: dict) -> float:
    """
    Compute the fundamental base score (C + A + I).
    This is the 'floor' score independent of technical action.
    """
    c = float(result.get("C_score", 0) or 0)
    a = float(result.get("A_score", 0) or 0)
    i = float(result.get("I_score", 3.0) or 3.0)
    return round(c + a + i, 1)


def get_technical_overlay(result: dict) -> float:
    """
    Compute the technical overlay score (N + S + L + M).
    This is the 'upside' above the fundamental base.
    """
    n = float(result.get("N_score", 0) or 0)
    s = float(result.get("S_score", 0) or 0)
    l = float(result.get("L_score", 7.5) or 7.5)
    m = float(result.get("M_score", 4.0) or 4.0)
    return round(n + s + l + m, 1)


def score_summary(result: dict) -> str:
    """
    One-line human-readable summary of the score decomposition.
    """
    c  = result.get("C_score",    0)
    a  = result.get("A_score",    0)
    n  = result.get("N_score",    0)
    s  = result.get("S_score",    0)
    l  = result.get("L_score",  7.5)
    i  = result.get("I_score",  3.0)
    m  = result.get("M_score",  4.0)
    total  = build_composite_score(result)
    signal = get_signal(total)
    bk     = result.get("breakout_pct")
    bk_str = f"{bk:.0f}%" if bk is not None else "n/a"
    return (f"{result.get('ticker','?'):6s}  {total:5.1f}  [{signal:10s}]  "
            f"C={c:.1f} A={a:.1f} N={n:.1f} S={s:.1f} L={l:.1f} I={i:.1f} M={m:.1f}  "
            f"bk={bk_str}")
