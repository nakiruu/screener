"""
models/swing_trade.py
Swing trade entry/exit engine for CANSLIM-qualified stocks.

Given a CANSLIM-scored result, computes:
  - Setup classification (breakout, pullback, extended, watch, etc.)
  - Entry zone (price, lo, hi)
  - Stop loss (7.5% below entry — O'Neil's 7–8% rule)
  - Targets (T1 = +20%, T2 = +50%)
  - Trailing stop (3-week high × 92.5%)
  - Exit warnings (climax top, below key MA, etc.)
  - Trade status (ACTIVE / WATCH / AVOID)
"""

from __future__ import annotations

import numpy as np

# ── Constants ─────────────────────────────────────────────────
STOP_LOSS_PCT  = 0.075   # 7.5% hard stop (O'Neil rule)
TARGET_1_PCT   = 0.20    # first target: +20%
TARGET_2_PCT   = 0.50    # second target: +50%
MIN_SCORE      = 65.0    # below this → AVOID regardless of setup

# ── EMA / ATR helpers ─────────────────────────────────────────

def _ema(prices: np.ndarray, period: int) -> np.ndarray | None:
    """Exponential moving average. Returns None if insufficient data."""
    if prices is None or len(prices) < period:
        return None
    k   = 2.0 / (period + 1)
    out = np.zeros(len(prices))
    out[period - 1] = float(np.mean(prices[:period]))
    for i in range(period, len(prices)):
        out[i] = float(prices[i]) * k + out[i - 1] * (1 - k)
    return out


def _atr(highs: np.ndarray, lows: np.ndarray,
         closes: np.ndarray, period: int = 14) -> float | None:
    """Average True Range. Returns None if insufficient data."""
    if (highs is None or lows is None or closes is None
            or len(closes) < period + 1):
        return None
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:]   - closes[:-1]),
            np.abs(lows[1:]    - closes[:-1]),
        ),
    )
    if len(tr) < period:
        return None
    return float(np.mean(tr[-period:]))


# ── Setup classification ───────────────────────────────────────

def _classify_setup(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    price: float,
    pivot: float | None,
    bk_pct: float | None,
    ema10: np.ndarray | None,
    ema21: np.ndarray | None,
    ema50: np.ndarray | None,
) -> dict:
    """
    Classify the current price action into a trade setup type.

    Returns dict with keys:
      type: "breakout" | "handle" | "early_base" | "pullback"
            | "extended" | "watch"
      support_level: float | None
      note: str
    """
    e10 = float(ema10[-1]) if ema10 is not None else None
    e21 = float(ema21[-1]) if ema21 is not None else None
    e50 = float(ema50[-1]) if ema50 is not None else None

    # No pivot → can't classify a base setup
    if pivot is None or bk_pct is None:
        if e21 is not None and price < e21 * 1.02:
            return {"type": "pullback", "support_level": e21, "note": "below pivot; near 21-EMA"}
        return {"type": "watch", "support_level": None, "note": "no base pivot detected"}

    bk = float(bk_pct)

    # Extended: too far above pivot; check if also far from EMA
    if bk >= 40.0:
        if e21 is not None:
            dist21 = (price - e21) / e21
            if dist21 > 0.02:
                return {"type": "extended", "support_level": e21,
                        "note": f"{bk:.0f}% above pivot, {dist21*100:.1f}% above 21-EMA — don't chase"}
        return {"type": "extended", "support_level": e21,
                "note": f"{bk:.0f}% above pivot — extended"}

    # Near pivot (in base or just breaking out)
    if bk <= 2.0:
        # Tight handle: price within 2% below pivot with recent tight action
        if len(closes) >= 10:
            tightness = float(np.std(closes[-10:]) / np.mean(closes[-10:]))
            if tightness < 0.02:
                return {"type": "handle", "support_level": pivot * 0.95,
                        "note": f"tight handle below pivot (bk={bk:.1f}%, tightness={tightness*100:.1f}%)"}
        return {"type": "early_base", "support_level": pivot * 0.92,
                "note": f"still in base — ideal entry zone (bk={bk:.1f}%)"}

    if bk <= 5.0:
        return {"type": "breakout", "support_level": pivot,
                "note": f"near pivot breakout (bk={bk:.1f}%)"}

    # Moderate extension — look for pullback to key support
    if e21 is not None and price <= e21 * 1.03:
        return {"type": "pullback", "support_level": e21,
                "note": f"pulling back to 21-EMA (bk={bk:.0f}%)"}
    if e10 is not None and price <= e10 * 1.03:
        return {"type": "pullback", "support_level": e10,
                "note": f"pulling back to 10-EMA (bk={bk:.0f}%)"}

    # Healthy move — at market
    return {"type": "breakout", "support_level": pivot,
            "note": f"{bk:.0f}% above pivot — healthy move"}


# ── Entry zone ────────────────────────────────────────────────

def _compute_entry_zone(
    setup: dict,
    price: float,
    pivot: float | None,
    bk_pct: float | None,
    ema10: np.ndarray | None,
    ema21: np.ndarray | None,
    ema50: np.ndarray | None,
    atr14: float | None,
) -> tuple[float | None, float | None, float | None]:
    """
    Compute (entry_price, zone_lo, zone_hi).
    Returns (None, None, None) for setups where entry is not advised.
    """
    stype   = setup.get("type", "watch")
    support = setup.get("support_level")

    e21 = float(ema21[-1]) if ema21 is not None else None

    if stype == "extended":
        return None, None, None

    if stype in ("breakout", "handle", "early_base") and pivot is not None:
        entry   = round(pivot + 0.10, 2)
        zone_lo = round(pivot, 2)
        zone_hi = round(pivot * 1.05, 2)
        return entry, zone_lo, zone_hi

    if stype == "pullback" and support is not None:
        entry   = round(support * 1.005, 2)
        zone_lo = round(support * 0.99,  2)
        zone_hi = round(support * 1.02,  2)
        return entry, zone_lo, zone_hi

    if stype == "watch":
        return None, None, None

    # Default: at market with ±1% zone
    entry   = round(price, 2)
    zone_lo = round(price * 0.99, 2)
    zone_hi = round(price * 1.01, 2)
    return entry, zone_lo, zone_hi


# ── Exit warnings ──────────────────────────────────────────────

def _check_exit_warnings(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    current_price: float,
    ema10: np.ndarray | None,
    bk_pct: float | None,
) -> str:
    """
    Detect exit warning signals. Returns one of:
      "none" | "climax_top" | "below_10ema" | "distribution" | "stalling"
    """
    bk = float(bk_pct) if bk_pct is not None else 0.0

    # Climax top: stock is extended AND had a large weekly gain (≥10% in 5–6 bars)
    if bk >= 40.0 and len(closes) >= 10:
        week_gain = (closes[-1] / closes[-6] - 1) if len(closes) >= 6 else 0.0
        if week_gain >= 0.10:
            return "climax_top"

    # Below 10-EMA for 2+ consecutive days — only relevant for extended stocks
    # (early/healthy moves use EMA21/50 as the stop discipline instead)
    if bk >= 30.0 and ema10 is not None and len(closes) >= 3 and len(ema10) >= 3:
        if (closes[-1] < ema10[-1] * 0.995
                and closes[-2] < ema10[-2] * 0.995):
            return "below_10ema"

    # Distribution: heavy volume on a down day in extended stock
    if (bk >= 20.0 and volumes is not None and len(closes) >= 2
            and closes[-1] < closes[-2]):
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))
        if volumes[-1] > avg_vol * 1.5:
            return "distribution"

    return "none"


# ── Trade status ───────────────────────────────────────────────

def _determine_status(
    composite_score: float,
    setup_type: str,
    exit_warning: str,
    entry_price: float | None,
) -> str:
    """Determine trade status: ACTIVE | WATCH | AVOID."""
    if composite_score < MIN_SCORE:
        return "AVOID"
    if exit_warning == "climax_top":
        return "AVOID"
    if setup_type == "extended":
        return "WATCH"
    if entry_price is not None:
        return "ACTIVE"
    return "WATCH"


# ── Main context builder ───────────────────────────────────────

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
    Compute full swing trade context for a CANSLIM-scored ticker.

    Returns a dict with all entry/exit parameters and supporting metadata.
    """
    ctx: dict = {
        "ticker":        ticker,
        "current_price": round(current_price, 2),
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
        "trade_status":  "WATCH",
        "setup_quality": "unknown",
        "notes":         [],
    }

    if composite_score < MIN_SCORE:
        ctx["trade_status"] = "AVOID"
        ctx["notes"].append(f"Score {composite_score:.1f} < {MIN_SCORE} threshold")
        return ctx

    # ── EMAs ──────────────────────────────────────────────────
    ema10 = _ema(closes, 10)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    atr14 = _atr(highs, lows, closes, 14)

    # ── Setup classification ───────────────────────────────────
    setup = _classify_setup(
        closes=closes, highs=highs, lows=lows, volumes=volumes,
        price=current_price, pivot=base_pivot, bk_pct=breakout_pct,
        ema10=ema10, ema21=ema21, ema50=ema50,
    )
    stype = setup["type"]
    ctx["entry_type"]    = stype
    ctx["setup_quality"] = stype
    if setup.get("note"):
        ctx["notes"].append(setup["note"])

    # ── Entry zone ─────────────────────────────────────────────
    entry, zone_lo, zone_hi = _compute_entry_zone(
        setup=setup, price=current_price, pivot=base_pivot,
        bk_pct=breakout_pct, ema10=ema10, ema21=ema21, ema50=ema50,
        atr14=atr14,
    )
    ctx["entry_price"]   = entry
    ctx["entry_zone_lo"] = zone_lo
    ctx["entry_zone_hi"] = zone_hi

    # ── Stop / targets (only when entry is defined) ────────────
    if entry is not None:
        stop  = round(entry * (1 - STOP_LOSS_PCT), 2)
        t1    = round(entry * (1 + TARGET_1_PCT), 2)
        t2    = round(entry * (1 + TARGET_2_PCT), 2)
        risk  = entry - stop
        reward = t1 - entry
        rr     = round(reward / risk, 2) if risk > 0 else None

        ctx["stop_loss"]   = stop
        ctx["target_1"]    = t1
        ctx["target_2"]    = t2
        ctx["risk_reward"] = rr

    # ── Trailing stop (3-week high × 92.5%) ───────────────────
    if len(closes) >= 15:
        hi3wk = float(np.max(closes[-15:]))
        ctx["trailing_stop"] = round(hi3wk * (1 - STOP_LOSS_PCT), 2)

    # ── Exit warnings ──────────────────────────────────────────
    ctx["exit_warning"] = _check_exit_warnings(
        closes=closes, highs=highs, lows=lows, volumes=volumes,
        current_price=current_price, ema10=ema10, bk_pct=breakout_pct,
    )

    # ── Trade status ───────────────────────────────────────────
    ctx["trade_status"] = _determine_status(
        composite_score=composite_score,
        setup_type=stype,
        exit_warning=ctx["exit_warning"],
        entry_price=entry,
    )

    return ctx
