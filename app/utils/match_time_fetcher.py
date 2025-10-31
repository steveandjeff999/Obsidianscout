"""
Match Time Fetcher
Updates match scheduled times from FIRST and TBA APIs
Properly handles timezone conversions to ensure notifications are sent at the correct local time
"""
import requests
from datetime import datetime, timezone
from flask import current_app
from app import db
from app.models import Match, Event
from app.utils.api_utils import get_api_headers, get_preferred_api_source
from app.utils.config_manager import get_current_game_config
from app.utils.timezone_utils import parse_iso_with_timezone, convert_utc_to_local


def fetch_match_times_from_first(event_code, event_timezone=None):
    """
    Fetch match scheduled times from FIRST API
    
    Args:
        event_code: Event code to fetch times for
        event_timezone: IANA timezone string for the event (e.g., 'America/Denver')
    
    Returns:
        dict mapping (match_type, match_number) -> datetime (in UTC)
    """
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    headers = get_api_headers()
    
    match_times = {}
    
    # Schedule endpoints for different match types
    endpoints = [
        (f"/v2.0/{season}/schedule/{event_code}/qual", 'Qualification'),
        (f"/v2.0/{season}/schedule/{event_code}/playoff", 'Playoff'),
        (f"/v2.0/{season}/schedule/{event_code}/practice", 'Practice'),
    ]
    
    for endpoint, match_type in endpoints:
        try:
            api_url = f"{base_url}{endpoint}"
            response = requests.get(api_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                matches = data.get('Schedule', [])
                
                for match_data in matches:
                    match_num = match_data.get('matchNumber')
                    scheduled_time_str = match_data.get('startTime')
                    
                    if match_num and scheduled_time_str:
                        try:
                            # Parse ISO 8601 format: "2024-03-15T09:30:00"
                            # FIRST API has historically returned both naive-local and tz-aware
                            # strings. We should NOT assume the event timezone for naive
                            # strings by default because some endpoints actually return UTC
                            # values without a tz marker. Strategy:
                            # 1. Try parsing as-is (if string includes Z or offset it'll be
                            #    treated as UTC-aware by the parser).
                            # 2. If parsing yields a naive datetime, treat it as UTC first
                            #    (do NOT force event timezone).
                            # 3. If that fails and we have an event timezone, fall back to
                            #    parsing as local event time (best-effort for older APIs).
                            scheduled_time = parse_iso_with_timezone(scheduled_time_str, None)

                            if scheduled_time is None and event_timezone:
                                # Fallback: try parsing assuming the event local timezone
                                scheduled_time = parse_iso_with_timezone(scheduled_time_str, event_timezone)
                                if scheduled_time:
                                    print(f"️  FIRST: parsed naive time '{scheduled_time_str}' using event timezone fallback {event_timezone}: {scheduled_time.isoformat()}")
                            elif scheduled_time:
                                # Normal case: parsed as-aware or assumed-UTC
                                print(f" FIRST: parsed time '{scheduled_time_str}' -> {scheduled_time.isoformat()}")

                            if scheduled_time:
                                match_times[(match_type, match_num)] = scheduled_time
                        except Exception as e:
                            print(f"Error parsing time '{scheduled_time_str}': {e}")
                
                print(f" Fetched {len(matches)} {match_type} match times from FIRST API")
            else:
                print(f"️  FIRST API returned {response.status_code} for {endpoint}")
                
        except Exception as e:
            print(f" Error fetching match times from FIRST API: {e}")
    
    return match_times


def fetch_match_times_from_tba(event_code, event_timezone=None):
    """
    Fetch match scheduled/predicted times from The Blue Alliance API
    
    Args:
        event_code: Event code to fetch times for
        event_timezone: Not used - TBA provides Unix timestamps which are already UTC
    
    Returns:
        dict mapping (match_type, match_number) -> (scheduled_time, predicted_time) (both in UTC)
    """
    from app.utils.tba_api_utils import get_tba_api_headers, construct_tba_event_key
    
    base_url = 'https://www.thebluealliance.com/api/v3'
    year = get_current_game_config().get('season', 2026)
    
    # Construct TBA event key
    event_key = construct_tba_event_key(event_code, year)
    
    match_times = {}
    
    try:
        api_url = f"{base_url}/event/{event_key}/matches"
        response = requests.get(api_url, headers=get_tba_api_headers(), timeout=15)
        
        if response.status_code == 200:
            matches = response.json()
            
            # Map TBA comp_level to our match_type
            comp_level_map = {
                'qm': 'Qualification',
                'ef': 'Elimination',
                'qf': 'Quarterfinals',
                'sf': 'Semifinals',
                'f': 'Finals',
                'pr': 'Practice'
            }
            
            for match_data in matches:
                comp_level = match_data.get('comp_level', 'qm')
                match_num = match_data.get('match_number')
                match_type = comp_level_map.get(comp_level, 'Qualification')
                
                # TBA provides time, actual_time, and predicted_time as Unix timestamps (UTC)
                # time = scheduled time for the match
                # actual_time = when the match actually started (only set after match plays)
                # predicted_time = TBA's prediction of when match will start
                scheduled_time = match_data.get('time')  # Unix timestamp
                actual_time = match_data.get('actual_time')  # Unix timestamp
                predicted_time = match_data.get('predicted_time')  # Unix timestamp
                
                scheduled = None
                predicted = None
                
                # For schedule adjustment: prefer actual_time if available (match already played)
                # This lets us compare scheduled vs actual to detect schedule delays
                # If match is complete (has actual_time), use that as the "scheduled" time
                # so schedule_adjuster can compare it against the original scheduled time
                if actual_time:
                    try:
                        # Match was actually played at this time - use for schedule delay detection
                        scheduled = datetime.fromtimestamp(actual_time, tz=timezone.utc)
                    except Exception as e:
                        print(f"Error parsing actual_time {actual_time}: {e}")
                elif scheduled_time:
                    try:
                        # Match hasn't been played yet, use scheduled time
                        scheduled = datetime.fromtimestamp(scheduled_time, tz=timezone.utc)
                    except Exception as e:
                        print(f"Error parsing time {scheduled_time}: {e}")
                
                if predicted_time:
                    try:
                        # Unix timestamps are in UTC, create timezone-aware datetime
                        predicted = datetime.fromtimestamp(predicted_time, tz=timezone.utc)
                    except Exception as e:
                        print(f"Error parsing predicted_time {predicted_time}: {e}")
                
                if scheduled or predicted:
                    match_times[(match_type, match_num)] = (scheduled, predicted)
            
            print(f" Fetched {len(matches)} match times from TBA")
        else:
            print(f"️  TBA API returned {response.status_code}")
            
    except Exception as e:
        print(f" Error fetching match times from TBA: {e}")
    
    return match_times


def update_match_times(event_code, scouting_team_number=None):
    """
    Update scheduled times for all matches at an event
    Times are fetched from APIs in event local timezone and converted to UTC for storage
    
    Args:
        event_code: Event code to update
        scouting_team_number: Optional team number to scope update
        
    Returns:
        Number of matches updated
    """
    print(f"\n Updating match times for event {event_code}...")
    
    # Get event from database first to get timezone info
    query = Event.query.filter_by(code=event_code)
    if scouting_team_number:
        query = query.filter_by(scouting_team_number=scouting_team_number)
    
    event = query.first()
    if not event:
        print(f" Event {event_code} not found in database")
        return 0
    
    # Get event timezone for proper conversion
    event_timezone = event.timezone
    if event_timezone:
        print(f" Event timezone: {event_timezone}")
    else:
        print(f"️  No timezone set for event, times will be treated as UTC")
    
    # Get preferred API source
    preferred_api = get_preferred_api_source()
    
    # Fetch times from APIs (passing timezone for proper parsing)
    first_times = {}
    tba_times = {}
    
    if preferred_api == 'first':
        first_times = fetch_match_times_from_first(event_code, event_timezone)
        if not first_times:
            # Fallback to TBA
            print("️  No times from FIRST API, trying TBA...")
            tba_times = fetch_match_times_from_tba(event_code, event_timezone)
    else:
        tba_times = fetch_match_times_from_tba(event_code, event_timezone)
        if not tba_times:
            # Fallback to FIRST
            print("️  No times from TBA, trying FIRST API...")
            first_times = fetch_match_times_from_first(event_code, event_timezone)
    
    # Get all matches for this event
    matches = Match.query.filter_by(event_id=event.id).all()
    
    updated_count = 0
    
    for match in matches:
        match_key = (match.match_type, match.match_number)
        
        updated = False
        
        # Update from FIRST API times (already in UTC from our parser)
        if match_key in first_times:
            scheduled_time = first_times[match_key]
            # Normalize to naive UTC for DB storage (SQLite stores naive datetimes)
            try:
                if scheduled_time is not None and scheduled_time.tzinfo is not None:
                    scheduled_naive = scheduled_time.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    scheduled_naive = scheduled_time
            except Exception:
                scheduled_naive = scheduled_time

            if match.scheduled_time != scheduled_naive:
                print(f"⏬ Updating Match {match.match_type}#{match.match_number} scheduled_time -> {scheduled_naive} (naive UTC)")
                match.scheduled_time = scheduled_naive
                updated = True
        
        # Update from TBA times (already in UTC)
        if match_key in tba_times:
            scheduled, predicted = tba_times[match_key]

            # Normalize TBA times (they are timezone-aware UTC) to naive UTC for DB
            try:
                if scheduled is not None and scheduled.tzinfo is not None:
                    scheduled_naive = scheduled.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    scheduled_naive = scheduled
            except Exception:
                scheduled_naive = scheduled

            try:
                if predicted is not None and predicted.tzinfo is not None:
                    predicted_naive = predicted.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    predicted_naive = predicted
            except Exception:
                predicted_naive = predicted

            if scheduled_naive and match.scheduled_time != scheduled_naive:
                print(f"⏬ Updating Match {match.match_type}#{match.match_number} scheduled_time -> {scheduled_naive} (naive UTC)")
                match.scheduled_time = scheduled_naive
                updated = True

            if predicted_naive and match.predicted_time != predicted_naive:
                print(f"⏬ Updating Match {match.match_type}#{match.match_number} predicted_time -> {predicted_naive} (naive UTC)")
                match.predicted_time = predicted_naive
                updated = True
        
        if updated:
            updated_count += 1
    
    if updated_count > 0:
        db.session.commit()
        print(f" Updated times for {updated_count} matches (stored in UTC)")
    else:
        print(f"ℹ️  No match time updates needed")
    
    return updated_count


def normalize_event_match_times(event_code, dry_run=True):
    """
    Normalize stored match datetimes for a single event.

    Heuristic:
    - Some installations have stored naive datetimes that actually represent
      the event-local time (no tzinfo). This function will try two
      interpretations for each naive datetime:
        A) Treat as UTC (dt_utc = naive.replace(tzinfo=UTC))
        B) Treat as event-local (dt_alt = convert_local_to_utc(naive, event.timezone))
    - If interpretation B maps to a local date within the event dates and A does not,
      we assume the value was stored as local and convert it to naive UTC for DB.

    Args:
        event_code: Event code to normalize (string)
        dry_run: If True, do not write changes to DB; instead return a report.

    Returns:
        dict with keys: 'event_code', 'checked', 'would_fix', 'fixed' (counts)
    """
    from app.models import Event, Match
    from app import db
    from datetime import timezone as _tz

    event = Event.query.filter_by(code=event_code).first()
    if not event:
        print(f" Event {event_code} not found")
        return {'event_code': event_code, 'checked': 0, 'would_fix': 0, 'fixed': 0}

    matches = Match.query.filter_by(event_id=event.id).all()
    checked = 0
    would_fix = 0
    fixed = 0

    for m in matches:
        for field in ('scheduled_time', 'predicted_time'):
            dt = getattr(m, field)
            if not dt:
                continue
            checked += 1

            # If the datetime already has tzinfo, assume it's correct (UTC-aware)
            if getattr(dt, 'tzinfo', None) is not None:
                continue

            # Interpretation A: treat as UTC
            try:
                dt_a = dt.replace(tzinfo=_tz.utc)
                local_a = None
                if event.timezone:
                    local_a = convert_utc_to_local(dt_a, event.timezone)
            except Exception:
                dt_a = None
                local_a = None

            # Interpretation B: treat as event-local
            dt_b = None
            local_b = None
            if event.timezone:
                try:
                    dt_b = convert_local_to_utc(dt, event.timezone)
                    local_b = convert_utc_to_local(dt_b, event.timezone)
                except Exception:
                    dt_b = None
                    local_b = None

            # Helper to check if local datetime falls within event start/end date
            def in_event_date(local_dt):
                if not local_dt or not event.start_date:
                    return False
                try:
                    return event.start_date <= local_dt.date() <= (event.end_date or event.start_date)
                except Exception:
                    return False

            a_in = in_event_date(local_a)
            b_in = in_event_date(local_b)

            # Decide: if B maps into event and A does not, we should fix
            if b_in and not a_in:
                would_fix += 1
                print(f"️  Would fix Match {m.match_type}#{m.match_number} field {field}: naive stored {dt} interpreted as local {event.timezone} -> UTC {dt_b}")
                if not dry_run:
                    # Store as naive UTC (DB convention)
                    try:
                        setattr(m, field, dt_b.replace(tzinfo=None))
                        fixed += 1
                    except Exception as e:
                        print(f" Failed to fix match {m.id} {field}: {e}")

    if not dry_run and fixed > 0:
        db.session.commit()

    return {'event_code': event_code, 'checked': checked, 'would_fix': would_fix, 'fixed': fixed}


def update_all_active_event_times():
    """
    Update match times for all active events across all scouting teams
    
    Returns:
        Total number of matches updated
    """
    from app.utils.config_manager import load_game_config
    from app.models import User
    
    total_updated = 0
    
    # Get all unique scouting teams
    team_numbers = set()
    try:
        for rec in User.query.with_entities(User.scouting_team_number).filter(
            User.scouting_team_number.isnot(None)
        ).distinct().all():
            if rec[0] is not None:
                team_numbers.add(rec[0])
    except Exception:
        pass
    
    # For each scouting team, check their configured event
    for team_number in sorted(team_numbers):
        try:
            game_config = load_game_config(team_number=team_number)
            event_code = game_config.get('current_event_code')
            
            if event_code:
                print(f"\n Processing team {team_number}, event {event_code}")
                updated = update_match_times(event_code, team_number)
                total_updated += updated
        except Exception as e:
            print(f" Error updating times for team {team_number}: {e}")
    
    return total_updated
