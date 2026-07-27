"""
portfolio/manager.py
Portfolio analysis engine: scores each holding with CANSLIM FA+TA and
produces ranked action recommendations per position and per option leg.

Action ladder (stock):
  ADD          — within buy zone, score ≥ 80
  HOLD         — healthy position, no action needed
  HOLD + TRAIL — extended move; tighten trailing stop
  TRIM 25%     — score slipping or minor extension
  TRIM 50%     — climax top / MONITOR on winner
  TRIM 75%     — PASS signal but large unrealised gain
  SELL         — PASS / MONITOR on loser; score < 65
  STOP LOSS    — mandatory; position down ≥ 7.5% from cost

Action ladder (options):
  SELL TO CLOSE   — ITM with large gain, or OTM near expiry on weak stock
  EXERCISE        — deep ITM call near expiry on strong stock
  ROLL            — ITM / ATM with < 21d, still bullish
  HOLD            — ITM or bullish OTM with time remaining
  LET EXPIRE      — OTM near expiry, no recovery expected
"""

from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path

import numpy as np

from scanners.fundamental import score_fundamentals
from scanners.technical   import score_technical, score_L_from_ranks
from scanners.market_gate import score_market
from models.scorer        import build_composite_score, get_signal

STOP_PCT    = 0.075   # O'Neil hard stop: -7.5% from cost
TARGET_1    = 0.20    # +20%
TARGET_2    = 0.50    # +50%
SCORE_BUY   = 80.0
SCORE_WATCH = 72.0
SCORE_MON   = 65.0


# ── PUBLIC API ────────────────────────────────────────────────

def analyse_portfolio(
    positions: list[dict],
    refresh: bool = False,
    period: str = "6mo",
) -> dict:
    """
    Score and recommend actions for a list of positions.

    Each position dict (required fields):
      ticker      str    e.g. "NVDA"
      shares      float  number of shares held
      cost_basis  float  average cost per share

    Optional fields:
      options     list   see _analyse_option() for option dict schema

    Returns a dict with keys:
      positions   list[dict]   enriched position results
      summary     dict         portfolio-level stats
      market      dict         market gate result
    """
    tickers = [p["ticker"].upper() for p in positions]

    # ── Market gate (once) ────────────────────────────────────
    market = score_market(refresh=refresh)

    # ── Score each ticker ─────────────────────────────────────
    scored: list[dict] = []
    for pos in positions:
        r = _score_position(pos, market, refresh=refresh, period=period)
        scored.append(r)

    # ── RS cross-sectional ranking ────────────────────────────
    scored = score_L_from_ranks(scored)

    # ── Recompute composites + generate actions ───────────────
    for r in scored:
        if not r.get("error"):
            r["composite"] = build_composite_score(r)
            r["signal"]    = get_signal(r["composite"])
        _generate_actions(r)

    # ── Portfolio summary ─────────────────────────────────────
    summary = _portfolio_summary(scored)

    return {"positions": scored, "summary": summary, "market": market}


# ── POSITION SCORING ──────────────────────────────────────────

def _score_position(pos: dict, market: dict,
                    refresh: bool, period: str) -> dict:
    ticker = pos["ticker"].upper()
    shares = float(pos.get("shares", 0))
    cost   = float(pos.get("cost_basis", 0))

    result = {
        "ticker":     ticker,
        "shares":     shares,
        "cost_basis": cost,
        "options":    pos.get("options", []),
        "error":      None,
        # CANSLIM sub-scores
        "C_score": 0, "A_score": 0, "N_score": 0,
        "S_score": 0, "L_score": 7.5, "I_score": 3.0,
        "M_score": round(market.get("M_score", 4.0), 1),
        # Technicals
        "breakout_pct": None, "base_pivot": None,
        "dist_from_hi": None, "rs_pct": None,
        "_mom_raw": 0.0,
        # Fundamentals
        "C_eps_growth": None, "A_cagr": None, "A_roe": None,
        "inst_pct": None,
        # Price / P&L
        "price": None, "mkt_value": None,
        "pnl_dollar": None, "pnl_pct": None,
        "stop_price": None, "t1_price": None, "t2_price": None,
        # Composite
        "composite": 0, "signal": "PASS",
        # Actions (filled later)
        "stock_action": None, "stock_rationale": None, "urgency": "NORMAL",
        "option_actions": [],
    }

    try:
        # Fundamentals
        fund = score_fundamentals(ticker, refresh=refresh)
        result.update({
            "C_score":      fund["C_score"],
            "A_score":      fund["A_score"],
            "I_score":      fund["I_score"],
            "C_eps_growth": fund.get("eps_growth"),
            "A_cagr":       fund.get("eps_cagr"),
            "A_roe":        fund.get("roe"),
            "inst_pct":     fund.get("inst_pct"),
            "price":        fund.get("price"),
        })

        # Technicals
        tech = score_technical(ticker, period=period, refresh=refresh)
        result.update({
            "N_score":      tech["N_score"],
            "S_score":      tech["S_score"],
            "L_score":      tech["L_score"],
            "breakout_pct": tech.get("breakout_pct"),
            "base_pivot":   tech.get("base_pivot"),
            "dist_from_hi": tech.get("dist_from_hi"),
            "rs_pct":       tech.get("rs_pct"),
            "_mom_raw":     tech.get("_mom_raw", 0.0),
        })

        # Price / P&L
        price = result["price"]
        if price and cost > 0:
            result["mkt_value"]  = round(price * shares, 2)
            result["pnl_dollar"] = round((price - cost) * shares, 2)
            result["pnl_pct"]    = round((price / cost) - 1, 4)
            result["stop_price"] = round(cost * (1 - STOP_PCT), 2)
            result["t1_price"]   = round(cost * (1 + TARGET_1), 2)
            result["t2_price"]   = round(cost * (1 + TARGET_2), 2)

    except Exception as e:
        result["error"] = str(e)

    return result


# ── ACTION ENGINE ─────────────────────────────────────────────

def _generate_actions(r: dict) -> None:
    """Fill stock_action, stock_rationale, urgency, and option_actions in-place."""
    if r.get("error"):
        r["stock_action"]    = "ERROR"
        r["stock_rationale"] = r["error"]
        r["urgency"]         = "HIGH"
        return

    score   = r["composite"]
    signal  = r["signal"]
    bk      = r.get("breakout_pct")
    pnl     = r.get("pnl_pct")    # may be None if no cost_basis
    price   = r.get("price")

    action, rationale, urgency = _stock_action(score, signal, bk, pnl)
    r["stock_action"]    = action
    r["stock_rationale"] = rationale
    r["urgency"]         = urgency

    # Options
    r["option_actions"] = []
    for opt in r.get("options", []):
        oa = _analyse_option(opt, price, signal, pnl)
        r["option_actions"].append(oa)


def _stock_action(
    score: float, signal: str,
    bk_pct: float | None, pnl_pct: float | None,
) -> tuple[str, str, str]:
    """
    Return (action, rationale, urgency) for a stock position.
    pnl_pct is fraction (0.10 = +10%). May be None if no cost basis.
    """
    bk = float(bk_pct) if bk_pct is not None else 0.0

    # ── Hard stop (regardless of score) ──────────────────────
    if pnl_pct is not None and pnl_pct <= -STOP_PCT:
        return (
            "STOP LOSS",
            f"Down {abs(pnl_pct)*100:.1f}% from cost — O'Neil 7.5% hard stop triggered",
            "URGENT",
        )

    # ── Climax top guard ──────────────────────────────────────
    if bk >= 60:
        return (
            "TRIM 50%",
            f"Breakout {bk:.0f}% above pivot — climax top risk; lock in gains",
            "HIGH",
        )

    # ── STRONG BUY ───────────────────────────────────────────
    if signal == "STRONG BUY":
        if bk < 5:
            return "ADD", "Score 88+ at/near pivot — ideal add point", "NORMAL"
        if bk < 8:
            return "ADD", f"Score 88+ within buy zone ({bk:.0f}% above pivot)", "NORMAL"
        if bk < 40:
            return "HOLD", f"Healthy breakout ({bk:.0f}%) on elite leader — hold", "NORMAL"
        return "HOLD + TRAIL", f"Extended {bk:.0f}% — tighten trailing stop, no adds", "NORMAL"

    # ── BUY ───────────────────────────────────────────────────
    if signal == "BUY":
        if bk < 8:
            return "ADD", f"Score 80+ within buy zone ({bk:.0f}% above pivot)", "NORMAL"
        if bk < 40:
            return "HOLD", f"BUY-rated at {bk:.0f}% above pivot — hold with stop", "NORMAL"
        return "TRIM 25%", f"BUY-rated but extended {bk:.0f}% — trim to manage risk", "ELEVATED"

    # ── WATCH ─────────────────────────────────────────────────
    if signal == "WATCH":
        if pnl_pct is not None and pnl_pct > TARGET_2:
            return "TRIM 25%", f"WATCH score but +{pnl_pct*100:.0f}% gain — protect profits", "ELEVATED"
        return "HOLD", "WATCH-rated — hold position, set stop, no new buys", "NORMAL"

    # ── MONITOR ──────────────────────────────────────────────
    if signal == "MONITOR":
        if pnl_pct is None:
            return "TRIM 25%", "MONITOR signal — reduce exposure", "ELEVATED"
        if pnl_pct >= TARGET_2:
            return "TRIM 50%", f"MONITOR on +{pnl_pct*100:.0f}% position — protect large gain", "HIGH"
        if pnl_pct >= TARGET_1:
            return "TRIM 25%", f"MONITOR on +{pnl_pct*100:.0f}% position — lock in partial gain", "ELEVATED"
        if pnl_pct >= 0:
            return "SELL", "MONITOR signal on small winner — exit cleanly", "HIGH"
        return "SELL", f"MONITOR signal on losing position ({pnl_pct*100:.1f}%) — exit now", "HIGH"

    # ── PASS ─────────────────────────────────────────────────
    if pnl_pct is not None and pnl_pct >= TARGET_2:
        return (
            "TRIM 75%",
            f"PASS-rated but +{pnl_pct*100:.0f}% gain — keep 25% runner with tight stop",
            "HIGH",
        )
    return "SELL", f"Score {score:.0f} below minimum threshold — exit position", "HIGH"


# ── OPTION ANALYSIS ───────────────────────────────────────────

def _analyse_option(opt: dict, current_price: float | None,
                    signal: str, stock_pnl: float | None) -> dict:
    """
    Analyse a single option leg and return an action dict.

    Option dict schema:
      type        str    'call' or 'put'
      strike      float  strike price
      contracts   int    number of contracts (each = 100 shares)
      expiry      str    'YYYY-MM-DD'  (optional)
      premium_paid float cost per share paid for the option (optional)
    """
    opt_type  = opt.get("type", "call").lower()
    strike    = float(opt.get("strike", 0))
    contracts = int(opt.get("contracts", 1))
    premium   = float(opt.get("premium_paid", 0))
    expiry_s  = opt.get("expiry")

    dte = None
    if expiry_s:
        try:
            exp = datetime.strptime(expiry_s, "%Y-%m-%d").date()
            dte = (exp - date.today()).days
        except ValueError:
            pass

    result = {
        "type":       opt_type,
        "strike":     strike,
        "contracts":  contracts,
        "expiry":     expiry_s,
        "dte":        dte,
        "premium_paid": premium,
        "itm":        None,
        "intrinsic":  None,
        "action":     None,
        "rationale":  None,
    }

    if current_price is None:
        result["action"]    = "UNKNOWN"
        result["rationale"] = "No price data"
        return result

    if opt_type == "call":
        intrinsic = max(0.0, current_price - strike)
        itm       = current_price > strike
        otm_pct   = (strike - current_price) / current_price * 100 if not itm else 0

        result["itm"]       = itm
        result["intrinsic"] = round(intrinsic, 2)

        if itm:
            gain_pct = (intrinsic / premium - 1) if premium > 0 else None
            if gain_pct is not None and gain_pct >= 1.0:
                result["action"]    = "SELL TO CLOSE"
                result["rationale"] = (
                    f"Call ITM with {gain_pct*100:.0f}% gain (intrinsic ${intrinsic:.2f}) "
                    "— take profits"
                )
            elif dte is not None and dte <= 21:
                if signal in ("STRONG BUY", "BUY"):
                    result["action"]    = "ROLL"
                    result["rationale"] = (
                        f"ITM call, {dte}d to expiry, stock rated {signal} "
                        "— roll to next expiry to stay long"
                    )
                else:
                    result["action"]    = "SELL TO CLOSE"
                    result["rationale"] = (
                        f"ITM call, {dte}d to expiry — sell for intrinsic value "
                        f"(${intrinsic:.2f})"
                    )
            elif signal in ("STRONG BUY", "BUY"):
                result["action"]    = "HOLD"
                result["rationale"] = (
                    f"ITM call (${intrinsic:.2f} intrinsic) on {signal}-rated stock — hold"
                )
            else:
                result["action"]    = "SELL TO CLOSE"
                result["rationale"] = (
                    f"ITM call on {signal}-rated stock — exit, capture intrinsic"
                )
        else:
            # OTM
            if dte is not None and dte <= 14:
                result["action"]    = "LET EXPIRE"
                result["rationale"] = (
                    f"OTM call {otm_pct:.1f}% below strike, {dte}d to expiry "
                    "— let expire"
                )
            elif signal in ("STRONG BUY", "BUY") and (dte is None or dte > 21):
                result["action"]    = "HOLD"
                result["rationale"] = (
                    f"OTM call {otm_pct:.1f}% below strike on {signal}-rated stock "
                    "— hold for potential move"
                )
            else:
                result["action"]    = "SELL TO CLOSE"
                result["rationale"] = (
                    f"OTM call {otm_pct:.1f}% below strike on {signal}-rated stock "
                    "— recover remaining premium"
                )

    elif opt_type == "put":
        intrinsic = max(0.0, strike - current_price)
        itm       = current_price < strike

        result["itm"]       = itm
        result["intrinsic"] = round(intrinsic, 2)

        if itm:
            gain_pct = (intrinsic / premium - 1) if premium > 0 else None
            if gain_pct is not None and gain_pct >= 0.5:
                result["action"]    = "SELL TO CLOSE"
                result["rationale"] = (
                    f"Put ITM with {gain_pct*100:.0f}% gain — take profits on hedge"
                )
            else:
                result["action"]    = "HOLD"
                result["rationale"] = "Put ITM — maintain hedge while stock weak"
        else:
            if signal in ("STRONG BUY", "BUY"):
                result["action"]    = "LET EXPIRE"
                result["rationale"] = (
                    f"Protective put, stock rated {signal} — let hedge expire"
                )
            elif dte is not None and dte <= 14:
                result["action"]    = "LET EXPIRE"
                result["rationale"] = "OTM put near expiry — let expire"
            else:
                result["action"]    = "HOLD"
                result["rationale"] = "Put hedge on weakening position — maintain"

    else:
        result["action"]    = "REVIEW"
        result["rationale"] = f"Unknown option type: {opt_type}"

    return result


# ── PORTFOLIO SUMMARY ─────────────────────────────────────────

def _portfolio_summary(results: list[dict]) -> dict:
    valid = [r for r in results if not r.get("error")]

    total_cost  = sum(r["cost_basis"] * r["shares"] for r in valid if r["cost_basis"])
    total_value = sum(r["mkt_value"] or 0 for r in valid)
    total_pnl   = total_value - total_cost

    signals = {}
    urgency_counts = {"URGENT": 0, "HIGH": 0, "ELEVATED": 0, "NORMAL": 0}
    for r in valid:
        signals[r["signal"]] = signals.get(r["signal"], 0) + 1
        u = r.get("urgency", "NORMAL")
        urgency_counts[u] = urgency_counts.get(u, 0) + 1

    return {
        "total_positions":  len(results),
        "valid_positions":  len(valid),
        "total_cost_basis": round(total_cost,  2),
        "total_mkt_value":  round(total_value, 2),
        "total_pnl_dollar": round(total_pnl,   2),
        "total_pnl_pct":    round(total_pnl / total_cost, 4) if total_cost else 0,
        "signal_breakdown": signals,
        "urgency_counts":   urgency_counts,
    }
