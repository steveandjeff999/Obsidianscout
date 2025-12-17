"""Score utilities shared across the app

Provides a small helper to normalize score values coming from APIs or the DB.
Negative values (commonly -1) are treated as "no score yet" and returned as None.
Also provides match sorting utilities for proper playoff match ordering.
"""

# Global match type ordering: Practice → Qualification → Quarterfinals → Semifinals → Finals
MATCH_TYPE_ORDER = {
    'practice': 1,
    'qualification': 2,
    'qualifier': 2,
    'quarterfinal': 3,
    'quarterfinals': 3,
    'qf': 3,
    'semifinal': 4,
    'semifinals': 4,
    'sf': 4,
    'playoff': 5,  # Generic playoff (after semis, before finals)
    'elimination': 5,
    'final': 6,
    'finals': 6,
    'f': 6,
}

def parse_match_number(match_number):
    """Parse match number which may be int, string like '5', or playoff format like '1-2'.
    Returns tuple (series_number, game_number) for sorting.
    For simple numbers: (match_number, 0)
    For 'X-Y' format: (X, Y)
    """
    if match_number is None:
        return (0, 0)
    
    try:
        # Try simple integer first
        if isinstance(match_number, int):
            return (match_number, 0)
        
        s = str(match_number).strip()
        
        # Check for 'X-Y' format (e.g., '1-2', '10-1')
        if '-' in s:
            parts = s.split('-')
            if len(parts) == 2:
                try:
                    series = int(parts[0])
                    game = int(parts[1])
                    return (series, game)
                except ValueError:
                    pass
        
        # Try parsing as simple integer
        return (int(s), 0)
    except (ValueError, TypeError):
        return (0, 0)

def match_sort_key(m):
    """Global sort key for matches: orders by match type then by match number.
    Handles playoff 'X-Y' format match numbers correctly.
    
    Order: Practice → Qualification → Quarterfinals → Semifinals → Finals
    Within each type, sorts by series number then game number (for X-Y format).
    """
    match_type = (getattr(m, 'match_type', None) or '').lower()
    type_order = MATCH_TYPE_ORDER.get(match_type, 99)
    series, game = parse_match_number(getattr(m, 'match_number', None))
    return (type_order, series, game)

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
