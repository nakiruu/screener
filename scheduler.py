#!/usr/bin/env python3
"""
scheduler.py — Daily intraday scan at 9:35 AM EDT
Runs as a background daemon. Logs to logs/intraday.log.

Usage:
  nohup python scheduler.py &
  python scheduler.py --once        # fire immediately (test mode)
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import zoneinfo
    _ET = zoneinfo.ZoneInfo("America/New_York")
    def _now_et():
        return datetime.now(_ET)
except Exception:
    import time as _t
    def _now_et():
        offset = -4 if _t.daylight and _t.localtime().tm_isdst else -5
        return datetime.utcnow() + timedelta(hours=offset)


SCAN_HOUR   = 9
SCAN_MINUTE = 35
LOG_FILE    = Path(__file__).parent / "logs" / "intraday.log"
SCRIPT      = Path(__file__).parent / "run_intraday.py"


def next_fire_et() -> datetime:
    """Next 9:35 AM ET — today if we haven't passed it yet, tomorrow otherwise."""
    now = _now_et()
    candidate = now.replace(hour=SCAN_HOUR, minute=SCAN_MINUTE, second=0, microsecond=0)
    if now >= candidate:
        candidate += timedelta(days=1)
    return candidate


def seconds_until(target: datetime) -> float:
    now = _now_et()
    delta = (target - now).total_seconds()
    return max(delta, 0)


def run_scan() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"\n{'='*60}\n[{stamp}] Starting intraday scan\n{'='*60}\n")
        f.flush()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--top", "15"],
            cwd=str(SCRIPT.parent),
            stdout=f, stderr=f,
            text=True,
        )
        f.write(f"\n[{stamp}] Exit code: {result.returncode}\n")
    print(f"[{stamp}] Scan complete (exit {result.returncode}). Log: {LOG_FILE}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Fire once immediately and exit")
    args = p.parse_args()

    if args.once:
        print("Running scan immediately (--once mode)…")
        run_scan()
        return

    print(f"Scheduler started. Scan fires daily at {SCAN_HOUR:02d}:{SCAN_MINUTE:02d} ET.")
    print(f"Log: {LOG_FILE}")
    print("Press Ctrl+C to stop.\n")

    while True:
        target = next_fire_et()
        wait   = seconds_until(target)
        fire_s = target.strftime("%Y-%m-%d %H:%M ET")
        print(f"  Next scan: {fire_s}  ({wait/3600:.1f}h from now)")

        # Sleep in chunks so Ctrl+C is responsive
        while wait > 0:
            chunk = min(wait, 60)
            time.sleep(chunk)
            wait -= chunk

        print(f"  Firing scan — {datetime.now().strftime('%H:%M:%S')} UTC")
        run_scan()
        time.sleep(5)   # small buffer before computing next fire time


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")
        sys.exit(0)
