"""
models/relative_strength.py
RS (Relative Strength) rating computation — cross-sectional rank within QQQ universe.

Methodology:
  - 12-1 month momentum: return over past 12 months minus last 1 month
    (skips the most recent month to avoid mean-reversion bias — standard IBD approach)
  - Cross-sectional percentile rank within the QQQ universe
  - RS percentile → L score (0–15 pts)

Score mapping (O'Neil threshold: RS ≥ 80 = minimum for CANSLIM leaders):
  95–100 pct → 15 pts  (elite)
  90–94  pct → 14 pts
  85–89  pct → 13 pts
  80–84  pct → 11.5 pts  (O'Neil minimum)
  75–79  pct → 10 pts
  70–74  pct → 8.5 pts
  60–69  pct → 7 pts
  50–59  pct → 5.5 pts
  40–49  pct → 4 pts
  25–39  pct → 2.5 pts
  <25    pct → 1 pt
"""

from __future__ import annotations
import numpy as np


L_MAX = 15.0


def compute_momentum(closes: np.ndarray) -> float:
    """
    12-1 month momentum: annualized return minus last-month return.
    Standard cross-sectional momentum factor (Jegadeesh & Titman style).
    """
    if len(closes) >= 252:
        r12 = (closes[-1] / closes[0]) - 1
        r1  = (closes[-1] / closes[-22]) - 1
        return float(r12 - r1)
    if len(closes) > 22:
        return float((closes[-1] / closes[0]) - 1)
    return 0.0


def assign_rs_scores(results: list[dict]) -> list[dict]:
    """
    Cross-sectional RS ranking pass: assigns rs_pct and L_score to each
    result dict based on relative momentum within the universe.

    Expects each result dict to have a '_mom_raw' key (set by score_technical).
    Modifies results in place and returns the list.
    """
    valid = [(i, r) for i, r in enumerate(results) if not r.get("error")]
    if not valid:
        return results

    all_moms = [r.get("_mom_raw", 0.0) for _, r in valid]

    for _, r in valid:
        mom   = r.get("_mom_raw", 0.0)
        pct   = sum(1 for v in all_moms if v <= mom) / len(all_moms) * 100
        r["rs_pct"]  = round(float(pct), 1)
        r["L_score"] = score_l_from_pct(pct)

    return results


def score_l_from_pct(pct: float) -> float:
    """Map RS percentile (0–100) → L score (0–15 pts)."""
    if pct >= 95:   return 15.0
    if pct >= 90:   return 14.0
    if pct >= 85:   return 13.0
    if pct >= 80:   return 11.5
    if pct >= 75:   return 10.0
    if pct >= 70:   return  8.5
    if pct >= 60:   return  7.0
    if pct >= 50:   return  5.5
    if pct >= 40:   return  4.0
    if pct >= 25:   return  2.5
    return 1.0
