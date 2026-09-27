"""Run a command at fixed times of day, without a cron daemon.

Containers on a NAS have no cron and no systemd, and a scheduler that drifts is
worse than none. This one sleeps until the next wall-clock time in the list,
runs the command, and never lets a slow run swallow the following slot.

    python -m nightshift.schedule --at 09:00,21:00 -- nightshift run

Times are local to the container, so set TZ in the environment.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta

DAY = 86400


def parse_times(spec: str) -> list[tuple[int, int]]:
    """"09:00, 21:30" -> [(9, 0), (21, 30)], sorted, duplicates dropped."""
    out = set()
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            hh, mm = raw.split(":")
            h, m = int(hh), int(mm)
        except ValueError:
            raise ValueError(f"not a HH:MM time: {raw!r}") from None
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"time out of range: {raw!r}")
        out.add((h, m))
    if not out:
        raise ValueError("no times given")
    return sorted(out)


def seconds_until(now: datetime, times: list[tuple[int, int]]) -> float:
    """Seconds from `now` to the next slot, rolling over to tomorrow.

    A slot exactly at `now` counts as tomorrow's: the run that just happened
    must not be repeated in a tight loop.
    """
    best = None
    for h, m in times:
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        delay = (target - now).total_seconds()
        if delay <= 0:
            delay += DAY
        if best is None or delay < best:
            best = delay
    return best


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nightshift.schedule", description=__doc__)
    p.add_argument("--at", required=True, help="times of day, comma separated (09:00,21:00)")
    p.add_argument("--now", action="store_true", help="also run once at startup")
    p.add_argument("command", nargs=argparse.REMAINDER,
                   help="the command to run, after --")
    a = p.parse_args(argv)

    command = [c for c in a.command if c != "--"]
    if not command:
        p.error("no command given after --")
    times = parse_times(a.at)
    slots = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    print(f"[schedule] {' '.join(command)} at {slots} ({time.tzname[0]})", flush=True)

    if a.now:
        run(command)
    while True:
        delay = seconds_until(datetime.now(), times)
        nxt = (datetime.now() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M")
        print(f"[schedule] next run {nxt} (in {delay / 60:.0f} min)", flush=True)
        time.sleep(delay)
        run(command)


def run(command: list[str]) -> None:
    started = datetime.now()
    print(f"[schedule] start {started:%Y-%m-%d %H:%M:%S}", flush=True)
    try:
        code = subprocess.call(command)
    except OSError as e:          # a missing binary must not kill the scheduler
        print(f"[schedule] could not start: {e}", file=sys.stderr, flush=True)
        return
    took = (datetime.now() - started).total_seconds()
    print(f"[schedule] exit {code} after {took:.0f}s", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
