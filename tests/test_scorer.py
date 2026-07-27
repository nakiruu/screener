"""
tests/test_scorer.py
Unit tests for the reverse-engineered CANSLIM scoring model.

Run with:  python -m pytest tests/ -v
       or: python tests/test_scorer.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.scorer import (
    build_composite_score, get_signal, get_fundamental_base,
    get_technical_overlay, SCORE_TIERS, C_MAX, A_MAX, N_MAX,
    S_MAX, L_MAX, I_MAX, M_MAX
)
from scanners.fundamental import (
    _score_eps_growth, _score_annual, _score_institutional
)
from scanners.technical import score_L_from_pct


def test_score_weights_sum_to_100():
    assert C_MAX + A_MAX + N_MAX + S_MAX + L_MAX + I_MAX + M_MAX == 100


def test_perfect_score():
    r = {
        "C_score": 25, "A_score": 20, "N_score": 15, "S_score": 15,
        "L_score": 15, "I_score": 5,  "M_score": 5,
    }
    assert build_composite_score(r) == 100.0


def test_zero_score():
    # When all explicit scores are 0, scorer uses default I (3.0) and M (4.0)
    # from the result dict — those defaults are only applied when keys are missing.
    # Passing explicit 0s overrides the defaults.
    r = {
        "C_score": 0, "A_score": 0, "N_score": 0, "S_score": 0,
        "L_score": 0, "I_score": 0, "M_score": 0,
    }
    # With all explicit zeros, result should be 0
    assert build_composite_score(r) == 0.0


def test_score_clamped_to_100():
    r = {
        "C_score": 999, "A_score": 999, "N_score": 999,
        "S_score": 999, "L_score": 999, "I_score": 999, "M_score": 999,
    }
    assert build_composite_score(r) == 100.0


def test_canslim_tier_thresholds():
    """Scores from the original audit dataset should map to expected tiers."""
    cases = [
        (92.0, "STRONG BUY"),   # CRDO
        (90.0, "STRONG BUY"),   # CIEN
        (84.0, "BUY"),          # PANW
        (80.0, "BUY"),          # AMD
        (74.0, "WATCH"),        # VRT
        (72.0, "WATCH"),        # SPLV
        (65.0, "MONITOR"),      # ENPH — sits at bottom of MONITOR band (65–72)
        (64.9, "PASS"),         # just below MONITOR threshold
        (48.0, "PASS"),         # MJ
    ]
    for score, expected in cases:
        result = get_signal(score)
        assert result == expected, f"Score {score}: expected {expected}, got {result}"


def test_eps_growth_scoring():
    """Verify EPS growth scoring calibration."""
    assert _score_eps_growth(1.50) == 25.0    # >100% → max
    assert _score_eps_growth(0.50) == 21.0    # 50% growth
    assert _score_eps_growth(0.25) == 17.0    # O'Neil threshold
    assert _score_eps_growth(0.00) ==  4.0    # flat
    assert _score_eps_growth(-0.20) == 0.0    # negative


def test_annual_scoring():
    """Verify annual CAGR + ROE scoring."""
    score = _score_annual(0.30, 0.25)
    assert 12 <= score <= 20            # should be solidly in mid-range
    score_high = _score_annual(0.50, 0.40)
    assert score_high == 20.0           # max
    score_low = _score_annual(0.0, 0.0)
    assert score_low <= 5               # near zero


def test_institutional_scoring():
    """Verify institutional ownership scoring."""
    assert _score_institutional(0.65) == 5.0   # ideal zone
    assert _score_institutional(0.45) == 4.0   # good
    assert _score_institutional(0.95) == 2.0   # over-owned
    assert _score_institutional(0.10) == 1.0   # barely any
    assert _score_institutional(None) == 3.0   # neutral default


def test_rs_scoring():
    """Verify RS percentile → L score mapping."""
    assert score_L_from_pct(99.0) == 15.0    # top
    assert score_L_from_pct(80.0) == 11.5    # O'Neil minimum
    assert score_L_from_pct(50.0) ==  5.5    # average
    assert score_L_from_pct(10.0) ==  1.0    # laggard


def test_fundamental_base():
    """Fundamental base = C + A + I."""
    r = {
        "C_score": 22, "A_score": 18, "N_score": 14, "S_score": 13,
        "L_score": 13, "I_score":  4, "M_score":  4,
    }
    fb = get_fundamental_base(r)
    assert fb == 44.0


def test_technical_overlay():
    """Technical overlay = N + S + L + M."""
    r = {
        "C_score": 22, "A_score": 18, "N_score": 14, "S_score": 13,
        "L_score": 13, "I_score":  4, "M_score":  4,
    }
    to = get_technical_overlay(r)
    assert to == 44.0


def test_audit_reconstruction():
    """
    Reconstruct scores from audit data within ±10 pts tolerance.
    Key insight from regression: SPLV (72, 12% bk) has a fundamental base of ~66
    — it's a defensive ETF with genuinely strong C+A+I from index-like stability.
    The floor score concept means these names carry high fundamental base scores
    independent of their (low) technical momentum.
    """
    audit = [
        # (ticker, actual_score, breakout_pct, est_fund_base)
        # fund_base = C+A+I estimated from regression analysis
        ("CRDO",  92, 74, 62),
        ("CIEN",  90, 68, 62),
        ("NVDA",  89, 60, 64),
        ("SPLV",  72, 12, 66),   # defensive ETF: high fundamental base, low technical
        ("TIP",   60, 10, 53),
        ("MJ",    48,  8, 38),
    ]

    from scanners.technical import _score_N, _score_S, score_L_from_pct

    TOLERANCE = 10   # pts — generous for a reconstructed model

    for ticker, actual, bk, fund_base in audit:
        # Decompose fund_base into C, A, I components
        i = min(5.0, fund_base * 0.07)    # I ≈ 7% of base
        ca = fund_base - i                 # C+A = rest

        n = _score_N(bk, 0.05 if bk > 40 else 0.15)
        s = _score_S(bk, 1.3, 1.2)
        rs_pct = (actual - 45) / (92 - 45) * 100
        l = score_L_from_pct(rs_pct)
        m = 4.0

        r = {"C_score": ca * 0.55, "A_score": ca * 0.45, "N_score": n,
             "S_score": s, "L_score": l, "I_score": i, "M_score": m}
        modeled = build_composite_score(r)
        err = abs(modeled - actual)

        assert err <= TOLERANCE, (
            f"{ticker}: actual={actual}, modeled={modeled:.1f}, err={err:.1f} "
            f"(tolerance={TOLERANCE})"
        )


if __name__ == "__main__":
    tests = [
        test_score_weights_sum_to_100,
        test_perfect_score,
        test_zero_score,
        test_score_clamped_to_100,
        test_canslim_tier_thresholds,
        test_eps_growth_scoring,
        test_annual_scoring,
        test_institutional_scoring,
        test_rs_scoring,
        test_fundamental_base,
        test_technical_overlay,
        test_audit_reconstruction,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ! {t.__name__}: EXCEPTION {e}")
            failed += 1

    print(f"\n  {passed}/{passed+failed} tests passed")
    sys.exit(0 if failed == 0 else 1)
