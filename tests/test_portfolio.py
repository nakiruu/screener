"""
tests/test_portfolio.py
Unit tests for the portfolio action engine (no network calls).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio.manager import (
    _stock_action, _analyse_option,
    STOP_PCT, TARGET_1, TARGET_2,
)


# ── STOCK ACTION TESTS ────────────────────────────────────────

def test_stop_loss_overrides_signal():
    action, _, urgency = _stock_action(90, "STRONG BUY", bk_pct=5, pnl_pct=-0.076)
    assert action == "STOP LOSS"
    assert urgency == "URGENT"


def test_stop_loss_at_exact_threshold():
    action, _, _ = _stock_action(85, "BUY", bk_pct=3, pnl_pct=-STOP_PCT)
    assert action == "STOP LOSS"


def test_no_stop_just_above_threshold():
    action, _, _ = _stock_action(85, "BUY", bk_pct=3, pnl_pct=-0.074)
    assert action != "STOP LOSS"


def test_climax_top_at_60_pct():
    action, _, urgency = _stock_action(88, "STRONG BUY", bk_pct=60, pnl_pct=0.40)
    assert action == "TRIM 50%"
    assert urgency == "HIGH"


def test_strong_buy_at_pivot_add():
    action, _, _ = _stock_action(90, "STRONG BUY", bk_pct=2, pnl_pct=0.05)
    assert action == "ADD"


def test_strong_buy_in_buy_zone_add():
    action, _, _ = _stock_action(90, "STRONG BUY", bk_pct=6, pnl_pct=0.08)
    assert action == "ADD"


def test_strong_buy_healthy_move_hold():
    action, _, _ = _stock_action(90, "STRONG BUY", bk_pct=25, pnl_pct=0.20)
    assert action == "HOLD"


def test_strong_buy_extended_trail():
    action, _, _ = _stock_action(90, "STRONG BUY", bk_pct=45, pnl_pct=0.35)
    assert action == "HOLD + TRAIL"


def test_buy_in_zone_add():
    action, _, _ = _stock_action(82, "BUY", bk_pct=5, pnl_pct=0.03)
    assert action == "ADD"


def test_buy_extended_trim():
    action, _, _ = _stock_action(82, "BUY", bk_pct=45, pnl_pct=0.30)
    assert action == "TRIM 25%"


def test_watch_hold():
    action, _, _ = _stock_action(75, "WATCH", bk_pct=15, pnl_pct=0.10)
    assert action == "HOLD"


def test_watch_large_gain_trim():
    action, _, _ = _stock_action(75, "WATCH", bk_pct=15, pnl_pct=0.55)
    assert action == "TRIM 25%"


def test_monitor_winner_trim():
    action, _, urgency = _stock_action(68, "MONITOR", bk_pct=10, pnl_pct=0.25)
    assert action == "TRIM 25%"
    assert urgency in ("HIGH", "ELEVATED")


def test_monitor_big_winner_trim50():
    action, _, _ = _stock_action(68, "MONITOR", bk_pct=10, pnl_pct=0.55)
    assert action == "TRIM 50%"


def test_monitor_loser_sell():
    action, _, urgency = _stock_action(68, "MONITOR", bk_pct=5, pnl_pct=-0.05)
    assert action == "SELL"
    assert urgency == "HIGH"


def test_pass_sell():
    action, _, urgency = _stock_action(55, "PASS", bk_pct=0, pnl_pct=-0.02)
    assert action == "SELL"
    assert urgency == "HIGH"


def test_pass_large_gain_trim75():
    action, _, _ = _stock_action(55, "PASS", bk_pct=0, pnl_pct=0.60)
    assert action == "TRIM 75%"


def test_no_pnl_no_stop():
    # If cost basis unknown, should not trigger stop loss
    action, _, _ = _stock_action(90, "STRONG BUY", bk_pct=5, pnl_pct=None)
    assert action != "STOP LOSS"


# ── OPTION ACTION TESTS ───────────────────────────────────────

def test_itm_call_big_gain_sell():
    opt = {"type": "call", "strike": 100, "contracts": 1,
           "expiry": "2027-01-01", "premium_paid": 5.00}
    oa = _analyse_option(opt, current_price=115.0, signal="BUY", stock_pnl=0.15)
    assert oa["itm"] is True
    assert oa["intrinsic"] == 15.0
    assert oa["action"] == "SELL TO CLOSE"


def test_itm_call_hold_on_strong_buy():
    opt = {"type": "call", "strike": 100, "contracts": 1,
           "expiry": "2027-06-01", "premium_paid": 8.00}
    oa = _analyse_option(opt, current_price=108.0, signal="STRONG BUY", stock_pnl=0.10)
    assert oa["itm"] is True
    assert oa["action"] == "HOLD"


def test_otm_call_near_expiry_let_expire():
    opt = {"type": "call", "strike": 120, "contracts": 1,
           "expiry": "2026-05-30", "premium_paid": 2.00}
    oa = _analyse_option(opt, current_price=105.0, signal="WATCH", stock_pnl=0.05)
    assert oa["itm"] is False
    assert oa["action"] == "LET EXPIRE"


def test_otm_call_strong_buy_hold():
    opt = {"type": "call", "strike": 120, "contracts": 1,
           "expiry": "2027-01-01", "premium_paid": 6.00}
    oa = _analyse_option(opt, current_price=112.0, signal="STRONG BUY", stock_pnl=0.08)
    assert oa["itm"] is False
    assert oa["action"] == "HOLD"


def test_otm_call_pass_rated_sell():
    opt = {"type": "call", "strike": 120, "contracts": 1,
           "expiry": "2027-01-01", "premium_paid": 6.00}
    oa = _analyse_option(opt, current_price=112.0, signal="PASS", stock_pnl=-0.03)
    assert oa["action"] == "SELL TO CLOSE"


def test_itm_put_big_gain_sell():
    opt = {"type": "put", "strike": 100, "contracts": 1,
           "expiry": "2027-01-01", "premium_paid": 4.00}
    oa = _analyse_option(opt, current_price=88.0, signal="MONITOR", stock_pnl=-0.12)
    assert oa["itm"] is True
    assert oa["intrinsic"] == 12.0
    assert oa["action"] == "SELL TO CLOSE"


def test_otm_put_on_strong_buy_let_expire():
    opt = {"type": "put", "strike": 90, "contracts": 1,
           "expiry": "2027-01-01", "premium_paid": 3.00}
    oa = _analyse_option(opt, current_price=105.0, signal="STRONG BUY", stock_pnl=0.15)
    assert oa["itm"] is False
    assert oa["action"] == "LET EXPIRE"


def test_no_price_data_unknown():
    opt = {"type": "call", "strike": 100, "contracts": 1}
    oa = _analyse_option(opt, current_price=None, signal="BUY", stock_pnl=None)
    assert oa["action"] == "UNKNOWN"


def test_itm_call_near_expiry_strong_buy_roll():
    opt = {"type": "call", "strike": 100, "contracts": 1,
           "expiry": "2026-06-06", "premium_paid": 5.00}   # ~15d out
    oa = _analyse_option(opt, current_price=108.0, signal="STRONG BUY", stock_pnl=0.10)
    assert oa["itm"] is True
    assert oa["action"] in ("ROLL", "SELL TO CLOSE")   # either is valid near expiry


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
