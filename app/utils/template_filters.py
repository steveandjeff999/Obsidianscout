"""
Template filters for the application
"""
import json
from datetime import datetime, timezone
from app.utils.timezone_utils import convert_utc_to_local, format_time_with_timezone

def init_app(app):
    """Register template filters with the Flask app"""
    @app.template_filter('prettify_json')
    def prettify_json(value):
        """Format JSON string with proper indentation"""
        try:
            if value:
                parsed = json.loads(value)
                return json.dumps(parsed, indent=2)
            return "{}"
        except Exception:
            return value

    @app.template_filter('format_time_tz')
    def format_time_tz(dt, event_timezone=None, format_str='%I:%M %p'):
        """
        Format a datetime with timezone information
        """
        if dt is None:
            return ""
        return format_time_with_timezone(dt, event_timezone, format_str)

    @app.template_filter('is_starting_soon')
    def is_starting_soon(match, event_timezone=None, adjusted_dt=None):
        """
        Return True if the match's next scheduled/predicted time is within a short window around now
        and the match has not finished.

        adjusted_dt: optional datetime which already includes any dynamic offset; if provided it is used
        in preference to match.predicted_time.
        """
        from datetime import datetime, timezone
        from app.utils.timezone_utils import convert_local_to_utc

        if not match:
            return False

        # If match has actual_time or a winner or scored non-negative values, it's finished
        finished = bool(
            getattr(match, 'actual_time', None)
            or getattr(match, 'winner', None)
            or ((getattr(match, 'red_score', None) is not None and getattr(match, 'red_score', None) >= 0)
                or (getattr(match, 'blue_score', None) is not None and getattr(match, 'blue_score', None) >= 0))
        )

        if finished:
            return False

        # Prefer adjusted_dt (already offset), otherwise predicted_time, otherwise scheduled_time with schedule_offset
        dt = adjusted_dt or getattr(match, 'predicted_time', None)
        if dt is None:
            sched = getattr(match, 'scheduled_time', None)
            if sched is None:
                return False
            # Apply event schedule_offset if present
            try:
                offset_minutes = int(getattr(match.event, 'schedule_offset', 0) or 0)
            except Exception:
                offset_minutes = 0
            if offset_minutes:
                from datetime import timedelta
                dt = sched + timedelta(minutes=offset_minutes)
            else:
                dt = sched

        try:
            match_time_utc = convert_local_to_utc(dt, event_timezone)
        except Exception:
            try:
                match_time_utc = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return False

        now_utc = datetime.now(timezone.utc)

        # Window: 5 minutes before to 30 minutes after match_time
        try:
            from datetime import timedelta
            window_before = timedelta(minutes=5)
            window_after = timedelta(minutes=30)
            return (now_utc >= (match_time_utc - window_before)) and (now_utc <= (match_time_utc + window_after))
        except Exception:
            return now_utc > match_time_utc

    # Also expose as a template global function for direct calls in templates
    try:
        app.add_template_global(is_starting_soon, name='is_starting_soon')
    except Exception:
        app.jinja_env.globals['is_starting_soon'] = is_starting_soon

    @app.template_filter('to_local_tz')
    def to_local_tz(dt_utc, event_timezone):
        """
        Convert UTC datetime to event local timezone
        """
        if dt_utc is None or not event_timezone:
            return dt_utc
        return convert_utc_to_local(dt_utc, event_timezone)

    @app.template_filter('dedupe_events')
    def dedupe_events(events):
        """
        Deduplicate a list of events for template rendering.

        Rules:
        - Events are considered duplicates when they share the same event code (case-insensitive)
          and the same alliance status.
        - If there are two entries with the same code but different alliance status, both should remain
          (do not dedupe alliance vs non-alliance events of the same code).
        - If code is not present, fall back to ID-based uniqueness.
        """
        try:
            # Precompute shared event codes to ensure we treat alliance-labeled events properly
            try:
                from app.utils.team_isolation import get_alliance_shared_event_codes, get_current_scouting_team_number
                shared_codes = set([str(c).strip().upper() for c in (get_alliance_shared_event_codes() or []) if isinstance(c, str)])
                current_team = get_current_scouting_team_number()
            except Exception:
                shared_codes = set()
                current_team = None
            unique = []
            seen = set()
            for ev in (events or []):
                # Normalize code (case-insensitive) and fallback to name+year if absent
                code = None
                if hasattr(ev, 'code'):
                    code = getattr(ev, 'code')
                elif isinstance(ev, dict):
                    code = ev.get('code')
                code_key = ''
                if code:
                    code_key = str(code).strip().upper()
                else:
                    # Fallback to name+year normalization when code is missing
                    name = getattr(ev, 'name', '') if not isinstance(ev, dict) else ev.get('name', '')
                    year = getattr(ev, 'year', '') if not isinstance(ev, dict) else ev.get('year', '')
                    code_key = f'NAME:{str(name).strip().upper()}|{str(year)}'

                # Determine alliance flag
                is_alliance = False
                # If the event object has an explicit 'is_alliance' flag, use it
                if hasattr(ev, 'is_alliance'):
                    is_alliance = bool(getattr(ev, 'is_alliance'))
                elif isinstance(ev, dict):
                    is_alliance = bool(ev.get('is_alliance', False))
                # Determine if the event should be considered an alliance event by code
                try:
                    ev_code = getattr(ev, 'code', None) if not isinstance(ev, dict) else ev.get('code')
                    event_sc_tn = getattr(ev, 'scouting_team_number', None) if not isinstance(ev, dict) else ev.get('scouting_team_number')
                    if ev_code and str(ev_code).upper() in shared_codes:
                        # If event belongs to the current user's team, mark as non-alliance copy
                        if current_team is not None and event_sc_tn == current_team:
                            # keep as non-alliance (explicit local copy)
                            pass
                        else:
                            is_alliance = True
                except Exception:
                    pass

                key = (code_key, bool(is_alliance))
                if key not in seen:
                    seen.add(key)
                    unique.append(ev)
            return unique
        except Exception:
            # On any failure, return events as-is to avoid breaking templates
            return events or []
