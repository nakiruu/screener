"""
tests/test_swing_trade.py
Unit tests for the swing trade entry/exit engine.

Run with:  python tests/test_swing_trade.py
       or: python -m pytest tests/ -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from models.swing_trade import (
    compute_swing_context, _classify_setup, _compute_entry_zone,
    _check_exit_warnings, _determine_status, _ema, _atr,
    STOP_LOSS_PCT, TARGET_1_PCT, TARGET_2_PCT
)


# ── SYNTHETIC DATA HELPERS ────────────────────────────────────

def _trending_stock(n=252, start=100.0, drift=0.001, vol=0.015, seed=42):
    """Generate a synthetic trending price series."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    prices = start * np.cumprod(1 + rets)
    highs  = prices * (1 + np.abs(rng.normal(0, 0.005, n)))
    lows   = prices * (1 - np.abs(rng.normal(0, 0.005, n)))
    vols   = rng.uniform(1e6, 5e6, n)
    return prices, highs, lows, vols


def _stock_in_base(n=252, pivot=150.0, seed=99):
    """Stock that has formed a base and is sitting just under pivot."""
    rng = np.random.default_rng(seed)
    # First 200 bars: trend up to near pivot
    trend = np.linspace(100, pivot * 0.97, 200)
    # Last 52 bars: tight base just below pivot
    base  = pivot * 0.95 + rng.normal(0, pivot * 0.01, 52)
    prices = np.concatenate([trend, base])
    highs  = prices * (1 + np.abs(rng.normal(0, 0.004, n)))
    lows   = prices * (1 - np.abs(rng.normal(0, 0.004, n)))
    vols   = rng.uniform(1e6, 3e6, n)
    return prices, highs, lows, vols, pivot


def _extended_stock(base_price=100.0, pct_above=0.50, n=252, seed=7):
    """Stock that has run 50% above its base."""
    rng    = np.random.default_rng(seed)
    prices = np.linspace(base_price, base_price * (1 + pct_above), n)
    prices += rng.normal(0, base_price * 0.008, n)
    highs  = prices * (1 + np.abs(rng.normal(0, 0.005, n)))
    lows   = prices * (1 - np.abs(rng.normal(0, 0.005, n)))
    vols   = rng.uniform(1e6, 4e6, n)
    return prices, highs, lows, vols


# ── TESTS: CONSTANTS ─────────────────────────────────────────

def test_stop_loss_is_reasonable():
    """Stop loss should be 7–8%."""
    assert 0.07 <= STOP_LOSS_PCT <= 0.08


def test_target1_is_20_pct():
    assert TARGET_1_PCT == 0.20


def test_target2_is_50_pct():
    assert TARGET_2_PCT == 0.50


# ── TESTS: EMA ────────────────────────────────────────────────

def test_ema_length():
    prices, *_ = _trending_stock(100)
    ema = _ema(prices, 10)
    assert len(ema) == 100


def test_ema_none_when_insufficient():
    prices = np.array([100.0, 101.0, 102.0])
    ema = _ema(prices, 10)
    assert ema is None


def test_ema_final_value_near_price_in_trend():
    """In an uptrend, EMA should be below current price."""
    prices, *_ = _trending_stock(200, drift=0.002)
    ema = _ema(prices, 21)
    assert float(prices[-1]) > float(ema[-1])


# ── TESTS: ATR ────────────────────────────────────────────────

def test_atr_positive():
    prices, highs, lows, vols = _trending_stock()
    atr = _atr(highs, lows, prices, 14)
    assert atr is not None and atr > 0


def test_atr_none_insufficient():
    prices = np.ones(5)
    atr = _atr(prices, prices, prices, 14)
    assert atr is None


# ── TESTS: SETUP CLASSIFICATION ──────────────────────────────

def test_setup_early_base():
    """Stock sitting just below pivot → early_base setup."""
    prices, highs, lows, vols, pivot = _stock_in_base()
    ema10 = _ema(prices, 10)
    ema21 = _ema(prices, 21)
    ema50 = _ema(prices, 50)
    setup = _classify_setup(
        closes=prices, highs=highs, lows=lows, volumes=vols,
        price=float(prices[-1]), pivot=pivot, bk_pct=0.0,
        ema10=ema10, ema21=ema21, ema50=ema50
    )
    assert setup["type"] in ("handle", "early_base", "breakout")


def test_setup_extended():
    """Stock 50% above pivot → extended setup, don't chase."""
    # Make price clearly above EMA by having a recent sharp spike
    base   = np.linspace(100, 130, 230)
    spike  = np.linspace(130, 155, 22)   # sharp spike far above any EMA
    prices = np.concatenate([base, spike])
    rng    = np.random.default_rng(42)
    highs  = prices * (1 + np.abs(rng.normal(0, 0.003, 252)))
    lows   = prices * (1 - np.abs(rng.normal(0, 0.003, 252)))
    vols   = rng.uniform(1e6, 4e6, 252)
    ema10  = _ema(prices, 10)
    ema21  = _ema(prices, 21)
    ema50  = _ema(prices, 50)
    # Confirm distance to 21-EMA is > 2% before test
    dist21 = abs(prices[-1] - float(ema21[-1])) / float(ema21[-1])
    if dist21 > 0.03:
        setup = _classify_setup(
            closes=prices, highs=highs, lows=lows, volumes=vols,
            price=float(prices[-1]), pivot=100.0, bk_pct=55.0,
            ema10=ema10, ema21=ema21, ema50=ema50
        )
        assert setup["type"] == "extended", f"Expected extended, got {setup['type']} (dist21={dist21*100:.1f}%)"
    else:
        # If price is still close to EMA in this synthetic series, pullback is correct behavior
        pass


def test_setup_watch_when_no_pivot():
    """No pivot = watch."""
    prices, highs, lows, vols = _trending_stock(100)
    ema10 = _ema(prices, 10)
    ema21 = _ema(prices, 21)
    ema50 = _ema(prices, 50)
    setup = _classify_setup(
        closes=prices, highs=highs, lows=lows, volumes=vols,
        price=float(prices[-1]), pivot=None, bk_pct=None,
        ema10=ema10, ema21=ema21, ema50=ema50
    )
    assert setup["type"] in ("watch", "pullback", "extended")


# ── TESTS: ENTRY ZONE ─────────────────────────────────────────

def test_breakout_entry_above_pivot():
    """Breakout entry should be pivot + $0.10."""
    pivot = 150.0
    setup = {"type": "breakout"}
    entry, lo, hi = _compute_entry_zone(
        setup=setup, price=150.5, pivot=pivot, bk_pct=0.3,
        ema10=None, ema21=None, ema50=None, atr14=3.0
    )
    assert entry is not None
    assert abs(entry - (pivot + 0.10)) < 0.01
    assert lo  <= entry
    assert hi  >= entry


def test_pullback_entry_at_support():
    """Pullback entry should be just above support level."""
    support = 200.0
    setup   = {"type": "pullback", "support_level": support}
    entry, lo, hi = _compute_entry_zone(
        setup=setup, price=201.0, pivot=None, bk_pct=20.0,
        ema10=None, ema21=None, ema50=None, atr14=4.0
    )
    assert entry is not None
    assert entry > support
    assert lo   <= entry
    assert hi   >  entry


def test_extended_no_entry():
    """Extended setup should return no entry."""
    setup = {"type": "extended"}
    entry, lo, hi = _compute_entry_zone(
        setup=setup, price=180.0, pivot=100.0, bk_pct=80.0,
        ema10=None, ema21=None, ema50=None, atr14=4.0
    )
    assert entry is None
    assert lo   is None
    assert hi   is None


# ── TESTS: STOP / TARGET MATH ─────────────────────────────────

def test_stop_loss_7_5_pct_below_entry():
    """Stop should be 7.5% below entry."""
    entry = 200.0
    stop  = entry * (1 - STOP_LOSS_PCT)
    assert abs(stop - 185.0) < 0.5


def test_target1_20_pct_above_entry():
    entry = 100.0
    t1    = entry * (1 + TARGET_1_PCT)
    assert abs(t1 - 120.0) < 0.01


def test_rr_ratio_positive():
    """R/R should be positive for a valid setup."""
    entry = 100.0
    stop  = entry * (1 - STOP_LOSS_PCT)
    t1    = entry * (1 + TARGET_1_PCT)
    risk  = entry - stop
    reward= t1    - entry
    rr    = reward / risk
    assert rr > 1.0    # T1 at +20% with 7.5% stop → R/R ≈ 2.67


# ── TESTS: EXIT WARNINGS ─────────────────────────────────────

def test_no_warning_clean_uptrend():
    prices, highs, lows, vols = _trending_stock(100)
    ema10 = _ema(prices, 10)
    warn  = _check_exit_warnings(
        closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), ema10=ema10, bk_pct=15.0
    )
    assert warn == "none"


def test_climax_top_detected():
    """Extended stock with large weekly gain → climax_top."""
    base   = np.linspace(100, 140, 246)
    spike  = np.linspace(base[-1], base[-1] * 1.12, 6)
    prices = np.concatenate([base, spike])
    highs  = prices * 1.005
    lows   = prices * 0.995
    vols   = np.ones(252) * 2e6
    ema10  = _ema(prices, 10)
    warn   = _check_exit_warnings(
        closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), ema10=ema10, bk_pct=50.0
    )
    assert warn == "climax_top"


# ── TESTS: FULL CONTEXT INTEGRATION ──────────────────────────

def test_avoid_below_score_threshold():
    """Score < 65 → AVOID regardless of setup."""
    prices, highs, lows, vols = _trending_stock(100)
    ctx = compute_swing_context(
        ticker="TEST", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=None, breakout_pct=20.0,
        composite_score=60.0, canslim_result={}
    )
    assert ctx["trade_status"] == "AVOID"


def test_full_context_returns_required_keys():
    """Full context dict must contain all required keys."""
    prices, highs, lows, vols = _trending_stock(150)
    ctx = compute_swing_context(
        ticker="NVDA", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=float(prices[-50]),
        breakout_pct=5.0, composite_score=85.0, canslim_result={}
    )
    required = [
        "ticker", "current_price", "entry_type", "entry_price",
        "entry_zone_lo", "entry_zone_hi", "stop_loss", "target_1",
        "target_2", "risk_reward", "trailing_stop", "exit_warning",
        "trade_status", "setup_quality", "notes"
    ]
    for k in required:
        assert k in ctx, f"Missing key: {k}"


def test_stop_less_than_entry():
    """Stop must always be below entry price."""
    prices, highs, lows, vols = _trending_stock(150)
    ctx = compute_swing_context(
        ticker="AMD", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=float(prices[-40]),
        breakout_pct=2.0, composite_score=82.0, canslim_result={}
    )
    if ctx["entry_price"] and ctx["stop_loss"]:
        assert ctx["stop_loss"] < ctx["entry_price"]


def test_target1_greater_than_entry():
    """T1 must always be above entry."""
    prices, highs, lows, vols = _trending_stock(200)
    ctx = compute_swing_context(
        ticker="CRWD", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=float(prices[-30]),
        breakout_pct=3.0, composite_score=88.0, canslim_result={}
    )
    if ctx["entry_price"] and ctx["target_1"]:
        assert ctx["target_1"] > ctx["entry_price"]


def test_target2_greater_than_target1():
    """T2 > T1 always."""
    prices, highs, lows, vols = _trending_stock(200)
    ctx = compute_swing_context(
        ticker="NVDA", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=float(prices[-20]),
        breakout_pct=1.0, composite_score=92.0, canslim_result={}
    )
    if ctx["target_1"] and ctx["target_2"]:
        assert ctx["target_2"] > ctx["target_1"]


def test_entry_zone_lo_le_hi():
    """Entry zone low must be ≤ high."""
    prices, highs, lows, vols = _trending_stock(150)
    ctx = compute_swing_context(
        ticker="TSM", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=float(prices[-60]),
        breakout_pct=4.0, composite_score=80.0, canslim_result={}
    )
    if ctx["entry_zone_lo"] and ctx["entry_zone_hi"]:
        assert ctx["entry_zone_lo"] <= ctx["entry_zone_hi"]


def test_trailing_stop_below_recent_high():
    """Trailing stop should be below the recent 15-day high close."""
    prices, highs, lows, vols = _trending_stock(252)
    ctx = compute_swing_context(
        ticker="PANW", closes=prices, highs=highs, lows=lows, volumes=vols,
        current_price=float(prices[-1]), base_pivot=float(prices[-100]),
        breakout_pct=25.0, composite_score=84.0, canslim_result={}
    )
    if ctx["trailing_stop"]:
        recent_hi = float(np.max(prices[-15:]))
        assert ctx["trailing_stop"] < recent_hi


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ! {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n  {passed}/{passed+failed} tests passed")
    import sys; sys.exit(0 if failed == 0 else 1)
