"""
Helpers to compute per-event dynamic predicted-time offsets based on recent matches.
"""
from datetime import timedelta
import statistics
from app.utils.timezone_utils import convert_local_to_utc


def compute_event_dynamic_offset_minutes(event, matches, lookback=10):
    """
    Compute a dynamic offset (in minutes) for an event based on recent completed matches.
    Offset = median(actual_time - predicted_time) in minutes. Positive means matches are running late and
    predicted times should be increased by this many minutes.

    Args:
        event: Event model instance (may be None)
        matches: iterable of Match objects (preferably sorted most-recent-first)
        lookback: how many completed matches to use

    Returns:
        integer offset in minutes (can be negative), 0 if insufficient data
    """
    deltas = []
    count = 0

    for m in matches:
        if count >= lookback:
            break
        try:
            actual = getattr(m, 'actual_time', None)
            pred = getattr(m, 'predicted_time', None)
            if not actual or not pred:
                continue
            # Convert both to UTC using event timezone for predicted (if needed)
            try:
                pred_utc = convert_local_to_utc(pred, event.timezone if event and getattr(event, 'timezone', None) else None)
            except Exception:
                pred_utc = pred
            try:
                # actual may already be stored in UTC or be timezone-aware; ensure tz-aware
                if actual.tzinfo is None:
                    # assume actual is in UTC
                    actual_utc = actual.replace(tzinfo=None)
                else:
                    actual_utc = actual
            except Exception:
                actual_utc = actual

            # compute delta minutes
            delta = (actual_utc - pred_utc).total_seconds() / 60.0
            # ignore outliers larger than a day
            if abs(delta) > 24 * 60:
                continue
            deltas.append(delta)
            count += 1
        except Exception:
            continue

    if not deltas:
        return 0
    try:
        med = statistics.median(deltas)
        return int(round(med))
    except Exception:
        # fallback to mean
        try:
            return int(round(sum(deltas) / len(deltas)))
        except Exception:
            return 0
