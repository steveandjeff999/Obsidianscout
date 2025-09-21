"""Shim for real_time_file_sync - provides no-op implementations so imports succeed.

This prevents import errors in environments where the real sync system is intentionally disabled.
"""
from typing import Any


def setup_real_time_file_sync(app: Any) -> None:
    """No-op setup function for real-time file sync."""
    # Intentionally no side-effects in the shim.
    return None


def get_file_sync_status() -> dict:
    """Return a simple status dict to indicate sync is disabled."""
    return {'enabled': False, 'status': 'disabled', 'last_sync': None}
