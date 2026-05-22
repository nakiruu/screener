"""
output/report.py
HTML dashboard builder for QQQ CANSLIM scan results.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime


_SIGNAL_COLORS = {
    "STRONG BUY": "#00b300",
    "BUY":        "#33cc33",
    "WATCH":      "#cccc00",
    "MONITOR":    "#ff9900",
    "PASS":       "#cc0000",
    "NEUTRAL":    "#888888",
}

_TIER_BADGE = {
    "STRONG BUY": "badge-strong-buy",
    "BUY":        "badge-buy",
    "WATCH":      "badge-watch",
    "MONITOR":    "badge-monitor",
    "PASS":       "badge-pass",
    "NEUTRAL":    "badge-neutral",
}

_CSS = """
body { font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; margin: 0; padding: 20px; }
h1 { color: #00ff88; letter-spacing: 2px; }
h2 { color: #aaa; font-size: 1rem; font-weight: normal; margin-top: 0; }
.meta { color: #666; font-size: 0.85rem; margin-bottom: 20px; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th { background: #1a1a1a; color: #aaa; padding: 8px 10px; text-align: right; border-bottom: 1px solid #333; cursor: pointer; }
th:first-child, th:nth-child(2) { text-align: left; }
td { padding: 6px 10px; border-bottom: 1px solid #1e1e1e; text-align: right; }
td:first-child, td:nth-child(2) { text-align: left; }
tr:hover { background: #1a1a1a; }
.badge { padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 0.78rem; }
.badge-strong-buy { background: #003300; color: #00ff44; }
.badge-buy        { background: #003300; color: #66ff66; }
.badge-watch      { background: #332800; color: #ffcc00; }
.badge-monitor    { background: #331a00; color: #ff9900; }
.badge-pass       { background: #330000; color: #ff4444; }
.badge-neutral    { background: #222; color: #888; }
.score-hi { color: #00ff88; font-weight: bold; }
.score-mid { color: #ffcc00; }
.score-lo { color: #ff6666; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 28px; }
.stat-box { background: #1a1a1a; border: 1px solid #333; border-radius: 4px; padding: 14px; }
.stat-label { color: #666; font-size: 0.78rem; text-transform: uppercase; }
.stat-value { color: #00ff88; font-size: 1.4rem; font-weight: bold; margin-top: 4px; }
.market-bar { background: #1a1a1a; border: 1px solid #333; padding: 10px 16px; border-radius: 4px; margin-bottom: 20px; font-size: 0.85rem; color: #aaa; }
.gate-open { color: #00ff44; font-weight: bold; }
.gate-closed { color: #ff4444; font-weight: bold; }
"""

_SORT_JS = """
function sortTable(col) {
  const tbl = document.getElementById('results');
  const rows = Array.from(tbl.querySelectorAll('tbody tr'));
  const asc  = tbl.dataset.sortCol === String(col) && tbl.dataset.sortDir === 'asc';
  rows.sort((a, b) => {
    let av = a.cells[col].dataset.val ?? a.cells[col].textContent.trim();
    let bv = b.cells[col].dataset.val ?? b.cells[col].textContent.trim();
    av = isNaN(av) ? av : parseFloat(av);
    bv = isNaN(bv) ? bv : parseFloat(bv);
    return asc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });
  const tbody = tbl.querySelector('tbody');
  rows.forEach(r => tbody.appendChild(r));
  tbl.dataset.sortCol = col;
  tbl.dataset.sortDir = asc ? 'desc' : 'asc';
}
"""


def build_html_report(all_results: dict, path: str) -> None:
    """Build and write an HTML dashboard from scan results."""
    meta    = all_results.get("meta", {})
    results = all_results.get("results", [])

    valid  = [r for r in results if not r.get("error")]
    scores = [r["composite"] for r in valid]

    run_time = meta.get("run_time", datetime.now().isoformat())
    elapsed  = meta.get("elapsed_s", 0)
    mkt      = meta.get("market", {})

    # ── Market bar ─────────────────────────────────────────────
    gate_open = mkt.get("gate_open", True)
    gate_cls  = "gate-open" if gate_open else "gate-closed"
    gate_lbl  = "OPEN ✓" if gate_open else "CLOSED ✗"
    trend20   = mkt.get("trend_20", 0) * 100
    dist_days = mkt.get("dist_days", 0)
    mkt_note  = mkt.get("market_note", "")
    market_html = f"""
    <div class="market-bar">
      <b>Market Gate:</b> <span class="{gate_cls}">{gate_lbl}</span>
      &nbsp;|&nbsp; XLK 20d: <b>{trend20:+.1f}%</b>
      &nbsp;|&nbsp; Dist Days: <b>{dist_days}</b>
      &nbsp;|&nbsp; {mkt_note}
    </div>"""

    # ── Stat boxes ─────────────────────────────────────────────
    n_sb = sum(1 for r in valid if r.get("signal") == "STRONG BUY")
    n_b  = sum(1 for r in valid if r.get("signal") == "BUY")
    mean_s = f"{sum(scores)/len(scores):.1f}" if scores else "—"
    stat_html = f"""
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-label">Tickers Scanned</div>
        <div class="stat-value">{meta.get('total_tickers', len(results))}</div></div>
      <div class="stat-box"><div class="stat-label">Valid Results</div>
        <div class="stat-value">{len(valid)}</div></div>
      <div class="stat-box"><div class="stat-label">Strong Buy</div>
        <div class="stat-value" style="color:#00ff44">{n_sb}</div></div>
      <div class="stat-box"><div class="stat-label">Buy</div>
        <div class="stat-value" style="color:#66ff66">{n_b}</div></div>
      <div class="stat-box"><div class="stat-label">Mean Score</div>
        <div class="stat-value">{mean_s}</div></div>
      <div class="stat-box"><div class="stat-label">Scan Time</div>
        <div class="stat-value">{elapsed:.0f}s</div></div>
    </div>"""

    # ── Table rows ─────────────────────────────────────────────
    rows_html = []
    for i, r in enumerate(results, 1):
        score  = r.get("composite", 0)
        signal = r.get("signal", "NEUTRAL")
        bk     = r.get("breakout_pct")
        bk_str = f"{bk:.0f}%" if bk is not None else "—"
        ns     = (r.get("N_score") or 0) + (r.get("S_score") or 0)
        price  = r.get("price")
        price_str = f"${price:.2f}" if price else "—"

        score_cls = ("score-hi" if score >= 80 else
                     "score-mid" if score >= 65 else "score-lo")
        badge_cls = _TIER_BADGE.get(signal, "badge-neutral")

        def _td(v, fmt="{:.1f}"):
            if v is None:
                return "<td>—</td>"
            try:
                return f'<td data-val="{float(v):.4f}">{fmt.format(float(v))}</td>'
            except Exception:
                return f"<td>{v}</td>"

        rows_html.append(f"""<tr>
          <td>{i}</td>
          <td><b>{r.get('ticker','?')}</b></td>
          <td data-val="{score:.1f}"><span class="{score_cls}">{score:.1f}</span></td>
          <td><span class="badge {badge_cls}">{signal}</span></td>
          <td>{price_str}</td>
          <td>{bk_str}</td>
          {_td(r.get('C_score'))}
          {_td(r.get('A_score'))}
          {_td(ns)}
          {_td(r.get('L_score'))}
          {_td(r.get('I_score'))}
          {_td(r.get('M_score'))}
          <td>{r.get('sector','—')}</td>
        </tr>""")

    table_html = f"""
    <table id="results" data-sort-col="" data-sort-dir="">
      <thead><tr>
        <th onclick="sortTable(0)">#</th>
        <th onclick="sortTable(1)">Ticker</th>
        <th onclick="sortTable(2)">Score</th>
        <th onclick="sortTable(3)">Signal</th>
        <th onclick="sortTable(4)">Price</th>
        <th onclick="sortTable(5)">BK%</th>
        <th onclick="sortTable(6)">C</th>
        <th onclick="sortTable(7)">A</th>
        <th onclick="sortTable(8)">N+S</th>
        <th onclick="sortTable(9)">L</th>
        <th onclick="sortTable(10)">I</th>
        <th onclick="sortTable(11)">M</th>
        <th onclick="sortTable(12)">Sector</th>
      </tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>QQQ CANSLIM Scanner — {run_time[:10]}</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>QQQ CANSLIM SCANNER</h1>
  <h2>Nasdaq-100 · {run_time[:10]} · {elapsed:.1f}s</h2>
  <div class="meta">Formula: Score = C(0–25) + A(0–20) + N+S(0–30) + L(0–15) + I(0–5) + M(0–5) = max 100</div>
  {market_html}
  {stat_html}
  {table_html}
  <script>{_SORT_JS}</script>
</body>
</html>"""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
