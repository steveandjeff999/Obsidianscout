"""Utilities for working with scouting team numbers.

Provides a robust sort key for team numbers that may be ints, numeric strings,
non-numeric strings, or None. This prevents TypeError when sorting mixed types
on different servers where data may be stored differently.
"""
from typing import Any


def team_sort_key(x: Any):
    """Return a tuple key that sorts values as:

    1) Numeric team numbers (0, int value)
    2) Non-numeric strings (1, string value)
    3) None values last (2, '')

    This ensures comparisons never try to compare ints and strs directly.
    """
    if x is None:
        return (2, "")

    # Numeric (int or numeric string)
    try:
        return (0, int(x))
    except Exception:
        # Fallback: non-numeric string
        return (1, str(x))
