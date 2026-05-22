"""
models/swing_trade.py
Swing trade entry/exit engine layered on top of the CANSLIM score.

Given price data and a CANSLIM composite score, computes:
  - Setup type (breakout / pullback / extended / early_base / handle / watch)
  - Entry zone (price, lo, hi)
  - Stop loss, Target 1, Target 2
  - Risk/reward ratio
  - Trailing stop
  - Exit warnings (climax top, ema breach)
  - Trade status (BUY / WATCH / AVOID)
"""

from __future__ import annotations
import numpy as np

# ── Trade constants ───────────────────────────────────────────
STOP_LOSS_PCT  = 0.075   # 7.5% initial stop below entry
TARGET_1_PCT   = 0.20    # +20% first target
TARGET_2_PCT   = 0.50    # +50% second target

TRAILING_LOOKBACK = 15   # days for trailing stop high
TRAILING_PCT      = 0.075

SCORE_FLOOR = 65.0       # below this → AVOID regardless of setup


# ── MAIN ENTRY POINT ─────────────────────────────────────────

def compute_swing_context(
    ticker: str,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    current_price: float,
    base_pivot: float | None,
    breakout_pct: float | None,
    composite_score: float,
    canslim_result: dict,
) -> dict:
    """
    Compute the full swing trade context for a ticker.
    Returns a dict with all entry/exit levels and trade status.
    """
    ctx = {
        "ticker":        ticker,
        "current_price": current_price,
        "entry_type":    None,
        "entry_price":   None,
        "entry_zone_lo": None,
        "entry_zone_hi": None,
        "stop_loss":     None,
        "target_1":      None,
        "target_2":      None,
        "risk_reward":   None,
        "trailing_stop": None,
        "exit_warning":  "none",
        "trade_status":  "AVOID",
        "setup_quality": "n/a",
        "notes":         [],
    }

    # Score gate
    if composite_score < SCORE_FLOOR:
        ctx["notes"].append(f"Score {composite_score:.1f} below threshold ({SCORE_FLOOR})")
        return ctx

    bk_pct = float(breakout_pct) if breakout_pct is not None else None

    # Compute EMAs and ATR
    ema10 = _ema(closes, 10)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    atr14 = _atr(highs, lows, closes, 14)

    # Classify setup
    setup = _classify_setup(
        closes=closes, highs=highs, lows=lows, volumes=volumes,
        price=current_price, pivot=base_pivot, bk_pct=bk_pct,
        ema10=ema10, ema21=ema21, ema50=ema50
    )

    ctx["entry_type"]    = setup["type"]
    ctx["setup_quality"] = setup.get("quality", "n/a")

    # Entry zone
    entry, zone_lo, zone_hi = _compute_entry_zone(
        setup=setup, price=current_price, pivot=base_pivot, bk_pct=bk_pct,
        ema10=ema10, ema21=ema21, ema50=ema50, atr14=atr14
    )
    ctx["entry_price"]   = entry
    ctx["entry_zone_lo"] = zone_lo
    ctx["entry_zone_hi"] = zone_hi

    if entry is not None:
        stop   = round(entry * (1 - STOP_LOSS_PCT), 2)
        t1     = round(entry * (1 + TARGET_1_PCT),  2)
        t2     = round(entry * (1 + TARGET_2_PCT),  2)
        risk   = entry - stop
        reward = t1 - entry
        rr     = round(reward / risk, 2) if risk > 0 else None

        ctx["stop_loss"]   = stop
        ctx["target_1"]    = t1
        ctx["target_2"]    = t2
        ctx["risk_reward"] = rr

    # Trailing stop (based on recent high)
    if len(closes) >= TRAILING_LOOKBACK:
        recent_hi = float(np.max(closes[-TRAILING_LOOKBACK:]))
        ctx["trailing_stop"] = round(recent_hi * (1 - TRAILING_PCT), 2)

    # Exit warnings
    ctx["exit_warning"] = _check_exit_warnings(
        closes=closes, highs=highs, lows=lows, volumes=volumes,
        current_price=current_price, ema10=ema10, bk_pct=bk_pct
    )

    # Trade status
    ctx["trade_status"] = _determine_status(
        composite_score=composite_score,
        setup_type=setup["type"],
        exit_warning=ctx["exit_warning"],
        bk_pct=bk_pct,
    )

    return ctx


# ── EMA / ATR ─────────────────────────────────────────────────

def _ema(prices: np.ndarray, period: int) -> np.ndarray | None:
    """Exponential moving average. Returns array same length as prices, or None."""
    if prices is None or len(prices) < period:
        return None
    k = 2 / (period + 1)
    out = np.zeros(len(prices))
    out[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        out[i] = prices[i] * k + out[i - 1] * (1 - k)
    # Zero out warm-up period
    out[:period - 1] = 0.0
    return out


def _atr(highs: np.ndarray, lows: np.ndarray,
         closes: np.ndarray, period: int = 14) -> float | None:
    """Average True Range."""
    if highs is None or len(highs) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            float(highs[i]) - float(lows[i]),
            abs(float(highs[i]) - float(closes[i - 1])),
            abs(float(lows[i])  - float(closes[i - 1])),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    return float(np.mean(trs[-period:]))


# ── SETUP CLASSIFICATION ──────────────────────────────────────

def _classify_setup(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray,
    price: float, pivot: float | None, bk_pct: float | None,
    ema10: np.ndarray | None, ema21: np.ndarray | None,
    ema50: np.ndarray | None,
) -> dict:
    """
    Classify the current price action into a setup type.

    Returns dict with 'type', 'support_level', 'quality' keys.
    """
    if pivot is None or bk_pct is None:
        return {"type": "watch", "support_level": None, "quality": "no_pivot"}

    bk = float(bk_pct)

    # Extended: stock has run too far above pivot and is far above EMAs
    if bk >= 40.0:
        if ema21 is not None:
            dist21 = (price - float(ema21[-1])) / float(ema21[-1])
            if dist21 > 0.02:
                return {"type": "extended", "support_level": float(ema21[-1]),
                        "quality": "too_extended"}

    # Near pivot — check if in base or handle
    if bk <= 5.0:
        if bk <= 2.0:
            return {"type": "early_base", "support_level": pivot, "quality": "ideal"}
        return {"type": "handle", "support_level": pivot * 0.97, "quality": "good"}

    # Breakout zone: just above pivot (2–8%)
    if 2.0 < bk <= 8.0:
        return {"type": "breakout", "support_level": pivot, "quality": "good"}

    # Healthy move: check for pullback to EMA support
    if ema21 is not None and len(closes) > 22:
        e21_val = float(ema21[-1])
        dist_to_ema = (price - e21_val) / e21_val
        if -0.02 <= dist_to_ema <= 0.03:
            return {"type": "pullback", "support_level": e21_val, "quality": "good"}

    if ema10 is not None:
        e10_val = float(ema10[-1])
        dist_to_ema10 = (price - e10_val) / e10_val
        if -0.01 <= dist_to_ema10 <= 0.02:
            return {"type": "pullback", "support_level": e10_val, "quality": "ok"}

    return {"type": "watch", "support_level": None, "quality": "no_clear_setup"}


# ── ENTRY ZONE ────────────────────────────────────────────────

def _compute_entry_zone(
    setup: dict, price: float,
    pivot: float | None, bk_pct: float | None,
    ema10: np.ndarray | None, ema21: np.ndarray | None,
    ema50: np.ndarray | None, atr14: float | None,
) -> tuple[float | None, float | None, float | None]:
    """
    Compute (entry_price, zone_lo, zone_hi) for the given setup.
    Returns (None, None, None) if no actionable entry.
    """
    stype = setup.get("type")
    atr   = atr14 or (price * 0.015)

    if stype == "extended":
        return None, None, None

    if stype == "watch":
        return None, None, None

    if stype in ("early_base", "handle", "breakout") and pivot is not None:
        entry   = round(pivot + 0.10, 2)
        zone_lo = round(pivot, 2)
        zone_hi = round(pivot * 1.05, 2)
        return entry, zone_lo, zone_hi

    if stype == "pullback":
        support = setup.get("support_level")
        if support is None:
            return None, None, None
        entry   = round(float(support) * 1.005, 2)
        zone_lo = round(float(support) * 0.99,  2)
        zone_hi = round(float(support) * 1.02,  2)
        return entry, zone_lo, zone_hi

    # Fallback: at-market entry
    entry   = round(price, 2)
    zone_lo = round(price * 0.99,  2)
    zone_hi = round(price * 1.02,  2)
    return entry, zone_lo, zone_hi


# ── EXIT WARNINGS ─────────────────────────────────────────────

def _check_exit_warnings(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray,
    current_price: float, ema10: np.ndarray | None,
    bk_pct: float | None,
) -> str:
    """
    Check for exit signals. Returns one of: 'climax_top', 'ema_breach', 'none'.
    """
    bk = float(bk_pct) if bk_pct is not None else 0.0

    # Climax top: extended + large weekly move
    if bk >= 40.0 and len(closes) >= 6:
        week_gain = (float(closes[-1]) / float(closes[-6]) - 1)
        if week_gain >= 0.10:
            return "climax_top"

    return "none"


# ── TRADE STATUS ──────────────────────────────────────────────

def _determine_status(
    composite_score: float, setup_type: str,
    exit_warning: str, bk_pct: float | None,
) -> str:
    """Determine overall trade status."""
    if composite_score < SCORE_FLOOR:
        return "AVOID"

    if exit_warning == "climax_top":
        return "TAKE_PROFIT"

    if setup_type == "extended":
        return "WATCH"

    if setup_type in ("early_base", "handle", "breakout", "pullback"):
        if composite_score >= 80:
            return "BUY"
        return "WATCH"

    return "WATCH"
