#!/usr/bin/env python3
"""
Simple script to validate the autosync interval selection logic used by the periodic
API data sync worker. This mirrors the rules implemented in `run.py`:

- If event start date is unknown -> UNKNOWN_DATE_INTERVAL (20 minutes)
- If event start date is within ±1.5 weeks -> RECENT_INTERVAL (3 minutes)
- Otherwise -> DAILY_INTERVAL (24 hours)

This script runs several test cases and exits with code 0 if all pass, non-zero otherwise.
"""
from datetime import datetime, timezone, timedelta
import sys

RECENT_INTERVAL = 180
UNKNOWN_DATE_INTERVAL = 20 * 60
DAILY_INTERVAL = 24 * 60 * 60
THRESHOLD_SECONDS = 1.5 * 7 * 24 * 60 * 60  # 1.5 weeks


def choose_interval(event_start, now=None):
    now = now or datetime.now(timezone.utc)

    if event_start is None:
        return UNKNOWN_DATE_INTERVAL

    # Normalize event_start to a timezone-aware datetime at midnight UTC if it's a date
    if isinstance(event_start, datetime):
        es = event_start if event_start.tzinfo else event_start.replace(tzinfo=timezone.utc)
    else:
        # If user passed a date-like object, assume midnight UTC
        es = datetime.combine(event_start, datetime.min.time()).replace(tzinfo=timezone.utc)

    delta_seconds = (es - now).total_seconds()
    if abs(delta_seconds) <= THRESHOLD_SECONDS:
        return RECENT_INTERVAL
    return DAILY_INTERVAL


def run_tests():
    # Fix 'now' for reproducible tests
    now = datetime(2025, 11, 10, 3, 30, 0, tzinfo=timezone.utc)

    cases = [
        ("unknown", None, UNKNOWN_DATE_INTERVAL),
        ("future_within_5d", now + timedelta(days=5), RECENT_INTERVAL),
        ("past_within_5d", now - timedelta(days=5), RECENT_INTERVAL),
        ("future_11d", now + timedelta(days=11), DAILY_INTERVAL),
        ("past_11d", now - timedelta(days=11), DAILY_INTERVAL),
        ("far_future_30d", now + timedelta(days=30), DAILY_INTERVAL),
        ("far_past_200d", now - timedelta(days=200), DAILY_INTERVAL),
        # User example: okok event on 2025-04-02 should be DAILY relative to our fixed now
        ("okok_2025_04_02", datetime(2025, 4, 2, tzinfo=timezone.utc), DAILY_INTERVAL),
    ]

    all_ok = True
    for name, ev_start, expected in cases:
        got = choose_interval(ev_start, now)
        ok = got == expected
        print(f"{name}: expected={expected}, got={got} -> {'PASS' if ok else 'FAIL'}")
        if not ok:
            all_ok = False

    return 0 if all_ok else 2


if __name__ == '__main__':
    rc = run_tests()
    if rc == 0:
        print("All interval checks passed.")
    else:
        print("Some interval checks failed.")
    sys.exit(rc)
