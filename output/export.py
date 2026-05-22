"""
output/export.py
JSON and CSV export utilities for scan results.
"""

import csv
import json
from pathlib import Path


def export_json(all_results: dict, path: str) -> None:
    """Write full scan results (meta + results list) to JSON."""
    Path(path).write_text(json.dumps(all_results, indent=2, default=str))


def export_csv(results: list[dict], path: str) -> None:
    """Write results list to CSV with key columns."""
    if not results:
        return

    cols = [
        "ticker", "composite", "signal",
        "C_score", "A_score", "N_score", "S_score", "L_score", "I_score", "M_score",
        "breakout_pct", "base_pivot", "rs_pct", "dist_from_hi",
        "C_eps_growth", "A_cagr", "A_roe", "inst_pct",
        "price", "sector", "industry", "error",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in cols})
