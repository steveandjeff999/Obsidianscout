"""Utilities for robust event-code normalization and matching.

These helpers keep legacy raw codes (e.g. ``ARLI``) and modern
year-prefixed codes (e.g. ``2026ARLI``) interoperable across the app.
"""


def normalize_event_code(value):
    """Return a normalized uppercase event code string.

    Also heals malformed duplicated-year prefixes such as ``20262026ARLI``.
    """
    if value is None:
        return ""

    try:
        code = str(value).strip().upper()
    except Exception:
        return ""

    if not code:
        return ""

    # Heal repeated year prefixes: 20262026ARLI -> 2026ARLI.
    # Loop handles pathological repeats like 202620262026ARLI.
    while len(code) >= 8 and code[:4].isdigit() and code[4:8] == code[:4]:
        code = code[:4] + code[8:]

    return code


def split_event_code(code):
    """Split a normalized event code into (year_prefix, raw_code).

    Returns:
    - (year:int, raw:str) for year-prefixed codes
    - (None, normalized_code) for raw/non-prefixed codes
    """
    normalized = normalize_event_code(code)
    if len(normalized) > 4 and normalized[:4].isdigit():
        return int(normalized[:4]), normalized[4:]
    return None, normalized


def build_year_prefixed_event_code(code, season=None):
    """Return a year-prefixed code when possible.

    If ``code`` is already prefixed it is returned normalized.
    If ``season`` is unavailable/invalid, returns normalized ``code``.
    """
    normalized = normalize_event_code(code)
    if not normalized:
        return ""

    year_prefix, raw_code = split_event_code(normalized)
    if year_prefix is not None:
        return f"{year_prefix}{raw_code}" if raw_code else normalized

    try:
        season_int = int(season)
    except (TypeError, ValueError):
        return normalized

    return f"{season_int}{normalized}"


def normalize_current_event_code_for_config(event_code, season=None):
    """Normalize the current event code for config persistence.

    Preference:
    - Keep raw code for the active season (prevents double-prefix bugs).
    - Keep explicit year-prefixed codes for non-active seasons.
    - Always uppercase/trim and heal duplicated year prefixes.
    """
    normalized = normalize_event_code(event_code)
    if not normalized:
        return normalized

    year_prefix, raw_code = split_event_code(normalized)
    if year_prefix is None or not raw_code:
        return normalized

    try:
        if season is not None and int(season) == year_prefix:
            return raw_code
    except (TypeError, ValueError):
        pass

    return normalized


def event_code_variants(code, season=None):
    """Return ordered unique variants for robust event-code lookup.

    Examples:
    - ``ARLI`` + season 2026 -> ["ARLI", "2026ARLI"]
    - ``2026ARLI`` -> ["2026ARLI", "ARLI"]
    - ``20262026ARLI`` -> ["2026ARLI", "ARLI"]
    """
    normalized = normalize_event_code(code)
    if not normalized:
        return []

    variants = []
    seen = set()

    def _add(value):
        if not value:
            return
        if value in seen:
            return
        seen.add(value)
        variants.append(value)

    _add(normalized)

    year_prefix, raw_code = split_event_code(normalized)
    if year_prefix is not None and raw_code:
        _add(raw_code)
    else:
        prefixed = build_year_prefixed_event_code(normalized, season=season)
        if prefixed and prefixed != normalized:
            _add(prefixed)

    return variants
