import threading
from datetime import datetime, timezone

# Shared in-memory sync status for background worker and HTTP endpoints.
# This keeps last autosync times and a cached copy of team event config
# so we don't reload configs too frequently. Thread-safe access via lock.

_lock = threading.Lock()

# Map: scouting_team_number -> datetime of last successful autosync (UTC)
last_sync_times = {}

# Map: scouting_team_number -> {
#   'event_code': str or None,
#   'start_date': date or datetime or None,
#   'checked_at': datetime UTC when this cache was refreshed,
#   'desired_interval': int seconds
# }
event_cache = {}


def update_last_sync(team_number):
    with _lock:
        last_sync_times[team_number] = datetime.now(timezone.utc)


def get_last_sync(team_number):
    with _lock:
        return last_sync_times.get(team_number)


def set_event_cache(team_number, event_code, start_date, desired_interval):
    with _lock:
        event_cache[team_number] = {
            'event_code': event_code,
            'start_date': start_date,
            'checked_at': datetime.now(timezone.utc),
            'desired_interval': desired_interval
        }


def get_event_cache(team_number):
    with _lock:
        return event_cache.get(team_number)


def get_all_status():
    """Return a snapshot of all tracking info for consumption by routes."""
    with _lock:
        # shallow copy
        return {
            'last_sync_times': dict(last_sync_times),
            'event_cache': dict(event_cache)
        }
