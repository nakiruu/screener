"""
live/display.py
ANSI terminal dashboard — no extra dependencies.
"""

from __future__ import annotations
import shutil
from datetime import datetime

# ANSI codes
RED    = "\033[1;31m"
YELLOW = "\033[0;33m"
CYAN   = "\033[0;36m"
GREEN  = "\033[0;32m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

URGENCY_COLOR = {
    "URGENT":   RED,
    "HIGH":     YELLOW,
    "ELEVATED": CYAN,
    "NORMAL":   RESET,
}
SIGNAL_COLOR = {
    "STRONG BUY": GREEN,
    "BUY":        GREEN,
    "WATCH":      CYAN,
    "MONITOR":    YELLOW,
    "PASS":       RED,
}
URGENCY_ORDER = {"URGENT": 0, "HIGH": 1, "ELEVATED": 2, "NORMAL": 3}


def print_dashboard(snapshot: dict, mkt_status: dict,
                    last_updated: datetime) -> None:
    """Clear screen and print the full dashboard."""
    print("\033[2J\033[H", end="")
    print(render_dashboard(snapshot, mkt_status, last_updated))


def render_dashboard(snapshot: dict, mkt_status: dict,
                     last_updated: datetime) -> str:
    cols  = shutil.get_terminal_size((100, 40)).columns
    parts = []

    # Stop-loss alert banner (bright red, full width)
    banner = _alert_banner(snapshot["positions"], cols)
    if banner:
        parts.append(banner)

    parts.append(_header(mkt_status, last_updated, snapshot["summary"], cols))
    parts.append(_positions_table(snapshot["positions"], cols))

    return "\n".join(parts)


# ── SECTIONS ──────────────────────────────────────────────────

def _header(mkt: dict, updated: datetime, summary: dict, cols: int) -> str:
    status = mkt.get("status", "?")
    label  = mkt.get("label", "")
    gate_c = GREEN if mkt.get("open") else YELLOW
    time_s = updated.strftime("%H:%M:%S")

    pnl    = summary.get("total_pnl_dollar", 0)
    pnl_p  = summary.get("total_pnl_pct", 0) * 100
    mv     = summary.get("total_mkt_value", 0)
    sign   = "+" if pnl >= 0 else ""
    pnl_c  = GREEN if pnl >= 0 else RED

    urg    = summary.get("urgency_counts", {})
    alerts = []
    if urg.get("URGENT"):   alerts.append(f"{RED}🚨 {urg['URGENT']} STOP LOSS{RESET}")
    if urg.get("HIGH"):     alerts.append(f"{YELLOW}⚠  {urg['HIGH']} HIGH{RESET}")
    if urg.get("ELEVATED"): alerts.append(f"{CYAN}⚡ {urg['ELEVATED']} ELEVATED{RESET}")

    line1 = (f"{BOLD}  CANSLIM LIVE MONITOR{RESET}  "
             f"{gate_c}{status}{RESET}  {DIM}{label}{RESET}  "
             f"{DIM}updated {time_s}{RESET}")
    line2 = (f"  Portfolio P&L: {pnl_c}{BOLD}{sign}${pnl:,.0f} ({sign}{pnl_p:.1f}%){RESET}"
             f"  |  Market value: ${mv:,.0f}"
             + (f"  |  " + "  ".join(alerts) if alerts else ""))

    sep = "─" * cols
    return f"{sep}\n{line1}\n{line2}\n{sep}"


def _positions_table(positions: list[dict], cols: int) -> str:
    sorted_pos = sorted(
        positions,
        key=lambda r: (URGENCY_ORDER.get(r.get("urgency", "NORMAL"), 3),
                       -(r.get("pnl_pct") or 0)),
    )

    header = (f"  {'TICKER':<7} {'PRICE':>8} {'COST':>8} {'P&L':>8} "
              f"{'BK%':>5} {'SCORE':>5} {'SIGNAL':<10}  ACTION")
    rows = [header, "  " + "─" * (cols - 2)]

    for r in sorted_pos:
        rows.append(_position_row(r, cols))

    return "\n".join(rows)


def _position_row(r: dict, cols: int) -> str:
    urgency = r.get("urgency", "NORMAL")
    color   = URGENCY_COLOR.get(urgency, RESET)
    sig_c   = SIGNAL_COLOR.get(r.get("signal", ""), RESET)

    ticker  = r["ticker"]
    price   = r.get("price")
    cost    = r.get("cost_basis")
    pnl_p   = r.get("pnl_pct")
    bk      = r.get("breakout_pct")
    score   = r.get("composite", 0)
    signal  = r.get("signal", "?")
    action  = r.get("stock_action", "?")
    rationale = r.get("stock_rationale", "")

    price_s = f"${price:,.2f}"  if price is not None else "     n/a"
    cost_s  = f"${cost:,.2f}"   if cost  is not None else "     n/a"
    pnl_s   = f"{pnl_p*100:+.1f}%" if pnl_p is not None else "    n/a"
    bk_s    = f"{bk:.0f}%"      if bk    is not None else "  n/a"
    pnl_c   = (GREEN if (pnl_p or 0) >= 0 else RED) if pnl_p is not None else RESET

    row1 = (f"  {color}{ticker:<7}{RESET} {price_s:>8} {cost_s:>8} "
            f"{pnl_c}{pnl_s:>8}{RESET} "
            f"{bk_s:>5} {score:>5.1f} "
            f"{sig_c}{signal:<10}{RESET}  "
            f"{color}{BOLD}{action}{RESET}")

    # Truncate rationale to fit terminal
    max_rat = cols - 12
    rat_short = rationale[:max_rat] if len(rationale) > max_rat else rationale
    row2 = f"  {DIM}         {rat_short}{RESET}"

    # Key levels if available
    stop  = r.get("stop_price")
    t1    = r.get("t1_price")
    pivot = r.get("base_pivot")
    if stop and t1 and price:
        stop_c = RED if price <= stop * 1.02 else DIM
        pv_s   = f"  pivot ${pivot:,.2f}" if pivot else ""
        row3   = (f"  {DIM}         stop {stop_c}${stop:,.2f}{DIM}  "
                  f"T1 ${t1:,.2f}{pv_s}{RESET}")
    else:
        row3 = ""

    # Option legs
    opt_lines = []
    for oa in r.get("option_actions", []):
        otype = oa.get("type", "?").upper()
        strike = oa.get("strike", 0)
        dte    = oa.get("dte")
        itm_s  = "ITM" if oa.get("itm") else "OTM"
        dte_s  = f"{dte}d" if dte is not None else "?"
        oa_act = oa.get("action", "?")
        oa_rat = oa.get("rationale", "")[:60]
        oa_c   = RED if oa_act == "SELL TO CLOSE" else (YELLOW if oa_act == "ROLL" else DIM)
        opt_lines.append(
            f"  {DIM}         ├─ {otype} ${strike:.0f} {itm_s} {dte_s} → "
            f"{oa_c}{oa_act}{DIM}  {oa_rat}{RESET}"
        )

    lines = [row1, row2]
    if row3:
        lines.append(row3)
    lines.extend(opt_lines)
    lines.append("")   # blank spacer
    return "\n".join(lines)


def _alert_banner(positions: list[dict], cols: int) -> str:
    stops = [r["ticker"] for r in positions
             if r.get("stock_action") == "STOP LOSS"]
    if not stops:
        return ""
    tickers = "  ".join(stops)
    msg = f"  🚨  STOP LOSS TRIGGERED: {tickers}  🚨"
    pad = " " * max(0, cols - len(msg) - 2)
    return f"{RED}{BOLD}{msg}{pad}{RESET}\n"
