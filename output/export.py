"""
output/export.py
JSON and CSV export utilities for QQQ CANSLIM scan results.
"""

import csv
import json
from pathlib import Path


_CSV_FIELDS = [
    "ticker", "composite", "signal",
    "C_score", "A_score", "N_score", "S_score", "L_score", "I_score", "M_score",
    "breakout_pct", "base_pivot", "dist_from_hi", "rs_pct",
    "C_eps_growth", "A_cagr", "A_roe", "inst_pct",
    "price", "sector", "industry", "error",
]


def export_json(all_results: dict, path: str) -> None:
    """Write full scan results to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    def _default(obj):
        try:
            return float(obj)
        except Exception:
            return str(obj)

    p.write_text(json.dumps(all_results, indent=2, default=_default))


def export_csv(results: list[dict], path: str) -> None:
    """Write per-ticker results to a CSV file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {k: _fmt(r.get(k)) for k in _CSV_FIELDS}
            writer.writerow(row)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)
