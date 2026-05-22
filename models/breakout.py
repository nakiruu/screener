"""
models/breakout.py
Base pivot detection and breakout% calculation.

Algorithm:
  1. Find the lowest 20-day low in the trailing 6 months (base bottom)
  2. Find the highest high in the right side of the base (cup pivot)
  3. Breakout% = (current_price − pivot) / pivot × 100

Breakout% tiers (from CLAUDE.md):
  ≥60%:  Highly extended — risk of climax top
  40–59%: Extended but still trending
  20–39%: Healthy move
  5–19%:  Early / buyable
  <5%:    Still in base — ideal entry zone
"""

from __future__ import annotations
import numpy as np


BREAKOUT_MAX_PCT = 74.0   # empirical ceiling from regression (CLAUDE.md)


def detect_base_pivot(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int = 126,
) -> tuple[float | None, float | None]:
    """
    Detect the most recent price base pivot and compute breakout%.

    Returns (pivot_price, breakout_pct) or (None, None) if insufficient data.
    """
    n = len(closes)
    if n < 40:
        return None, None

    current = float(closes[-1])
    lookback = min(lookback, n - 1)
    window   = closes[-(lookback + 1):-1]   # exclude current bar

    # Base bottom: lowest close in lookback window
    base_idx = int(np.argmin(window))

    # Pivot: highest high on the right side of the base
    right_start = base_idx
    right_end   = len(window) - 10
    if right_end <= right_start:
        right_end = len(window)

    hi_slice = highs[-(lookback + 1) + right_start : -(10) if right_end < len(window) - 1 else None]
    if len(hi_slice) < 3:
        # Fallback: 52-week high
        pivot = float(np.max(closes[-252:])) if n >= 252 else float(np.max(closes))
        bk    = max(0.0, (current / pivot - 1) * 100)
        return pivot, bk

    pivot = float(np.max(hi_slice))
    bk    = max(0.0, (current / max(pivot, 1e-6) - 1) * 100)
    return pivot, bk


def breakout_tier(bk_pct: float | None) -> str:
    """Classify breakout% into a descriptive tier label."""
    if bk_pct is None:
        return "unknown"
    if bk_pct >= 60:
        return "highly_extended"
    if bk_pct >= 40:
        return "extended"
    if bk_pct >= 20:
        return "healthy"
    if bk_pct >= 5:
        return "early_buyable"
    return "in_base"


def ns_from_breakout(bk_pct: float | None,
                     ns_max: float = 30.0,
                     norm: float = BREAKOUT_MAX_PCT) -> tuple[float, float]:
    """
    Convert breakout% to combined N+S score, split equally.
    Returns (N_pts, S_pts).
    """
    if bk_pct is None:
        bk_pct = 0.0
    combined = min((float(bk_pct) / norm) * ns_max, ns_max)
    half = combined * 0.5
    return half, half
