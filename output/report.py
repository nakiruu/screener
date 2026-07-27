"""
output/report.py
HTML dashboard builder for QQQ CANSLIM scan results.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime
from html import escape as _esc


def build_html_report(all_results: dict, path: str) -> None:
    """Generate an HTML dashboard and write it to path."""
    meta    = all_results.get("meta", {})
    results = all_results.get("results", [])
    valid   = [r for r in results if not r.get("error")]

    run_time = meta.get("run_time", datetime.now().isoformat())
    elapsed  = meta.get("elapsed_s", 0)
    market   = meta.get("market", {})

    rows_html = "\n".join(_row(i + 1, r) for i, r in enumerate(valid))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>QQQ CANSLIM Scan — {run_time[:10]}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:20px; }}
  h1   {{ color:#38bdf8; margin-bottom:4px; }}
  .meta {{ font-size:.85rem; color:#94a3b8; margin-bottom:20px; }}
  table {{ border-collapse:collapse; width:100%; font-size:.82rem; }}
  th    {{ background:#1e293b; color:#94a3b8; padding:8px 10px; text-align:left; border-bottom:1px solid #334155; position:sticky; top:0; }}
  td    {{ padding:6px 10px; border-bottom:1px solid #1e293b; }}
  tr:hover td {{ background:#1e293b; }}
  .sb  {{ color:#16a34a; font-weight:700; }}
  .buy {{ color:#22c55e; font-weight:600; }}
  .wtch{{ color:#f59e0b; }}
  .mon {{ color:#f97316; }}
  .pass{{ color:#ef4444; }}
  .score {{ font-weight:700; }}
</style>
</head>
<body>
<h1>QQQ CANSLIM Scanner</h1>
<div class="meta">
  Run: {run_time[:19]} &nbsp;|&nbsp; {elapsed:.1f}s &nbsp;|&nbsp;
  {len(valid)}/{meta.get('total_tickers', '?')} tickers &nbsp;|&nbsp;
  Market: {market.get('market_note', '?')} &nbsp;|&nbsp;
  M={market.get('M_score', '?')}/5 &nbsp;|&nbsp;
  Dist days: {market.get('dist_days', '?')}
</div>
<table>
<thead>
<tr>
  <th>#</th><th>Ticker</th><th>Score</th><th>Signal</th>
  <th>BK%</th><th>C</th><th>A</th><th>N+S</th><th>L</th><th>I</th><th>M</th>
  <th>EPS Growth</th><th>CAGR</th><th>ROE</th><th>RS%</th>
  <th>Price</th><th>Sector</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

    Path(path).write_text(html, encoding="utf-8")


def _row(rank: int, r: dict) -> str:
    sig   = r.get("signal", "PASS")
    cls   = {"STRONG BUY": "sb", "BUY": "buy", "WATCH": "wtch",
             "MONITOR": "mon", "PASS": "pass"}.get(sig, "")
    bk    = f"{r['breakout_pct']:.0f}%" if r.get("breakout_pct") is not None else "—"
    ns    = (r.get("N_score", 0) or 0) + (r.get("S_score", 0) or 0)
    eps   = f"{r['C_eps_growth']*100:.0f}%" if r.get("C_eps_growth") is not None else "—"
    cagr  = f"{r['A_cagr']*100:.0f}%" if r.get("A_cagr") is not None else "—"
    roe   = f"{r['A_roe']*100:.0f}%" if r.get("A_roe") is not None else "—"
    rs    = f"{r['rs_pct']:.0f}" if r.get("rs_pct") is not None else "—"
    price = f"${r['price']:.2f}" if r.get("price") is not None else "—"

    sector = _esc(str(r.get('sector', '—')))
    ticker = _esc(str(r.get('ticker', '')))

    return (
        f"<tr>"
        f"<td>{rank}</td>"
        f"<td><b>{ticker}</b></td>"
        f"<td class='score'>{r.get('composite', 0):.1f}</td>"
        f"<td class='{cls}'>{sig}</td>"
        f"<td>{bk}</td>"
        f"<td>{r.get('C_score', 0):.1f}</td>"
        f"<td>{r.get('A_score', 0):.1f}</td>"
        f"<td>{ns:.1f}</td>"
        f"<td>{r.get('L_score', 0):.1f}</td>"
        f"<td>{r.get('I_score', 0):.1f}</td>"
        f"<td>{r.get('M_score', 0):.1f}</td>"
        f"<td>{eps}</td>"
        f"<td>{cagr}</td>"
        f"<td>{roe}</td>"
        f"<td>{rs}</td>"
        f"<td>{price}</td>"
        f"<td>{sector}</td>"
        f"</tr>"
    )
