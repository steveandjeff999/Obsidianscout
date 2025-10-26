"""Score utilities shared across the app

Provides a small helper to normalize score values coming from APIs or the DB.
Negative values (commonly -1) are treated as "no score yet" and returned as None.
"""
def norm_db_score(val):
    """Normalize a score value coming from the DB/API: treat negative or invalid scores as None.

    Args:
        val: value from DB or API (int, str, None)

    Returns:
        int or None
    """
    try:
        if val is None:
            return None
        # Convert numeric-like inputs to int
        if isinstance(val, str):
            v = int(val.strip())
        else:
            v = int(val)

        if v < 0:
            return None
        return v
    except Exception:
        return None
