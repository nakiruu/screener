"""
live/refresher.py
Injects live prices into a frozen CANSLIM snapshot without re-running
the full scoring pipeline.  Only P&L, stop-loss status, and action
recommendations are recomputed on each tick.
"""

from __future__ import annotations
import copy
from portfolio.manager import _generate_actions, STOP_PCT, TARGET_1, TARGET_2


def build_live_snapshot(
    base_result: dict,
    live_prices: dict[str, float | None],
) -> dict:
    """
    Overlay live prices onto the frozen base_result from analyse_portfolio().
    Returns a new dict — base_result is never mutated.

    Only price, mkt_value, pnl_dollar, pnl_pct, stock_action,
    stock_rationale, urgency, and option_actions are refreshed.
    All CANSLIM sub-scores and TA fields remain as-is from the cache.
    """
    updated_positions = [
        _inject_price(pos, live_prices.get(pos["ticker"]))
        for pos in base_result["positions"]
    ]

    # Recompute portfolio summary from updated positions
    from portfolio.manager import _portfolio_summary
    summary = _portfolio_summary(updated_positions)

    return {
        "positions": updated_positions,
        "summary":   summary,
        "market":    base_result["market"],
    }


def _inject_price(pos: dict, live_price: float | None) -> dict:
    """
    Clone one position, overwrite price-derived fields, re-run action engine.
    """
    p = copy.copy(pos)   # shallow copy — sub-dicts (options) are not mutated

    if live_price is not None and live_price > 0:
        p["price"] = live_price
        cost   = p.get("cost_basis") or 0
        shares = p.get("shares") or 0
        if cost > 0:
            p["mkt_value"]  = round(live_price * shares, 2)
            p["pnl_dollar"] = round((live_price - cost) * shares, 2)
            p["pnl_pct"]    = round(live_price / cost - 1, 4)
            # stop / targets are cost-basis constants — only set if not already present
            p.setdefault("stop_price", round(cost * (1 - STOP_PCT), 2))
            p.setdefault("t1_price",   round(cost * (1 + TARGET_1),  2))
            p.setdefault("t2_price",   round(cost * (1 + TARGET_2),  2))

    # Re-derive action with fresh pnl_pct
    _generate_actions(p)
    return p
