"""
Statbotics helper utilities — lightweight ability to pull EPA metrics from
Statbotics team pages.

This module prefers the official `statbotics` Python client when it is
installed. If the client is unavailable or does not expose expected
fields, the helper falls back to parsing the public team HTML page (no
additional dependency required).

Behavior:
- If `statbotics` client is importable, it is used first; otherwise the
  existing HTML-parsing fallback is used.
- No site routes or models are modified by this helper.

Docs: https://www.statbotics.io/docs/python
"""

from __future__ import annotations

import re
from html import unescape
from typing import Optional, Dict, Any

import requests

# Try optional official client (preferred) — fail quietly if not installed.
try:
    import statbotics as _sb_client  # type: ignore
except Exception:  # pragma: no cover - import-time fallback
    _sb_client = None

STATBOTICS_BASE = "https://www.statbotics.io"
STATBOTICS_API_BASE = "https://api.statbotics.io/v3"
_DEFAULT_TIMEOUT = 4
_USER_AGENT = "FRC-Scouting-Platform/1.0"

# In-memory EPA cache: key -> (value, last_access_time)
# value is a dict | _CACHE_MISS sentinel
_team_epa_cache: Dict[str, tuple] = {}
_CACHE_MISS = object()  # sentinel: distinguishes "tried and failed" from "never tried"
_EPA_IDLE_SECONDS = 1800          # evict entries unused for 30 min
_EPA_CLEANUP_EVERY = 200          # run eviction sweep every N accesses
_epa_access_counter = 0


def _epa_cache_get(key: str):
    """Read from L1 EPA cache, refreshing last-access time.
    Returns (value, found).
    """
    import time as _time
    global _epa_access_counter
    entry = _team_epa_cache.get(key)
    if entry is None:
        return None, False
    value, _ = entry
    _team_epa_cache[key] = (value, _time.time())
    _epa_access_counter += 1
    if _epa_access_counter >= _EPA_CLEANUP_EVERY:
        _epa_cache_evict()
    return value, True


def _epa_cache_set(key: str, value) -> None:
    """Write to L1 EPA cache, recording current time as last-access."""
    import time as _time
    global _epa_access_counter
    _team_epa_cache[key] = (value, _time.time())
    _epa_access_counter += 1
    if _epa_access_counter >= _EPA_CLEANUP_EVERY:
        _epa_cache_evict()


def _epa_cache_evict() -> None:
    """Remove entries idle for >30 min."""
    import time as _time
    global _epa_access_counter
    _epa_access_counter = 0
    now = _time.time()
    stale = [k for k, (_, ts) in list(_team_epa_cache.items())
             if now - ts > _EPA_IDLE_SECONDS]
    for k in stale:
        del _team_epa_cache[k]

# Lazily-created Statbotics client instance (reused across calls)
_sb_instance = None


class StatboticsError(Exception):
    """Raised for Statbotics-related errors (network or parsing)."""


def _get_game_config_year() -> int:
    """Return the season year from the active game config, or the current calendar year.

    This ensures Statbotics EPA lookups always target the correct FRC season
    regardless of when the server process started.
    """
    try:
        from app.utils.config_manager import get_current_game_config
        config = get_current_game_config()
        if isinstance(config, dict):
            year = config.get('season') or config.get('year')
            if year:
                return int(year)
    except Exception:
        pass
    from datetime import datetime as _dt
    return _dt.now().year


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _extract_epa_from_dict(data: Dict) -> Optional[Dict[str, Optional[float]]]:
    """Extract EPA values from a Statbotics API response dict.

    Handles multiple response shapes from different library versions and
    API endpoints.
    """
    epa = data.get("epa")
    if not isinstance(epa, dict):
        return None

    result: Dict[str, Optional[float]] = {
        "auto": None, "teleop": None, "endgame": None, "total": None,
        "rank_world": None, "rank_country": None,
    }

    # Shape A (v2 get_team_year): epa.breakdown.{auto_points, teleop_points, …}
    breakdown = epa.get("breakdown")
    if isinstance(breakdown, dict):
        result["auto"] = _safe_float(breakdown.get("auto_points"))
        result["teleop"] = _safe_float(breakdown.get("teleop_points"))
        result["endgame"] = _safe_float(breakdown.get("endgame_points"))
        result["total"] = _safe_float(breakdown.get("total_points"))

    # Shape B: epa.total_points = {mean: …}
    if result["total"] is None:
        tp = epa.get("total_points")
        if isinstance(tp, dict):
            result["total"] = _safe_float(tp.get("mean"))
        else:
            result["total"] = _safe_float(tp)

    # Shape C: epa.{auto, teleop, endgame, total} (flat)
    if result["auto"] is None:
        result["auto"] = _safe_float(epa.get("auto") or epa.get("auto_points"))
    if result["teleop"] is None:
        result["teleop"] = _safe_float(epa.get("teleop") or epa.get("teleop_points"))
    if result["endgame"] is None:
        result["endgame"] = _safe_float(epa.get("endgame") or epa.get("endgame_points"))
    if result["total"] is None:
        result["total"] = _safe_float(epa.get("total"))

    # Shape D: epa.current.{total, auto, …}
    current = epa.get("current")
    if isinstance(current, dict) and result["total"] is None:
        result["auto"] = _safe_float(current.get("auto") or current.get("auto_points"))
        result["teleop"] = _safe_float(current.get("teleop") or current.get("teleop_points"))
        result["endgame"] = _safe_float(current.get("endgame") or current.get("endgame_points"))
        result["total"] = _safe_float(current.get("total") or current.get("total_points"))

    # Ranks — epa.ranks.total.rank, epa.ranks.country.rank
    ranks = epa.get("ranks")
    if isinstance(ranks, dict):
        total_rank = ranks.get("total")
        if isinstance(total_rank, dict):
            result["rank_world"] = total_rank.get("rank")
        country_rank = ranks.get("country")
        if isinstance(country_rank, dict):
            result["rank_country"] = country_rank.get("rank")

    return result if result["total"] is not None else None


def _client_get_team_epa(team_number: int | str) -> Optional[Dict[str, Optional[float]]]:
    """Attempt to get EPA using the official ``statbotics`` client.

    Uses ``Statbotics().get_team_year(team, year)`` which returns the
    full EPA breakdown.  Falls back through current → previous year.
    """
    if not _sb_client:
        return None

    global _sb_instance
    try:
        SBClass = getattr(_sb_client, "Statbotics", None)
        if not SBClass:
            return None
        if _sb_instance is None:
            _sb_instance = SBClass()

        current_year = _get_game_config_year()

        for year in (current_year, current_year - 1):
            try:
                data = _sb_instance.get_team_year(int(team_number), year)
                if isinstance(data, dict):
                    parsed = _extract_epa_from_dict(data)
                    if parsed is not None:
                        return parsed
            except Exception:
                continue
    except Exception:
        pass
    return None


def _rest_api_get_team_epa(team_number: int | str) -> Optional[Dict[str, Optional[float]]]:
    """Fetch EPA via the Statbotics REST API (v3) as a fallback."""
    current_year = _get_game_config_year()

    for year in (current_year, current_year - 1):
        try:
            url = f"{STATBOTICS_API_BASE}/team_year/{team_number}/{year}"
            resp = requests.get(
                url,
                headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
                timeout=_DEFAULT_TIMEOUT,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            if isinstance(data, dict):
                parsed = _extract_epa_from_dict(data)
                if parsed is not None:
                    return parsed
        except Exception:
            continue
    return None


def _headers() -> Dict[str, str]:
    return {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": _USER_AGENT}


def fetch_team_page(team_number: int | str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Fetch the statbotics team page HTML for `team_number`.

    Raises StatboticsError on network errors or unexpected HTTP status.
    """
    url = f"{STATBOTICS_BASE}/team/{team_number}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=timeout)
    except requests.RequestException as e:
        raise StatboticsError(f"Request failed: {e}") from e

    if resp.status_code == 200:
        return resp.text
    if resp.status_code == 404:
        raise StatboticsError(f"Statbotics team page not found: {url}")
    raise StatboticsError(f"Statbotics returned HTTP {resp.status_code} for {url}")


def parse_team_epa(page_html: str) -> Optional[Dict[str, Optional[float]]]:
    """Parse EPA values from the raw HTML of a statbotics team page.

    Returns a dict with keys: 'auto', 'teleop', 'endgame', 'total',
    'rank_world', 'rank_country' or None if no EPA info could be found.
    """
    if not page_html:
        return None

    # Remove tags so the regex can operate on plain text.
    text = re.sub(r"<[^>]+>", " ", page_html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    # Primary pattern used on Statbotics team pages:
    # "EPA Breakdown: Auto: 5.9 Teleop: 5.9 Endgame: 5.9 Total: 17.6"
    pattern = re.compile(
        r"EPA\s+Breakdown\s*[:]?\s*Auto\s*[:]?\s*([\-\d\.]+)\s*"
        r"Teleop\s*[:]?\s*([\-\d\.]+)\s*Endgame\s*[:]?\s*([\-\d\.]+)\s*"
        r"Total\s*[:]?\s*([\-\d\.]+)",
        re.IGNORECASE,
    )

    m = pattern.search(text)
    # Fallback: some pages shorten "EPA Breakdown" to just "EPA:"
    if not m:
        fallback = re.compile(
            r"EPA\s*[:]?\s*Auto\s*[:]?\s*([\-\d\.]+)\s*"
            r"Teleop\s*[:]?\s*([\-\d\.]+)\s*Endgame\s*[:]?\s*([\-\d\.]+)\s*"
            r"Total\s*[:]?\s*([\-\d\.]+)",
            re.IGNORECASE,
        )
        m = fallback.search(text)

    if not m:
        return None

    try:
        auto_v, tele_v, end_v, total_v = (float(x) for x in m.groups())
    except Exception:
        return None

    # Optional rank extraction (e.g. "[11 Worldwide out of 3776]")
    rank_world = None
    rank_country = None

    wr = re.search(r"\[(\d+)\s+Worldwide", text, re.IGNORECASE)
    if wr:
        try:
            rank_world = int(wr.group(1))
        except Exception:
            rank_world = None

    cr = re.search(r"\[(\d+)\s+USA", text, re.IGNORECASE)
    if cr:
        try:
            rank_country = int(cr.group(1))
        except Exception:
            rank_country = None

    return {
        "auto": auto_v,
        "teleop": tele_v,
        "endgame": end_v,
        "total": total_v,
        "rank_world": rank_world,
        "rank_country": rank_country,
    }


def _db_cache_get(team_number: int | str, ttl_hours: int = 24,
                  stale_ok: bool = False) -> Optional[Dict[str, Optional[float]]]:
    """L2 cache: read from StatboticsCache DB table.

    Returns the EPA dict, ``_CACHE_MISS`` sentinel for a stored miss,
    or ``None`` if there is no valid DB entry.

    When *stale_ok* is ``True`` the TTL check is skipped and any
    previously stored row is returned.  This lets user-facing requests
    use stale DB data instantly rather than blocking on slow API calls.
    """
    try:
        from flask import current_app  # noqa: F401 – need app context
        from app.models import StatboticsCache

        year = _get_game_config_year()

        if stale_ok:
            # Accept ANY stored row regardless of age
            row = (StatboticsCache.query
                   .filter_by(team_number=int(team_number), year=year)
                   .first())
            if row is None:
                row = (StatboticsCache.query
                       .filter_by(team_number=int(team_number), year=year - 1)
                       .first())
        else:
            row = StatboticsCache.get_cached(int(team_number), year, ttl_hours=ttl_hours)
            if row is None:
                # Also check previous year
                row = StatboticsCache.get_cached(int(team_number), year - 1, ttl_hours=ttl_hours)

        if row is None:
            return None
        if row.is_miss:
            return _CACHE_MISS  # type: ignore[return-value]
        return row.to_epa_dict()
    except Exception:
        return None


def _db_cache_put(team_number: int | str, epa_dict: Optional[Dict]) -> None:
    """L2 cache: persist an EPA result (or miss) in the DB."""
    try:
        from app.models import StatboticsCache

        year = _get_game_config_year()
        StatboticsCache.upsert(int(team_number), year, epa_dict)
    except Exception:
        pass


def get_statbotics_team_epa(team_number: int | str, use_cache: bool = True) -> Optional[Dict[str, Optional[float]]]:
    """Public helper: fetch + parse EPA for a team.

    Cache hierarchy:
      L1 — in-memory dict (instant, per-process lifetime)
      L2 — DB ``statbotics_cache`` table (persists across restarts, 24 h TTL)
      L3 — Statbotics API (official client → REST → HTML scraping)

    Caches **all** results (including failures) so slow lookups only
    happen once per team per process lifetime.
    """
    key = str(team_number)

    # --- L1: in-memory cache (30-min idle TTL) ---
    if use_cache:
        cached, found = _epa_cache_get(key)
        if found:
            return None if cached is _CACHE_MISS else cached

    # --- L2: DB cache ---
    if use_cache:
        db_result = _db_cache_get(team_number)
        if db_result is _CACHE_MISS:
            _epa_cache_set(key, _CACHE_MISS)
            return None
        if db_result is not None:
            _epa_cache_set(key, db_result)
            return db_result

        # --- L2b: stale DB fallback (return old data instantly) ---
        # Rather than blocking 30 s on the Statbotics API, serve stale
        # data for user-facing requests and let the background scheduler
        # refresh later.
        stale = _db_cache_get(team_number, stale_ok=True)
        if stale is _CACHE_MISS:
            _epa_cache_set(key, _CACHE_MISS)
            return None
        if stale is not None:
            _epa_cache_set(key, stale)
            return stale

    result: Optional[Dict] = None

    # --- L3: Statbotics API ---
    # Only reached when there is *no* DB data at all (first run) or
    # when use_cache=False (background scheduler refresh).

    # 1. Official Python client (fastest — uses REST under the hood)
    try:
        result = _client_get_team_epa(team_number)
    except Exception:
        pass

    # 2. Direct REST API call (reliable JSON, no HTML parsing)
    if result is None:
        try:
            result = _rest_api_get_team_epa(team_number)
        except Exception:
            pass

    # 3. HTML scraping (last resort)
    if result is None:
        try:
            html = fetch_team_page(team_number)
            result = parse_team_epa(html)
        except Exception:
            pass

    # Store in caches — even failures — to prevent repeated slow lookups
    if use_cache:
        _epa_cache_set(key, result if result is not None else _CACHE_MISS)
        _db_cache_put(team_number, result)
    else:
        # Scheduler path (use_cache=False) — always persist to DB
        _db_cache_put(team_number, result)

    return result


def get_statbotics_team_total_epa(team_number: int | str) -> Optional[float]:
    """Convenience: return the `total` EPA for a team or None."""
    parsed = get_statbotics_team_epa(team_number)
    return parsed.get("total") if parsed else None


def clear_epa_caches() -> None:
    """Clear ALL in-memory EPA caches.

    Call this when the EPA admin setting changes so stale data is
    never served.  The DB cache (StatboticsCache) is intentionally kept
    — it stores raw API data which is source-agnostic.
    """
    global _epa_access_counter
    _team_epa_cache.clear()
    _epa_access_counter = 0
