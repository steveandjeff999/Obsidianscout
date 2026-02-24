from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import Match, Event, Team, ScoutingData, AllianceSharedScoutingData
from app import db
from app.utils.api_utils import get_matches, ApiError, api_to_db_match_conversion, get_matches_dual_api
from app.utils.score_utils import norm_db_score, match_sort_key, parse_match_number, MATCH_TYPE_ORDER
from datetime import datetime, timezone
from app.utils.timezone_utils import convert_local_to_utc, utc_now_iso
from app.utils.prediction_offsets import compute_event_dynamic_offset_minutes
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_effective_game_config
from flask_socketio import emit, join_room, leave_room
from app.models import StrategyDrawing
from app import socketio
import os
from flask import send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image
import io
from app.utils.alliance_data import get_active_alliance_id, get_all_scouting_data, get_all_matches_for_alliance
from app.utils.team_isolation import (
    filter_matches_by_scouting_team, filter_events_by_scouting_team,
    filter_teams_by_scouting_team, assign_scouting_team_to_model, get_event_by_code,
    get_all_teams_at_event
)
from app.utils.team_isolation import get_combined_dropdown_events
from sqlalchemy import or_

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }


# (score normalization and match sorting is provided by app.utils.score_utils)

bp = Blueprint('matches', __name__, url_prefix='/matches')

@bp.route('/')
@analytics_required
def index():
    """Display matches for the current event from configuration"""
    # Get event code from config
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    if current_event_code:
        current_event_code = str(current_event_code).strip()
    
    # Get the current event
    event = None
    event_id = request.args.get('event_id', type=int)
    
    if event_id:
        # If a specific event ID is requested, use that (filtered by scouting team)
        event = filter_events_by_scouting_team().filter(Event.id == event_id).first()
        if not event:
            flash("Event not found or not accessible.", "error")
            return redirect(url_for('matches.index'))
    elif current_event_code:
        # Otherwise use the current event from config (filtered by scouting team)
        event = get_event_by_code(current_event_code)
    
    # Get all events for the dropdown (combined/deduped like /events)
    events = get_combined_dropdown_events()

    # Handle raw event_id URL params that may use synthetic ids (like 'alliance_CODE') or event codes
    force_selected_event = False
    try:
        raw_event_param = request.args.get('event_id')
        if raw_event_param and events:
            if isinstance(raw_event_param, str):
                if raw_event_param.startswith('alliance_'):
                    evt = next((e for e in events if str(getattr(e, 'id', '')) == raw_event_param), None)
                    if evt:
                        event = evt
                else:
                    # If a code string was passed, match by code
                    code_up = raw_event_param.upper()
                    evt = next((e for e in events if (getattr(e, 'code', '') or '').upper() == code_up), None)
                    if evt:
                        event = evt
    except Exception:
        pass

    # Prefer synthetic alliance entry for current_event_code when present (override local copy when alliance active)
    try:
        # Only auto-override with the alliance/current_event when the user did NOT explicitly request an event
        if not request.args.get('event_id') and current_event_code and events and get_active_alliance_id():
            code_up = str(current_event_code).upper()
            evt = next((e for e in events if getattr(e, 'is_alliance', False) and (getattr(e, 'code', '') or '').upper() == code_up), None)
            if evt:
                # No explicit event requested; use the synthetic alliance entry
                event = evt
    except Exception:
        pass

    # If no event selected and we're not in alliance mode, default to the current team's most-recent event
    try:
        if not event and not get_active_alliance_id():
            team_event = filter_events_by_scouting_team().order_by(
                Event.year.desc(), 
                Event.start_date.desc(), 
                Event.id.desc()
            ).first()
            if team_event:
                event = team_event
    except Exception:
        pass

    # Ensure selected_event matches an entry from the events dropdown list
    # This is critical for proper dropdown selection in the template
    selected_event_for_dropdown = None
    if event and events:
        try:
            # Check if we're in alliance mode
            alliance_id = get_active_alliance_id()
            is_in_alliance_mode = alliance_id is not None
            
            # Try to find the event in the dropdown list by matching ID or code
            event_id_to_match = getattr(event, 'id', None)
            event_code_to_match = (getattr(event, 'code', '') or '').upper()
            
            # Collect all matching events, then pick the best one
            matching_events = []
            for dropdown_evt in events:
                dropdown_id = getattr(dropdown_evt, 'id', None)
                dropdown_code = (getattr(dropdown_evt, 'code', '') or '').upper()
                is_alliance_evt = getattr(dropdown_evt, 'is_alliance', False)
                
                # Check if this event matches by ID or code
                if (event_id_to_match and dropdown_id == event_id_to_match) or \
                   (event_code_to_match and dropdown_code == event_code_to_match):
                    matching_events.append(dropdown_evt)
            
            # Prefer alliance events when in alliance mode, non-alliance events otherwise
            if matching_events:
                for evt in matching_events:
                    is_alliance_evt = getattr(evt, 'is_alliance', False)
                    if is_in_alliance_mode and is_alliance_evt:
                        selected_event_for_dropdown = evt
                        break
                    elif not is_in_alliance_mode and not is_alliance_evt:
                        selected_event_for_dropdown = evt
                        break
                # Fallback to first match if preference not found
                if not selected_event_for_dropdown:
                    selected_event_for_dropdown = matching_events[0]
            
            # Fallback: if not found, use the event itself
            if not selected_event_for_dropdown:
                selected_event_for_dropdown = event
        except Exception:
            selected_event_for_dropdown = event
    else:
        selected_event_for_dropdown = event

    # Filter matches by the selected event and scouting team
    if event:
        # Check for alliance mode
        alliance_id = get_active_alliance_id()
        
        if alliance_id:
            # Alliance mode - get matches from alliance scouting data for this event
            matches, _ = get_all_matches_for_alliance(event_id=event.id)
            # Keep the list of matches provided by the helper (it may have times populated in-memory)
        else:
            # Build base query for this event (filtered by scouting team)
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func
            from app.utils.team_isolation import get_current_scouting_team_number
            event_code = getattr(event, 'code', None)
            current_scouting_team = get_current_scouting_team_number()
            
            if event_code:
                query = filter_matches_by_scouting_team().join(
                    Event, Match.event_id == Event.id
                ).filter(func.upper(Event.code) == event_code.upper())
            else:
                query = filter_matches_by_scouting_team().filter(Match.event_id == event.id)
            
            # Defensive check: ensure we only show matches for current scouting team
            if current_scouting_team is not None:
                query = query.filter(Match.scouting_team_number == current_scouting_team)
            else:
                query = query.filter(Match.scouting_team_number.is_(None))

        # Apply optional filters from the request
        q = (request.args.get('q') or '').strip()
        match_type = (request.args.get('match_type') or '').strip()

        if alliance_id:
            # We're operating on a Python list of Match objects (already loaded)
            if match_type:
                matches = [m for m in matches if (m.match_type or '').lower() == match_type.lower()]
            if q:
                if q.isdigit():
                    qnum = int(q)
                    matches = [m for m in matches if (m.match_number == qnum or (m.red_alliance and q in m.red_alliance) or (m.blue_alliance and q in m.blue_alliance))]
                else:
                    matches = [m for m in matches if ((m.red_alliance and q.lower() in m.red_alliance.lower()) or (m.blue_alliance and q.lower() in m.blue_alliance.lower()))]
        else:
            if match_type:
                # Case-insensitive match type filtering
                try:
                    query = query.filter(Match.match_type.ilike(match_type))
                except Exception:
                    # Fallback to exact compare if ilike not available
                    query = query.filter(Match.match_type == match_type)

            if q:
                # If numeric, allow matching by match number OR team numbers in alliances
                if q.isdigit():
                    try:
                        qnum = int(q)
                        query = query.filter(or_(Match.match_number == qnum,
                                                  Match.red_alliance.like(f"%{q}%"),
                                                  Match.blue_alliance.like(f"%{q}%")))
                    except Exception:
                        query = query.filter(or_(Match.red_alliance.ilike(f"%{q}%"), Match.blue_alliance.ilike(f"%{q}%")))
                else:
                    query = query.filter(or_(Match.red_alliance.ilike(f"%{q}%"), Match.blue_alliance.ilike(f"%{q}%")))

            # Execute query and sort in Python using our custom ordering
            matches = query.all()

        # Use global match_sort_key for proper ordering (handles X-Y playoff format)
        matches = sorted(matches, key=match_sort_key)
    else:
        # No event selected - show all matches for the scouting team (All Events option)
        alliance_id = get_active_alliance_id()
        from app.utils.team_isolation import get_current_scouting_team_number
        current_scouting_team = get_current_scouting_team_number()
        
        if alliance_id:
            # Alliance mode - get all matches from alliance scouting data
            matches, _ = get_all_matches_for_alliance()
        else:
            # Build base query for all matches (filtered by scouting team)
            query = filter_matches_by_scouting_team()
            
            # Defensive check: ensure we only show matches for current scouting team
            if current_scouting_team is not None:
                query = query.filter(Match.scouting_team_number == current_scouting_team)
            else:
                query = query.filter(Match.scouting_team_number.is_(None))
        
        # Apply optional filters from the request
        q = (request.args.get('q') or '').strip()
        match_type = (request.args.get('match_type') or '').strip()

        if alliance_id:
            # We're operating on a Python list of Match objects (already loaded)
            if match_type:
                matches = [m for m in matches if (m.match_type or '').lower() == match_type.lower()]
            if q:
                if q.isdigit():
                    qnum = int(q)
                    matches = [m for m in matches if (m.match_number == qnum or (m.red_alliance and q in m.red_alliance) or (m.blue_alliance and q in m.blue_alliance))]
                else:
                    matches = [m for m in matches if ((m.red_alliance and q.lower() in m.red_alliance.lower()) or (m.blue_alliance and q.lower() in m.blue_alliance.lower()))]
        else:
            if match_type:
                # Case-insensitive match type filtering
                try:
                    query = query.filter(Match.match_type.ilike(match_type))
                except Exception:
                    # Fallback to exact compare if ilike not available
                    query = query.filter(Match.match_type == match_type)

            if q:
                # If numeric, allow matching by match number OR team numbers in alliances
                if q.isdigit():
                    try:
                        qnum = int(q)
                        query = query.filter(or_(Match.match_number == qnum,
                                                  Match.red_alliance.like(f"%{q}%"),
                                                  Match.blue_alliance.like(f"%{q}%")))
                    except Exception:
                        query = query.filter(or_(Match.red_alliance.ilike(f"%{q}%"), Match.blue_alliance.ilike(f"%{q}%")))
                else:
                    query = query.filter(or_(Match.red_alliance.ilike(f"%{q}%"), Match.blue_alliance.ilike(f"%{q}%")))

            # Execute query and sort in Python using our custom ordering
            matches = query.all()

        # Use global match_sort_key for proper ordering (handles X-Y playoff format)
        matches = sorted(matches, key=match_sort_key)
    
    # Compute display scores: prefer API (match.red_score/blue_score) and fall back to local scouting data
    display_scores = {}
    try:
        # Only attempt local fallback if we have an authenticated user with a scouting team
        scouting_team_number = current_user.scouting_team_number if getattr(current_user, 'is_authenticated', False) else None
    except Exception:
        scouting_team_number = None

    def _compute_local_scores_for_match(m):
        # Gather scouting entries for this match and scouting team
        # EPA fallback: if a team has no scouting data, use Statbotics EPA when enabled
        from app.utils.analysis import get_current_epa_source, get_epa_metrics_for_team

        epa_source = get_current_epa_source()
        use_epa = epa_source in ('scouted_with_statbotics', 'statbotics_only', 'tba_opr_only', 'scouted_with_tba_opr')
        statbotics_only = epa_source in ('statbotics_only', 'tba_opr_only')

        if not scouting_team_number and not use_epa:
            return (None, None)
        # Exclude alliance-copied data when not in alliance mode
        from sqlalchemy import or_
        entries = []
        if scouting_team_number and not statbotics_only:
            entries = ScoutingData.query.filter_by(match_id=m.id, scouting_team_number=scouting_team_number).filter(
                or_(
                    ScoutingData.scout_name == None,
                    ~ScoutingData.scout_name.like('[Alliance-%')
                )
            ).all()

        # Keep the latest entry per team_id to avoid duplicate scouts
        latest_by_team = {}
        for e in entries:
            tid = e.team_id
            if tid not in latest_by_team or (getattr(e, 'timestamp', None) and e.timestamp and e.timestamp > latest_by_team[tid].timestamp):
                latest_by_team[tid] = e

        red_sum = 0
        blue_sum = 0
        any_points = False
        red_team_numbers = set(m.red_teams)
        blue_team_numbers = set(m.blue_teams)

        # Track which team_numbers already got scouting points
        scored_team_numbers = set()
        has_scout_data = False  # True only when real scouting entries contributed

        for e in latest_by_team.values():
            try:
                pts = int(e.calculate_metric('tot') or 0)
            except Exception:
                pts = 0
            tn = None
            try:
                tn = e.team.team_number if e.team else None
            except Exception:
                tn = None

            if tn in red_team_numbers:
                red_sum += pts
                any_points = any_points or pts > 0
                scored_team_numbers.add(tn)
                has_scout_data = True
            elif tn in blue_team_numbers:
                blue_sum += pts
                any_points = any_points or pts > 0
                scored_team_numbers.add(tn)
                has_scout_data = True

        # EPA fallback for teams without scouting data
        # Note: EPA scores are predictions only and must NOT mark a match as played
        epa_contributed = False
        if use_epa:
            all_match_teams = red_team_numbers | blue_team_numbers
            for tn in all_match_teams:
                if not statbotics_only and tn in scored_team_numbers:
                    continue
                epa = get_epa_metrics_for_team(tn)
                epa_total = epa.get('total') if epa else None
                if epa_total and epa_total > 0:
                    if statbotics_only:
                        # Override any scouting score with EPA
                        pass
                    if tn in red_team_numbers:
                        red_sum += int(epa_total)
                        epa_contributed = True
                    elif tn in blue_team_numbers:
                        blue_sum += int(epa_total)
                        epa_contributed = True

        if not any_points and not epa_contributed:
            return (None, None, None)
        # Return source: 'local' if real scouting data present, 'epa' if only EPA/OPR data
        score_source = 'local' if has_scout_data else 'epa'
        return (red_sum, blue_sum, score_source)


    # Build display scores for each match (normalize DB scores and fall back to local scouting data)
    for match in matches:
        # Normalize DB scores (treat negative scores like -1 as unplayed)
        red_db = norm_db_score(match.red_score)
        blue_db = norm_db_score(match.blue_score)

        # If API-provided scores exist (not None after normalization), use them; otherwise try local scouting data
        if red_db is not None or blue_db is not None:
            display_scores[match.id] = {
                'red_score': red_db,
                'blue_score': blue_db,
                'source': 'api'
            }
        else:
            r, b, score_src = _compute_local_scores_for_match(match)
            if r is not None or b is not None:
                display_scores[match.id] = {
                    'red_score': r,
                    'blue_score': b,
                    'source': score_src  # 'local' = real scouting, 'epa' = EPA/OPR prediction only
                }
            else:
                display_scores[match.id] = {'red_score': None, 'blue_score': None, 'source': None}

    # Compute per-event dynamic offset (minutes) from recent completed matches to improve predicted times
    dynamic_offset_minutes = 0
    try:
        if event:
            # Use matches sorted by most recent match_number descending to find recent completed matches
            recent_matches = sorted(matches, key=lambda m: m.match_number, reverse=True)
            dynamic_offset_minutes = compute_event_dynamic_offset_minutes(event, recent_matches, lookback=10)
    except Exception:
        dynamic_offset_minutes = 0

    # Build adjusted predicted times map (match_id -> adjusted_datetime)
    adjusted_predictions = {}
    try:
        for m in matches:
            if getattr(m, 'predicted_time', None) is not None:
                try:
                    adj = m.predicted_time
                    if dynamic_offset_minutes:
                        from datetime import timedelta
                        adj = adj + timedelta(minutes=dynamic_offset_minutes)
                    adjusted_predictions[m.id] = adj
                except Exception:
                    adjusted_predictions[m.id] = m.predicted_time
    except Exception:
        adjusted_predictions = {}

    # Determine the next unplayed match (first match in sorted order without actual_time/winner)
    # Note: Don't rely on scores alone as they may be initialized to 0 before matches are played
    next_unplayed_match_id = None
    try:
        now_utc = datetime.now(timezone.utc)
        for m in matches:
            finished = bool(
                getattr(m, 'actual_time', None)
                or getattr(m, 'winner', None)
            )
            if finished:
                continue

            # We only consider matches with an adjusted predicted_time for the 'starting soon' behavior
            pred = adjusted_predictions.get(m.id) or getattr(m, 'predicted_time', None)
            if not pred:
                # If no predicted_time, this match is the next unplayed but we won't mark it 'starting soon' unless predicted_time exists
                next_unplayed_match_id = m.id
                break

            # Convert event-local predicted_time to UTC for comparison
            try:
                match_pred_utc = convert_local_to_utc(pred, m.event.timezone if getattr(m, 'event', None) else None)
            except Exception:
                match_pred_utc = pred if pred.tzinfo is not None else pred.replace(tzinfo=timezone.utc)

            # If predicted time is in the past, mark this as the next unplayed to show 'Starting soon'
            if now_utc > match_pred_utc:
                next_unplayed_match_id = m.id
                break

            # If predicted time is not past, then the first unplayed match is this one but it's not yet 'starting soon'
            next_unplayed_match_id = m.id
            break
    except Exception:
        next_unplayed_match_id = None

    return render_template('matches/index.html', matches=matches, events=events, selected_event=selected_event_for_dropdown, force_selected_event=force_selected_event, display_scores=display_scores, next_unplayed_match_id=next_unplayed_match_id, adjusted_predictions=adjusted_predictions, **get_theme_context())

@bp.route('/sync_from_config')
def sync_from_config():
    """Sync matches from FIRST API using the event code from config file"""
    try:
        # Get event code from config
        game_config = get_effective_game_config()
        raw_event_code = game_config.get('current_event_code')
        
        if not raw_event_code:
            flash("No event code found in configuration. Please add 'current_event_code' to your game_config.json file.", 'danger')
            return redirect(url_for('matches.index'))
        
        # Find or create the event in our database (filtered by scouting team)
        # Use year-prefixed event code so each year is treated as a different event (e.g., 2026ARLI)
        current_year = game_config.get('season', 2026)
        event_code = f"{current_year}{raw_event_code}"
        event = get_event_by_code(event_code)

        # If `get_event_by_code` returned a synthetic alliance entry (id like 'alliance_<CODE>'),
        # convert it to a real DB Event record under the current scouting team so
        # subsequent database writes use an integer `event.id`.
        try:
            from sqlalchemy import func
            from app.utils.team_isolation import get_current_scouting_team_number
            from app.utils.api_utils import get_event_details_dual_api
            from app.routes.data import get_or_create_event

            current_scouting_team = get_current_scouting_team_number()
            if event and isinstance(getattr(event, 'id', None), str) and str(event.id).startswith('alliance_'):
                # Try to find a real event record for this code under the current scouting team
                real_event = Event.query.filter(
                    func.upper(Event.code) == str(event.code).upper(),
                    Event.scouting_team_number == current_scouting_team
                ).first()

                if not real_event:
                    # Attempt to fetch details from API and create the event record
                    # Use raw_event_code for external API calls
                    try:
                        event_details = get_event_details_dual_api(raw_event_code)
                    except Exception:
                        event_details = None

                    # Store with year-prefixed event_code to differentiate years
                    real_event = get_or_create_event(
                        name=event_details.get('name', f"Event {raw_event_code}") if event_details else f"Event {raw_event_code}",
                        code=event_code,
                        year=event_details.get('year', current_year) if event_details else current_year,
                        location=event_details.get('location') if event_details else None,
                        start_date=event_details.get('start_date') if event_details else None,
                        end_date=event_details.get('end_date') if event_details else None,
                        scouting_team_number=current_scouting_team
                    )

                    if event_details and event_details.get('timezone') and not getattr(real_event, 'timezone', None):
                        real_event.timezone = event_details.get('timezone')
                        db.session.add(real_event)
                        db.session.commit()

                # Replace the synthetic object with the concrete DB record for the rest of this route
                event = real_event
        except Exception:
            # If anything goes wrong, continue and let later code handle missing `event` gracefully
            try:
                db.session.rollback()
            except Exception:
                pass

            from app.routes.data import get_or_create_event
            from app.utils.team_isolation import get_current_scouting_team_number
            current_scouting_team = get_current_scouting_team_number()
            # Use raw_event_code for external API calls
            event_details = get_event_details_dual_api(raw_event_code)
            
            if event_details:
                # Use get_or_create_event to properly handle race conditions
                # Store with year-prefixed event_code to differentiate years
                event = get_or_create_event(
                    name=event_details.get('name', f"Event {raw_event_code}"),
                    code=event_code,
                    year=event_details.get('year', current_year),
                    location=event_details.get('location'),
                    start_date=event_details.get('start_date'),
                    end_date=event_details.get('end_date'),
                    scouting_team_number=current_scouting_team
                )
                # Set timezone separately if available (not in get_or_create_event params)
                if event_details.get('timezone') and not getattr(event, 'timezone', None):
                    event.timezone = event_details.get('timezone')
                    db.session.add(event)
            else:
                # Fallback to placeholder using get_or_create_event
                # Store with year-prefixed event_code to differentiate years
                event = get_or_create_event(
                    name=f"Event {raw_event_code}",
                    code=event_code,
                    year=current_year,
                    scouting_team_number=current_scouting_team
                )
            db.session.flush()  # Get the ID without committing yet
        
        # Fetch matches from the dual API using raw event code (external APIs don't use year-prefixed codes)
        match_data_list = get_matches_dual_api(raw_event_code)
        
        # Track metrics for user feedback
        matches_added = 0
        matches_updated = 0
        
        # Import DisableReplication to prevent queue issues during bulk operations
        from app.utils.real_time_replication import DisableReplication
        
        # Temporarily disable replication during bulk sync to prevent queue issues
        with DisableReplication():
            BATCH_SIZE = 25
            batch_count = 0
            failed_matches = []  # Track matches that failed to sync

            # Process each match from the API inside SAVEPOINTs so one
            # failure doesn't kill the whole sync.
            for match_data in match_data_list:
                # Set the event_id for the match
                match_data['event_id'] = event.id
                
                if not match_data:
                    continue
                    
                match_number = match_data.get('match_number')
                match_type = match_data.get('match_type')
                
                if not match_number or not match_type:
                    continue

                try:
                    nested = db.session.begin_nested()  # SAVEPOINT
                
                    # Verify event exists before trying to add/update match
                    if not event or not event.id:
                        raise ValueError(f"Invalid event_id for match {match_type} {match_number}")
                
                    # Check if the match already exists for this scouting team
                    # Use explicit query to avoid issues with deleted matches
                    from app.utils.team_isolation import get_current_scouting_team_number
                    current_team = get_current_scouting_team_number()
                    
                    match = Match.query.filter(
                        Match.scouting_team_number == current_team,
                        Match.event_id == event.id,
                        Match.match_number == match_number,
                        Match.match_type == match_type
                    ).first()
                    
                    if match:
                        # Update existing match
                        match.red_alliance = match_data.get('red_alliance', match.red_alliance)
                        match.blue_alliance = match_data.get('blue_alliance', match.blue_alliance)
                        match.winner = match_data.get('winner', match.winner)
                        match.red_score = match_data.get('red_score', match.red_score)
                        match.blue_score = match_data.get('blue_score', match.blue_score)
                        match.display_match_number = match_data.get('display_match_number', match.display_match_number)
                        if match_data.get('comp_level'):
                            match.comp_level = match_data.get('comp_level')
                        if match_data.get('set_number') is not None:
                            match.set_number = match_data.get('set_number')
                        # Ensure scheduled times are updated
                        if match_data.get('scheduled_time'):
                            match.scheduled_time = match_data.get('scheduled_time')
                        if match_data.get('predicted_time'):
                            match.predicted_time = match_data.get('predicted_time')
                        if match_data.get('actual_time'):
                            match.actual_time = match_data.get('actual_time')
                        # Ensure scouting_team_number is set (in case it was None before)
                        assign_scouting_team_to_model(match)
                        matches_updated += 1
                    else:
                        # Add new match - filter out non-model fields before creating
                        # Valid Match model fields
                        valid_fields = {
                            'match_number', 'match_type', 'event_id', 'red_alliance', 'blue_alliance',
                            'red_score', 'blue_score', 'winner', 'timestamp', 'scheduled_time',
                            'predicted_time', 'actual_time', 'display_match_number', 'scouting_team_number',
                            'comp_level', 'set_number'
                        }
                        # Filter match_data to only include valid fields
                        filtered_data = {k: v for k, v in match_data.items() if k in valid_fields}
                        
                        # Ensure event_id is set
                        filtered_data['event_id'] = event.id
                        
                        match = Match(**filtered_data)
                        assign_scouting_team_to_model(match)  # Assign current scouting team
                        db.session.add(match)
                        db.session.flush()  # Flush to catch any DB errors immediately
                        matches_added += 1

                    nested.commit()  # Release SAVEPOINT
                except Exception as e:
                    try:
                        nested.rollback()  # Rollback only this SAVEPOINT
                    except Exception:
                        pass
                    error_msg = f"{match_type} {match_number}: {str(e)}"
                    failed_matches.append(error_msg)
                    current_app.logger.error(f"Failed to sync match {error_msg}")
                    print(f"Warning: Failed to sync match {error_msg}")
                    continue

                batch_count += 1
                if batch_count % BATCH_SIZE == 0:
                    db.session.commit()  # Checkpoint progress
            
            # Final commit for remaining items
            db.session.commit()
            
            # Report any failed matches to the user
            if failed_matches:
                failed_count = len(failed_matches)
                if failed_count <= 5:
                    # Show details for a few failures
                    flash(f"Warning: {failed_count} match(es) failed to sync: {'; '.join(failed_matches[:5])}", 'warning')
                else:
                    # Too many to show details
                    flash(f"Warning: {failed_count} match(es) failed to sync. Check logs for details.", 'warning')
                current_app.logger.warning(f"Match sync failures: {failed_matches}")
        
        # Merge any duplicate events that may have been created
        try:
            from app.routes.data import merge_duplicate_events
            from app.utils.team_isolation import get_current_scouting_team_number
            current_scouting_team = get_current_scouting_team_number()
            merge_duplicate_events(current_scouting_team)
        except Exception as merge_err:
            print(f"  Warning: Could not merge duplicate events: {merge_err}")
        
        # Update match times from API after syncing matches
        try:
            from app.utils.match_time_fetcher import update_match_times
            times_updated = update_match_times(event_code, current_app.config.get('TEAM_NUMBER'))
            if times_updated > 0:
                print(f" Updated scheduled times for {times_updated} matches")
        except Exception as e:
            print(f"️  Could not update match times: {e}")
        
        # After bulk sync, queue a single replication event for the match sync
        if matches_added > 0 or matches_updated > 0:
            from app.utils.real_time_replication import real_time_replicator
            real_time_replicator.replicate_operation(
                'update', 
                'matches', 
                {
                    'event_code': event_code,
                    'matches_added': matches_added,
                    'matches_updated': matches_updated,
                    'total_matches': len(match_data_list),
                    'sync_type': 'bulk_sync',
                    'sync_timestamp': datetime.now(timezone.utc).isoformat()
                }, 
                f"sync_summary_{event_code}"
            )
        
        # Show success message
        flash(f"Matches sync complete! Added {matches_added} new matches and updated {matches_updated} existing matches.", 'success')
        
    except ApiError as e:
        msg = str(e)
        msg_lower = msg.lower()
        if '401' in msg_lower or '404' in msg_lower or 'not found' in msg_lower:
            flash("Event not found from API.", 'danger')
        else:
            flash(f"API Error: {msg}", 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f"Error syncing matches: {str(e)}", 'danger')
    
    return redirect(url_for('matches.index'))


@bp.route('/update_times')
def update_times():
    """Update match scheduled times from API for the current event"""
    try:
        # Get event code from config
        game_config = get_effective_game_config()
        raw_event_code = game_config.get('current_event_code')
        
        if not raw_event_code:
            flash("No event code found in configuration.", 'danger')
            return redirect(url_for('matches.index'))
        
        # Construct year-prefixed code for database lookup
        current_year = game_config.get('season', 2026)
        event_code = f"{current_year}{raw_event_code}"
        
        # Update match times
        from app.utils.match_time_fetcher import update_match_times
        times_updated = update_match_times(event_code, current_app.config.get('TEAM_NUMBER'))
        
        if times_updated > 0:
            flash(f" Updated scheduled times for {times_updated} matches!", 'success')
        else:
            flash("No match times needed updating.", 'info')
        
    except Exception as e:
        flash(f"Error updating match times: {str(e)}", 'danger')
    
    return redirect(url_for('matches.index'))


@bp.route('/<int:match_id>')
def view(match_id):
    """View match details and related scouting data"""
    from app.models import AllianceSharedScoutingData
    from sqlalchemy import func
    
    match = Match.query.get_or_404(match_id)
    
    # Check if alliance mode is active
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # Get scouting data for this match - use alliance data if in alliance mode
    if is_alliance_mode:
        # In alliance mode, query by match_number and event_code since match IDs differ across teams
        event = Event.query.get(match.event_id)
        scouting_data = AllianceSharedScoutingData.query.join(
            Match, AllianceSharedScoutingData.match_id == Match.id
        ).join(
            Event, Match.event_id == Event.id
        ).filter(
            Match.match_number == match.match_number,
            Match.match_type == match.match_type,
            func.upper(Event.code) == func.upper(event.code) if event and event.code else Match.event_id == match.event_id,
            AllianceSharedScoutingData.alliance_id == alliance_id,
            AllianceSharedScoutingData.is_active == True
        ).all()
    else:
        # Exclude alliance-copied data when not in alliance mode
        from sqlalchemy import or_
        scouting_data = ScoutingData.query.filter_by(match_id=match.id, scouting_team_number=current_user.scouting_team_number).filter(
            or_(
                ScoutingData.scout_name == None,
                ~ScoutingData.scout_name.like('[Alliance-%')
            )
        ).all()
    
    # Get game configuration
    game_config = get_effective_game_config()
    # Compute display score for this match (prefer API, fallback to local scouting data)
    display_score = {'red_score': None, 'blue_score': None, 'source': None}
    # Normalize stored scores so negative sentinel values don't mark the match as played
    red_db = norm_db_score(match.red_score)
    blue_db = norm_db_score(match.blue_score)
    _predicted_dt = getattr(match, 'predicted_time', None)
    _actual_dt = getattr(match, 'actual_time', None)
    _scheduled_dt = getattr(match, 'scheduled_time', None)
    _played_dt = _actual_dt or _scheduled_dt
    if red_db is not None or blue_db is not None:
        display_score = {'red_score': red_db, 'blue_score': blue_db, 'source': 'api'}
    else:
        try:
            scouting_team_number = current_user.scouting_team_number if getattr(current_user, 'is_authenticated', False) else None
        except Exception:
            scouting_team_number = None

        # Use the scouting data we already fetched (which is alliance-aware)
        from app.utils.analysis import get_current_epa_source, get_epa_metrics_for_team
        epa_source = get_current_epa_source()
        use_epa = epa_source in ('scouted_with_statbotics', 'statbotics_only', 'tba_opr_only', 'scouted_with_tba_opr')
        statbotics_only = epa_source in ('statbotics_only', 'tba_opr_only')

        entries = scouting_data if scouting_data and not statbotics_only else []
        if entries:
                latest_by_team = {}
                for e in entries:
                    tid = e.team_id
                    if tid not in latest_by_team or (getattr(e, 'timestamp', None) and e.timestamp and e.timestamp > latest_by_team[tid].timestamp):
                        latest_by_team[tid] = e

                red_sum = 0
                blue_sum = 0
                any_points = False
                red_team_numbers = set(match.red_teams)
                blue_team_numbers = set(match.blue_teams)
                scored_team_numbers = set()

                for e in latest_by_team.values():
                    try:
                        pts = int(e.calculate_metric('tot') or 0)
                    except Exception:
                        pts = 0
                    tn = None
                    try:
                        tn = e.team.team_number if e.team else None
                    except Exception:
                        tn = None

                    if tn in red_team_numbers:
                        red_sum += pts
                        any_points = any_points or pts > 0
                        scored_team_numbers.add(tn)
                    elif tn in blue_team_numbers:
                        blue_sum += pts
                        any_points = any_points or pts > 0
                        scored_team_numbers.add(tn)

                # EPA fallback for teams without scouting data
                if use_epa:
                    all_match_teams = red_team_numbers | blue_team_numbers
                    for tn in all_match_teams:
                        if not statbotics_only and tn in scored_team_numbers:
                            continue
                        epa = get_epa_metrics_for_team(tn)
                        epa_total = epa.get('total') if epa else None
                        if epa_total and epa_total > 0:
                            if tn in red_team_numbers:
                                red_sum += int(epa_total)
                                any_points = True
                            elif tn in blue_team_numbers:
                                blue_sum += int(epa_total)
                                any_points = True

                if any_points:
                    display_score = {'red_score': red_sum, 'blue_score': blue_sum, 'source': 'local'}
        elif use_epa:
            # No scouting data at all — try pure EPA prediction
            red_sum = 0
            blue_sum = 0
            any_points = False
            red_team_numbers = set(match.red_teams)
            blue_team_numbers = set(match.blue_teams)
            for tn in (red_team_numbers | blue_team_numbers):
                epa = get_epa_metrics_for_team(tn)
                epa_total = epa.get('total') if epa else None
                if epa_total and epa_total > 0:
                    if tn in red_team_numbers:
                        red_sum += int(epa_total)
                        any_points = True
                    elif tn in blue_team_numbers:
                        blue_sum += int(epa_total)
                        any_points = True
            if any_points:
                display_score = {'red_score': red_sum, 'blue_score': blue_sum, 'source': 'epa'}

    return render_template('matches/view.html', match=match, 
                          scouting_data=scouting_data, game_config=game_config, display_score=display_score, **get_theme_context())

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new match"""
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    events = get_combined_dropdown_events()
    
    # Get ALL teams at the current event (regardless of scouting_team_number)
    if current_event:
        teams = get_all_teams_at_event(event_id=current_event.id)
    else:
        teams = []  # No teams if no current event is set
    
    if request.method == 'POST':
        match_number = request.form.get('match_number', type=int)
        match_type = request.form.get('match_type')
        event_id = request.form.get('event_id', type=int)
        
        # Get alliance team numbers
        red_teams = []
        blue_teams = []
        for i in range(get_effective_game_config()['alliance_size']):
            red_team = request.form.get(f'red_team_{i}')
            blue_team = request.form.get(f'blue_team_{i}')
            if red_team: red_teams.append(red_team)
            if blue_team: blue_teams.append(blue_team)
            
        red_alliance = ','.join(red_teams)
        blue_alliance = ','.join(blue_teams)
        
        # Optional scores
        red_score = request.form.get('red_score', type=int)
        blue_score = request.form.get('blue_score', type=int)
        
        if not all([match_number, match_type, event_id, red_alliance, blue_alliance]):
            flash('All required fields must be filled out!', 'error')
            return redirect(url_for('matches.add'))

        # Prevent creating duplicate matches for same event/type/number
        existing = filter_matches_by_scouting_team().filter(
            Match.event_id == event_id,
            Match.match_number == match_number,
            Match.match_type == match_type
        ).first()
        if existing:
            flash(f'Match {match_type} {match_number} already exists for this event; updating existing match instead.', 'warning')
            existing.red_alliance = red_alliance
            existing.blue_alliance = blue_alliance
            existing.red_score = red_score
            existing.blue_score = blue_score
            db.session.commit()
            return redirect(url_for('matches.view', match_id=existing.id))

        # Ensure Team records exist for any team numbers referenced in alliances and associate them with the event
        def ensure_team_and_associate(team_number_str):
            # team_number_str may include whitespace; return the canonical string used in alliances
            tn = team_number_str.strip()
            if not tn:
                return None
            try:
                tn_int = int(tn)
            except Exception:
                # Non-numeric team identifiers are allowed but we treat them as strings
                tn_int = None

            team_obj = None
            if tn_int is not None:
                team_obj = filter_teams_by_scouting_team().filter(Team.team_number == tn_int).first()

            # Fallback: try to find any team with matching team_number string
            if not team_obj:
                if tn_int is not None:
                    # If numeric but not found, create a new Team with that number
                    team_obj = Team(team_number=tn_int, team_name=None, location=None)
                else:
                    # Non-numeric key - create with team_number set to 0 and store identifier in team_name
                    team_obj = Team(team_number=0, team_name=tn, location=None)
                assign_scouting_team_to_model(team_obj)
                try:
                    nested = db.session.begin_nested()  # SAVEPOINT
                    db.session.add(team_obj)
                    db.session.flush()
                    nested.commit()
                except Exception as e:
                    try:
                        nested.rollback()
                    except Exception:
                        pass
                    current_app.logger.error(f"Failed to create team {tn}: {e}")
                    return None

            # Associate the team with the event if not already
            try:
                nested = db.session.begin_nested()  # SAVEPOINT
                ev = Event.query.get(event_id)
                if ev and ev not in team_obj.events:
                    team_obj.events.append(ev)
                    db.session.flush()
                nested.commit()
            except Exception:
                try:
                    nested.rollback()
                except Exception:
                    pass

            return tn

        # Ensure all referenced teams exist/are associated
        for t in red_teams + blue_teams:
            ensure_team_and_associate(t)

        # Create new match
        match = Match(
            match_number=match_number,
            match_type=match_type,
            event_id=event_id,
            red_alliance=red_alliance,
            blue_alliance=blue_alliance,
            red_score=red_score,
            blue_score=blue_score
        )
        assign_scouting_team_to_model(match)

        db.session.add(match)
        db.session.commit()

        flash(f'Match {match_type} {match_number} added successfully!', 'success')
        return redirect(url_for('matches.index'))
    
    return render_template('matches/add.html', events=events, teams=teams, 
                          alliance_size=get_effective_game_config()['alliance_size'],
                          match_types=get_effective_game_config()['match_types'], **get_theme_context())

@bp.route('/<int:match_id>/edit', methods=['GET', 'POST'])
def edit(match_id):
    """Edit match details"""
    match = Match.query.get_or_404(match_id)
    events = get_combined_dropdown_events()
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get ALL teams at the current event (regardless of scouting_team_number)
    if current_event:
        teams = get_all_teams_at_event(event_id=current_event.id)
    else:
        teams = []  # No teams if no current event is set
    
    if request.method == 'POST':
        match.match_number = request.form.get('match_number', type=int)
        match.match_type = request.form.get('match_type')
        match.event_id = request.form.get('event_id', type=int)
        
        # Get alliance team numbers
        red_teams = []
        blue_teams = []
        for i in range(get_effective_game_config()['alliance_size']):
            red_team = request.form.get(f'red_team_{i}')
            blue_team = request.form.get(f'blue_team_{i}')
            if red_team: red_teams.append(red_team)
            if blue_team: blue_teams.append(blue_team)
            
        match.red_alliance = ','.join(red_teams)
        match.blue_alliance = ','.join(blue_teams)
        
        # Optional scores
        match.red_score = request.form.get('red_score', type=int)
        match.blue_score = request.form.get('blue_score', type=int)
        
        db.session.commit()
        flash(f'Match updated successfully!', 'success')
        return redirect(url_for('matches.view', match_id=match.id))
    
    # Parse alliance teams for form
    red_teams = match.red_alliance.split(',') if match.red_alliance else []
    blue_teams = match.blue_alliance.split(',') if match.blue_alliance else []
    
    return render_template('matches/edit.html', match=match, events=events, teams=teams,
                         red_teams=red_teams, blue_teams=blue_teams,
                         alliance_size=get_effective_game_config()['alliance_size'],
                         match_types=get_effective_game_config()['match_types'], **get_theme_context())

@bp.route('/<int:match_id>/delete', methods=['POST'])
def delete(match_id):
    """Delete a match"""
    match = Match.query.get_or_404(match_id)
    
    # Delete associated scouting data (including qualitative entries)
    ScoutingData.query.filter_by(match_id=match.id, scouting_team_number=current_user.scouting_team_number).delete()
    # qualitative observations are scoped to the match too
    from app.models import QualitativeScoutingData
    QualitativeScoutingData.query.filter_by(match_id=match.id, scouting_team_number=current_user.scouting_team_number).delete()
    
    db.session.delete(match)
    db.session.commit()
    
    flash(f'Match deleted successfully!', 'success')
    return redirect(url_for('matches.index'))

@bp.route('/strategy')
@analytics_required
def strategy():
    """Match strategy analysis page"""
    # Get all events for the dropdown (combined/deduped like /events)
    events = get_combined_dropdown_events()
    
    # Get event from URL parameter or form (accept synthetic 'alliance_CODE' ids)
    raw_event_param = request.args.get('event_id') or request.form.get('event_id')
    event = None
    matches = []

    if raw_event_param:
        # If the param is numeric, treat it as a DB id; otherwise treat as a synthetic alliance id or code
        try:
            event_id = int(raw_event_param)
            event = Event.query.get_or_404(event_id)
            # If alliance mode is active, prefer alliance-aware match gathering
            alliance_id = get_active_alliance_id()
            if alliance_id:
                matches, _ = get_all_matches_for_alliance(event_id=event.id, event_code=getattr(event, 'code', None))
            else:
                matches = filter_matches_by_scouting_team().filter(Match.event_id == event.id).all()
        except Exception:
            # Non-numeric ids: handle synthetic 'alliance_CODE' or raw event code
            try:
                param_str = str(raw_event_param)
                # If form of 'alliance_CODE', extract code portion
                if param_str.startswith('alliance_'):
                    code = param_str[len('alliance_'):]
                else:
                    code = param_str
                # Use helper to build a representative event object (may return synthetic or real event)
                event = get_event_by_code(code)
                # Use alliance helper to fetch matches across alliance members
                matches, _ = get_all_matches_for_alliance(event_id=param_str, event_code=code)
            except Exception:
                matches = []
        # Sort matches for display
        try:
            matches = sorted(matches, key=match_sort_key)
        except Exception:
            pass
    
    # Get game configuration (alliance-aware)
    game_config = get_effective_game_config()
    
    # Allow an optional preselected match id so other pages can link directly to an analysis
    preselected_match_id = request.args.get('match_id', type=int)

    return render_template(
        'matches/strategy.html',
        events=events,
        selected_event=event,
        matches=matches,
        game_config=game_config,
        preselected_match_id=preselected_match_id,
        **get_theme_context()
    )


@bp.route('/strategy/live')
@analytics_required
def strategy_live():
    """Live strategy page that automatically shows the selected team's next match
    and advances to the following match 2 minutes after the scheduled start time
    of the match it was showing.
    """
    # All events for dropdown (combined/deduped like /events)
    events = get_combined_dropdown_events()

    # Determine selected event from query params or config
    # Use the effective game config helper so defaults from config files are respected
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    event_id = request.args.get('event_id', type=int)
    event = None
    if event_id:
        try:
            event = Event.query.get(event_id)
        except Exception as exc:  # catch missing-column errors, etc.
            from sqlalchemy.exc import ProgrammingError
            if isinstance(exc, ProgrammingError):
                # Try to self-heal by running any outstanding migrations and
                # retry once.  The column definitions in MIGRATIONS are now
                # dialect-aware, so this should succeed on PostgreSQL.
                from app.utils.database_migrations import run_all_migrations
                from app import db
                run_all_migrations(db)
                try:
                    event = Event.query.get(event_id)
                except Exception:
                    event = None
            else:
                event = None
    elif current_event_code:
        try:
            event = get_event_by_code(current_event_code)
        except Exception as exc:
            # if the failure was caused by a missing column, run migrations
            from sqlalchemy.exc import ProgrammingError
            if isinstance(exc, ProgrammingError):
                from app.utils.database_migrations import run_all_migrations
                from app import db
                run_all_migrations(db)
                try:
                    event = get_event_by_code(current_event_code)
                except Exception:
                    event = None
            else:
                event = None

    # Get ALL teams at the event (regardless of scouting_team_number)
    teams = []
    event_timezone = None
    if event:
        teams = get_all_teams_at_event(event_id=event.id)
        event_timezone = getattr(event, 'timezone', None)

    return render_template('matches/strategy_live.html', events=events, selected_event=event, teams=teams, game_config=game_config, event_timezone=event_timezone, **get_theme_context())


@bp.route('/strategy/live/current-match')
@analytics_required
def strategy_live_current_match():
    """Server-side match selection for live strategy.
    Accepts: event_id, team_number, skip_ids (comma-separated match IDs to skip past).
    Returns the match the live strategy page should currently display and timing info.
    The server determines the correct match using server time, eliminating client clock issues.
    """
    try:
        event_id = request.args.get('event_id', type=int)
        team_number = request.args.get('team_number', type=str)
        skip_ids_raw = request.args.get('skip_ids', '', type=str)
        skip_ids = set()
        if skip_ids_raw:
            for s in skip_ids_raw.split(','):
                s = s.strip()
                if s.isdigit():
                    skip_ids.add(int(s))

        if not event_id or not team_number:
            return jsonify({'success': False, 'error': 'event_id and team_number are required'}), 400

        team_number = team_number.strip()

        # Determine event (respect scouting team isolation)
        event = filter_events_by_scouting_team().filter(Event.id == event_id).first()
        if not event:
            return jsonify({'success': False, 'error': 'Event not found'}), 404

        # Fetch all matches for the event
        from sqlalchemy import func as _func
        event_code = getattr(event, 'code', None)
        if event_code:
            matches_q = filter_matches_by_scouting_team().join(Event, Match.event_id == Event.id).filter(
                _func.upper(Event.code) == event_code.upper()
            )
        else:
            matches_q = filter_matches_by_scouting_team().filter_by(event_id=event.id)

        from app.utils.team_isolation import get_current_scouting_team_number
        scouting_team = get_current_scouting_team_number()
        if scouting_team is not None:
            matches_q = matches_q.filter(Match.scouting_team_number == scouting_team)
        else:
            matches_q = matches_q.filter(Match.scouting_team_number.is_(None))

        all_matches = matches_q.all()
        all_matches = sorted(all_matches, key=match_sort_key)

        # Filter to matches that include this team
        def _team_in_match(tn, m):
            """Check whether team number tn appears in match m's alliances."""
            teams_in = set()
            for attr in ('red_1', 'red_2', 'red_3', 'blue_1', 'blue_2', 'blue_3'):
                v = getattr(m, attr, None)
                if v is not None:
                    teams_in.add(str(v).strip())
            for attr in ('red_alliance', 'blue_alliance'):
                v = getattr(m, attr, None)
                if v:
                    for part in str(v).split(','):
                        part = part.strip()
                        if part:
                            teams_in.add(part)
            return str(tn) in teams_in

        team_matches = [m for m in all_matches if _team_in_match(team_number, m)]
        if not team_matches:
            return jsonify({
                'success': True,
                'current_match': None,
                'total_team_matches': 0,
                'message': f'No matches found for team {team_number} at this event'
            })

        # Get schedule offset
        schedule_offset_min = getattr(event, 'schedule_offset', None) or 0
        schedule_offset_ms = schedule_offset_min * 60 * 1000
        ADVANCE_DELAY_MS = 2 * 60 * 1000  # 2 minutes after match start

        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)

        # Get event timezone for proper conversion (match times stored as naive UTC)
        event_tz = getattr(event, 'timezone', None)

        def _get_match_time_ms(m):
            """Get the best scheduling timestamp as UTC epoch milliseconds.
            Naive datetimes are treated as UTC (consistent with how
            match_time_fetcher stores them)."""
            for attr in ('predicted_time', 'scheduled_time'):
                dt = getattr(m, attr, None)
                if dt is not None:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp() * 1000)
            return None

        def _is_completed(m):
            actual = getattr(m, 'actual_time', None)
            winner = getattr(m, 'winner', None)
            r = norm_db_score(m.red_score)
            b = norm_db_score(m.blue_score)
            return bool(actual or winner or r is not None or b is not None)

        # Build list of unplayed, non-skipped match indices for "has next match" logic
        viable_indices = []
        for i, m in enumerate(team_matches):
            if m.id not in skip_ids and not _is_completed(m):
                viable_indices.append(i)

        # Walk through team matches in order and find the right one to show
        selected = None
        selected_idx = None
        selected_advance_at_ms = None
        all_info = []

        for i, m in enumerate(team_matches):
            is_done = _is_completed(m)
            ts = _get_match_time_ms(m)
            adjusted_ts = (ts + schedule_offset_ms) if ts is not None else None

            info = {
                'id': m.id,
                'match_number': m.match_number,
                'comp_level': getattr(m, 'comp_level', None) or getattr(m, 'match_type', None),
                'completed': is_done,
                'time_ms': ts,
                'skipped': m.id in skip_ids,
            }
            all_info.append(info)

            if m.id in skip_ids:
                continue
            if is_done:
                continue

            # This match is unplayed and not skipped
            if selected is None:
                # First viable candidate
                if adjusted_ts is not None:
                    advance_at = adjusted_ts + ADVANCE_DELAY_MS
                    if now_ms >= advance_at:
                        # Already past the advance point — skip unless it's the last viable match
                        continue
                # Either no time, or time is in the future / within 2-min window
                selected = m
                selected_idx = i
                if adjusted_ts is not None:
                    selected_advance_at_ms = adjusted_ts + ADVANCE_DELAY_MS
                continue

        # If nothing was selected (all past advance threshold or completed),
        # pick the last unplayed match that isn't skipped (fallback)
        if selected is None:
            for m in reversed(team_matches):
                if m.id not in skip_ids and not _is_completed(m):
                    selected = m
                    selected_idx = team_matches.index(m)
                    # Don't set advance_at for fallback — there's nothing after this
                    selected_advance_at_ms = None
                    break

        # If still nothing, everything is completed — show the last match
        if selected is None:
            selected = team_matches[-1]
            selected_idx = len(team_matches) - 1

        # Determine if there IS a next viable match after the selected one
        has_next_match = False
        if selected_idx is not None:
            for vi in viable_indices:
                if vi > selected_idx and team_matches[vi].id != selected.id:
                    has_next_match = True
                    break

        # If there's no next match to advance to, clear the advance timer
        if not has_next_match:
            selected_advance_at_ms = None

        # Build response for the selected match
        def _iso_utc(dt):
            if dt is None:
                return None
            if getattr(dt, 'tzinfo', None) is not None:
                return dt.isoformat()
            return dt.isoformat() + '+00:00'

        def _extract_teams(m, prefix_red=True):
            teams_out = []
            if prefix_red:
                attrs = ('red_1', 'red_2', 'red_3')
            else:
                attrs = ('blue_1', 'blue_2', 'blue_3')
            for attr in attrs:
                v = getattr(m, attr, None)
                if v is not None:
                    teams_out.append(str(v))
            if not teams_out:
                s = getattr(m, 'red_alliance' if prefix_red else 'blue_alliance', None)
                if s:
                    teams_out = [x.strip() for x in str(s).split(',') if x.strip()]
            return teams_out

        # Format the display time the SAME way the matches index page does
        # (using format_time_with_timezone with event timezone → consistent display)
        from app.utils.timezone_utils import format_time_with_timezone
        event_tz = getattr(event, 'timezone', None)
        best_time_dt = getattr(selected, 'predicted_time', None) or getattr(selected, 'scheduled_time', None)
        display_time = ''
        if best_time_dt:
            display_time = format_time_with_timezone(best_time_dt, event_tz, '%I:%M %p')

        match_data = {
            'id': selected.id,
            'event_id': selected.event_id,
            'match_number': selected.match_number,
            'comp_level': getattr(selected, 'comp_level', None) or getattr(selected, 'match_type', None),
            'predicted_time': _iso_utc(getattr(selected, 'predicted_time', None)),
            'scheduled_time': _iso_utc(getattr(selected, 'scheduled_time', None)),
            'actual_time': _iso_utc(getattr(selected, 'actual_time', None)),
            'display_time': display_time,  # pre-formatted like the matches page
            'status': 'completed' if _is_completed(selected) else 'upcoming',
            'alliances': {
                'red': {'teams': _extract_teams(selected, True), 'score': norm_db_score(selected.red_score)},
                'blue': {'teams': _extract_teams(selected, False), 'score': norm_db_score(selected.blue_score)},
            },
        }

        return jsonify({
            'success': True,
            'current_match': match_data,
            'advance_at_ms': selected_advance_at_ms,
            'has_next_match': has_next_match,
            'server_time_ms': now_ms,
            'schedule_offset_ms': schedule_offset_ms,
            'event_timezone': event_tz,
            'total_team_matches': len(team_matches),
            'team_schedule': all_info,
        })

    except Exception as e:
        import traceback as _tb
        current_app.logger.error(f"strategy_live_current_match error: {e}\n{_tb.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/strategy/all')
@analytics_required
def strategy_all():
    """Show a compact strategy summary card for every match in an event."""
    # Get all events for the dropdown (combined/deduped like /events)
    events = get_combined_dropdown_events()

    # Get event from URL parameter or form (accept synthetic 'alliance_CODE' ids)
    raw_event_param = request.args.get('event_id') or request.form.get('event_id')
    event = None
    matches = []
    summaries = []

    if raw_event_param:
        try:
            event_id = int(raw_event_param)
            event = Event.query.get_or_404(event_id)
            alliance_id = get_active_alliance_id()
            if alliance_id:
                matches, _ = get_all_matches_for_alliance(event_id=event.id, event_code=getattr(event, 'code', None))
            else:
                matches = filter_matches_by_scouting_team().filter(Match.event_id == event.id).all()
        except Exception:
            try:
                param_str = str(raw_event_param)
                if param_str.startswith('alliance_'):
                    code = param_str[len('alliance_'):]
                else:
                    code = param_str
                event = get_event_by_code(code)
                matches, _ = get_all_matches_for_alliance(event_id=param_str, event_code=code)
            except Exception:
                matches = []
        try:
            matches = sorted(matches, key=match_sort_key)
        except Exception:
            pass

    # Get game configuration (alliance-aware)
    game_config = get_effective_game_config()

    # Attempt to generate compact summaries for each match. If analysis fails for a match,
    # include minimal info and continue so the page always renders.
    if matches:
        from app.utils.analysis import generate_match_strategy_analysis
        # Prepare display scores (prefer API-provided scores, fall back to local scouting data)
        try:
            scouting_team_number = current_user.scouting_team_number if getattr(current_user, 'is_authenticated', False) else None
        except Exception:
            scouting_team_number = None

        def _compute_local_scores_for_match(m):
            # Check if alliance mode is active
            alliance_id = get_active_alliance_id()
            from app.utils.analysis import get_current_epa_source, get_epa_metrics_for_team
            epa_source = get_current_epa_source()
            use_epa = epa_source in ('scouted_with_statbotics', 'statbotics_only', 'tba_opr_only', 'scouted_with_tba_opr')
            statbotics_only = epa_source in ('statbotics_only', 'tba_opr_only')

            entries = []
            if not statbotics_only:
                if alliance_id:
                    # Alliance mode - query from shared tables by match_number and event_code
                    # since match IDs differ across alliance members
                    from sqlalchemy import func
                    event = Event.query.get(m.event_id)
                    entries = AllianceSharedScoutingData.query.join(
                        Match, AllianceSharedScoutingData.match_id == Match.id
                    ).join(
                        Event, Match.event_id == Event.id
                    ).filter(
                        Match.match_number == m.match_number,
                        Match.match_type == m.match_type,
                        func.upper(Event.code) == func.upper(event.code) if event and event.code else Match.event_id == m.event_id,
                        AllianceSharedScoutingData.alliance_id == alliance_id,
                        AllianceSharedScoutingData.is_active == True
                    ).all()
                elif scouting_team_number:
                    # Exclude alliance-copied data when not in alliance mode
                    from sqlalchemy import or_
                    entries = ScoutingData.query.filter_by(match_id=m.id, scouting_team_number=scouting_team_number).filter(
                        or_(
                            ScoutingData.scout_name == None,
                            ~ScoutingData.scout_name.like('[Alliance-%')
                        )
                    ).all()

            if not entries and not use_epa:
                return (None, None)

            latest_by_team = {}
            for e in entries:
                tid = e.team_id
                if tid not in latest_by_team or (getattr(e, 'timestamp', None) and e.timestamp and e.timestamp > latest_by_team[tid].timestamp):
                    latest_by_team[tid] = e

            red_sum = 0
            blue_sum = 0
            any_points = False
            # m.red_alliance/blue_alliance stored as comma-separated strings of team numbers
            red_team_numbers = set([t.strip() for t in str(m.red_alliance or '').split(',') if t.strip()])
            blue_team_numbers = set([t.strip() for t in str(m.blue_alliance or '').split(',') if t.strip()])
            scored_team_numbers = set()
            has_scout_data = False  # True only when real scouting entries contributed

            for e in latest_by_team.values():
                try:
                    pts = int(e.calculate_metric('tot') or 0)
                except Exception:
                    pts = 0
                tn = None
                try:
                    tn = str(e.team.team_number) if e.team else None
                except Exception:
                    tn = None

                if tn in red_team_numbers:
                    red_sum += pts
                    any_points = any_points or pts > 0
                    scored_team_numbers.add(tn)
                    has_scout_data = True
                elif tn in blue_team_numbers:
                    blue_sum += pts
                    any_points = any_points or pts > 0
                    scored_team_numbers.add(tn)
                    has_scout_data = True

            # EPA fallback for teams without scouting data
            # Note: EPA scores are predictions only and must NOT be stored as actual match outcomes
            epa_contributed = False
            if use_epa:
                all_match_teams = red_team_numbers | blue_team_numbers
                for tn in all_match_teams:
                    if not statbotics_only and tn in scored_team_numbers:
                        continue
                    epa = get_epa_metrics_for_team(tn)
                    epa_total = epa.get('total') if epa else None
                    if epa_total and epa_total > 0:
                        if tn in red_team_numbers:
                            red_sum += int(epa_total)
                            epa_contributed = True
                        elif tn in blue_team_numbers:
                            blue_sum += int(epa_total)
                            epa_contributed = True

            if not any_points and not epa_contributed:
                return (None, None, None)
            # 'local' = real scouting data present; 'epa' = EPA/OPR prediction only
            score_source = 'local' if has_scout_data else 'epa'
            return (red_sum, blue_sum, score_source)
        for m in matches:
            try:
                data = generate_match_strategy_analysis(m.id)
                pred = data.get('predicted_outcome', {}) if isinstance(data, dict) else {}
                winner = pred.get('predicted_winner') if isinstance(pred, dict) else None
                # Confidence may be named differently across versions; try common keys
                confidence = None
                if isinstance(pred, dict):
                    confidence = pred.get('confidence') or pred.get('confidence_level') or pred.get('win_probability')

                # Determine display scores (prefer API-defined match scores)
                red_score = norm_db_score(m.red_score)
                blue_score = norm_db_score(m.blue_score)
                _local_epa_red = None
                _local_epa_blue = None
                if red_score is None and blue_score is None:
                    rloc, bloc, score_src = _compute_local_scores_for_match(m)
                    if score_src == 'epa':
                        # EPA/OPR data is a prediction — do NOT treat as actual match outcome
                        _local_epa_red = rloc
                        _local_epa_blue = bloc
                    else:
                        red_score = rloc if rloc is not None else None
                        blue_score = bloc if bloc is not None else None

                # Track whether we used predicted scores from analysis
                predicted_scores_used = False

                # Pull predicted scores from analysis (always include for comparison when available)
                predicted_red_score = None
                predicted_blue_score = None
                if isinstance(pred, dict):
                    # Predicted outcome commonly provides 'red_score' and 'blue_score'
                    p_red = pred.get('red_score') or pred.get('predicted_red') or pred.get('predicted_score')
                    p_blue = pred.get('blue_score') or pred.get('predicted_blue') or pred.get('predicted_score')
                    try:
                        if p_red is not None:
                            predicted_red_score = int(round(float(p_red)))
                    except Exception:
                        predicted_red_score = p_red if p_red is not None else None
                    try:
                        if p_blue is not None:
                            predicted_blue_score = int(round(float(p_blue)))
                    except Exception:
                        predicted_blue_score = p_blue if p_blue is not None else None

                    # If we still don't have any actual/local scores, prefer predicted outcome scores
                    # then EPA/OPR local predictions (clearly labelled as predictions, not outcomes)
                    if (red_score is None or blue_score is None):
                        try:
                            if red_score is None and predicted_red_score is not None:
                                red_score = int(predicted_red_score)
                                predicted_scores_used = True
                        except Exception:
                            if red_score is None and predicted_red_score is not None:
                                red_score = predicted_red_score
                                predicted_scores_used = True
                        try:
                            if blue_score is None and predicted_blue_score is not None:
                                blue_score = int(predicted_blue_score)
                                predicted_scores_used = True
                        except Exception:
                            if blue_score is None and predicted_blue_score is not None:
                                blue_score = predicted_blue_score
                                predicted_scores_used = True
                        # Last fallback: EPA/OPR local estimates (only if no other prediction available)
                        if red_score is None and _local_epa_red is not None:
                            predicted_scores_used = True
                            if predicted_red_score is None:
                                predicted_red_score = _local_epa_red
                        if blue_score is None and _local_epa_blue is not None:
                            predicted_scores_used = True
                            if predicted_blue_score is None:
                                predicted_blue_score = _local_epa_blue

                # Parse alliance team strings into structured lists with optional team lookup
                def _parse_alliance(alliance_str):
                    teams_out = []
                    if not alliance_str:
                        return teams_out
                    for tn in [t.strip() for t in str(alliance_str).split(',') if t.strip()]:
                        team_obj = None
                        try:
                            tn_int = int(tn)
                            team_obj = filter_teams_by_scouting_team().filter(Team.team_number == tn_int).first()
                        except Exception:
                            team_obj = None
                        teams_out.append({
                            'team_number': tn,
                            'team_id': team_obj.id if team_obj else None,
                            'team_name': team_obj.team_name if team_obj and getattr(team_obj, 'team_name', None) else None
                        })
                    return teams_out

                summaries.append({
                    'match_id': m.id,
                    'match_type': m.match_type,
                    'match_number': m.match_number,
                    'red_alliance': m.red_alliance,
                    'blue_alliance': m.blue_alliance,
                    'red_teams': _parse_alliance(m.red_alliance),
                    'blue_teams': _parse_alliance(m.blue_alliance),
                    'red_score': red_score,
                    'blue_score': blue_score,
                    'predicted_red_score': predicted_red_score,
                    'predicted_blue_score': predicted_blue_score,
                    'predicted_winner': winner,
                    'confidence': confidence,
                    'predicted_scores_used': predicted_scores_used,
                    'error': None
                })
            except Exception as e:
                # Keep a minimal fallback so UI can at least show match and teams
                # Attempt to at least include parsed team lists and any available scores
                r_score = norm_db_score(m.red_score)
                b_score = norm_db_score(m.blue_score)
                if r_score is None and b_score is None:
                    rloc, bloc, score_src = _compute_local_scores_for_match(m)
                    if score_src != 'epa':  # EPA-only must not become an actual match score
                        r_score = rloc if rloc is not None else None
                        b_score = bloc if bloc is not None else None

                def _parse_alliance_safe(alliance_str):
                    return [ {'team_number': t.strip(), 'team_id': None, 'team_name': None} for t in str(alliance_str or '').split(',') if t.strip() ]

                summaries.append({
                    'match_id': m.id,
                    'match_type': m.match_type,
                    'match_number': m.match_number,
                    'red_alliance': m.red_alliance,
                    'blue_alliance': m.blue_alliance,
                    'red_teams': _parse_alliance_safe(m.red_alliance),
                    'blue_teams': _parse_alliance_safe(m.blue_alliance),
                    'red_score': r_score,
                    'blue_score': b_score,
                    'predicted_winner': None,
                    'confidence': None,
                    'error': str(e)
                })

    return render_template('matches/strategy_all.html', events=events, selected_event=event, matches=matches, game_config=game_config, summaries=summaries, **get_theme_context())

@bp.route('/strategy/analyze/<int:match_id>')
@login_required
def analyze_strategy(match_id):
    """Generate strategy analysis for a specific match"""
    from app.utils.analysis import generate_match_strategy_analysis
    
    # Check if user has analytics permission
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401
    
    user_roles = current_user.get_role_names()
    if not any(role in user_roles for role in ['admin', 'analytics']):
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    # Get the match
    match = Match.query.get_or_404(match_id)
    
    # Generate strategy analysis
    try:
        strategy_data = generate_match_strategy_analysis(match_id)
        
        if not strategy_data:
            return jsonify({'error': 'Unable to generate strategy analysis for this match'}), 404
        
        # Convert Team objects to dictionaries to make them JSON serializable
        def serialize_team_data(team_data):
            if isinstance(team_data, dict) and 'team' in team_data:
                serialized = team_data.copy()
                serialized['team'] = {
                    'id': team_data['team'].id,
                    'team_number': team_data['team'].team_number,
                    'team_name': team_data['team'].team_name,
                    'location': team_data['team'].location
                }
                # Remove scouting_data as it's not JSON serializable and not needed for frontend
                if 'scouting_data' in serialized:
                    del serialized['scouting_data']
                return serialized
            return team_data
        
        # Serialize red alliance teams
        if 'red_alliance' in strategy_data and 'teams' in strategy_data['red_alliance']:
            strategy_data['red_alliance']['teams'] = [
                serialize_team_data(team_data) for team_data in strategy_data['red_alliance']['teams']
            ]
        
        # Serialize blue alliance teams
        if 'blue_alliance' in strategy_data and 'teams' in strategy_data['blue_alliance']:
            strategy_data['blue_alliance']['teams'] = [
                serialize_team_data(team_data) for team_data in strategy_data['blue_alliance']['teams']
            ]
        
        print(f"DEBUG: Strategy data keys: {strategy_data.keys()}")
        print(f"DEBUG: Red alliance teams count: {len(strategy_data.get('red_alliance', {}).get('teams', []))}")
        print(f"DEBUG: Blue alliance teams count: {len(strategy_data.get('blue_alliance', {}).get('teams', []))}")
        
        return jsonify(strategy_data)
    except Exception as e:
        print(f"ERROR in analyze_strategy: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Error generating strategy analysis: {str(e)}'}), 500


@bp.route('/strategy/share', methods=['POST'])
@login_required
def create_strategy_share():
    """Create a public share token for a match strategy.

    Expects JSON body: {"match_id": <int>}
    Returns: {"url": ".../matches/strategy/public/<token>"}
    """
    # Only allow users with appropriate roles to create shares
    user_roles = current_user.get_role_names()
    if not any(role in user_roles for role in ['admin', 'analytics']):
        return jsonify({'error': 'Insufficient permissions'}), 403

    data = request.get_json() or {}
    match_id = data.get('match_id')
    if not match_id:
        return jsonify({'error': 'match_id required'}), 400

    match = Match.query.get(match_id)
    if not match:
        return jsonify({'error': 'Match not found'}), 404

    import secrets, json
    token = secrets.token_urlsafe(24)

    # File-backed storage for shares to avoid DB migrations
    shares_file = os.path.join(current_app.instance_path, 'strategy_shares.json')
    os.makedirs(current_app.instance_path, exist_ok=True)
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
        else:
            shares = {}
    except Exception:
        shares = {}

    shares[token] = {
        'match_id': match_id,
        'created_by': current_user.id if current_user.is_authenticated else None,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'revoked': False
    }

    # Attempt to generate and store the serialized strategy data so public viewers get immediate results
    try:
        from app.utils.analysis import generate_match_strategy_analysis
        strategy_data = generate_match_strategy_analysis(match_id)
        if strategy_data:
            # Serialize team objects to primitives (like public_analyze_strategy does)
            def serialize_team_data(team_data):
                if isinstance(team_data, dict) and 'team' in team_data:
                    serialized = team_data.copy()
                    team = serialized.get('team')
                    if hasattr(team, 'id'):
                        serialized['team'] = {
                            'id': team.id,
                            'team_number': team.team_number,
                            'team_name': team.team_name,
                            'location': team.location
                        }
                    # drop scouting_data for size and privacy
                    if 'scouting_data' in serialized:
                        del serialized['scouting_data']
                    return serialized
                return team_data

            if 'red_alliance' in strategy_data and 'teams' in strategy_data['red_alliance']:
                strategy_data['red_alliance']['teams'] = [serialize_team_data(td) for td in strategy_data['red_alliance']['teams']]
            if 'blue_alliance' in strategy_data and 'teams' in strategy_data['blue_alliance']:
                strategy_data['blue_alliance']['teams'] = [serialize_team_data(td) for td in strategy_data['blue_alliance']['teams']]

            shares[token]['data'] = strategy_data
            shares[token]['data_generated_at'] = datetime.now(timezone.utc).isoformat()
    except Exception:
        # If analysis generation fails, continue without preloaded data
        pass

    # Atomic write
    tmp_path = shares_file + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(shares, f)
    os.replace(tmp_path, shares_file)

    # Prefer client-provided origin (browser's address) so shared link uses the same host
    from urllib.parse import urlparse
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    if origin:
        # Normalize origin to scheme://host[:port]
        parsed = urlparse(origin)
        base = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base = request.url_root.rstrip('/')

    public_path = url_for('matches.public_strategy_view', token=token)
    # Return only the path; client JS will prepend the client's origin
    return jsonify({'path': public_path, 'token': token})


@bp.route('/strategy/public/<token>')
def public_strategy_view(token):
    """Public-facing strategy page rendered without authentication when a valid token is provided."""
    # Load file-backed shares
    import json
    shares_file = os.path.join(current_app.instance_path, 'strategy_shares.json')
    share = None
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
                entry = shares.get(token)
                if entry and not entry.get('revoked'):
                    share = entry
    except Exception:
        share = None

    if not share:
        flash('Shared strategy not found or access revoked.', 'danger')
        return redirect(url_for('matches.strategy'))

    # Render the same template but include the token and shared match id so JS can call the public analyze endpoint
    events = get_combined_dropdown_events()
    game_config = get_effective_game_config()
    # Fetch the match for the share
    match = Match.query.get(share.get('match_id'))
    selected_event = match.event if match else None
    matches = [match] if match else []
    # Provide preloaded data if available to avoid an extra analyze fetch
    preloaded = None
    try:
        if 'data' in shares and token in shares:
            # This branch won't be reached because shares variable is local above — read file again safely
            pass
        # Read the entry again to get any stored 'data'
        with open(shares_file, 'r') as f:
            all_shares = json.load(f) or {}
            entry = all_shares.get(token)
            if entry and entry.get('data'):
                preloaded = entry.get('data')
    except Exception:
        preloaded = None

    return render_template('matches/strategy.html', events=events, selected_event=selected_event, matches=matches, game_config=game_config, public_share_token=token, public_shared_match_id=match.id if match else None, public_strategy_data=preloaded, **get_theme_context())


@bp.route('/strategy/public/analyze/<token>/<int:match_id>')
def public_analyze_strategy(token, match_id):
    """Public analyze endpoint that returns strategy JSON if token is valid for the match."""
    # Validate token against file-backed store
    import json
    shares_file = os.path.join(current_app.instance_path, 'strategy_shares.json')
    try:
        if os.path.exists(shares_file):
            with open(shares_file, 'r') as f:
                shares = json.load(f) or {}
                entry = shares.get(token)
                if not entry or entry.get('revoked') or int(entry.get('match_id')) != int(match_id):
                    return jsonify({'error': 'Invalid or revoked share token'}), 403
        else:
            return jsonify({'error': 'Invalid or revoked share token'}), 403
    except Exception as e:
        return jsonify({'error': 'Invalid or revoked share token'}), 403

    from app.utils.analysis import generate_match_strategy_analysis
    # First try to return precomputed data from the share file to save time
    try:
        with open(shares_file, 'r') as f:
            shares = json.load(f) or {}
            entry = shares.get(token)
            if entry and entry.get('data'):
                return jsonify(entry.get('data'))
    except Exception:
        # Fall back to live computation if reading precomputed data fails
        pass

    try:
        strategy_data = generate_match_strategy_analysis(match_id)
        if not strategy_data:
            return jsonify({'error': 'Unable to generate strategy analysis for this match'}), 404

        # Reuse serialization logic from analyze_strategy
        def serialize_team_data(team_data):
            if isinstance(team_data, dict) and 'team' in team_data:
                serialized = team_data.copy()
                serialized['team'] = {
                    'id': team_data['team'].id,
                    'team_number': team_data['team'].team_number,
                    'team_name': team_data['team'].team_name,
                    'location': team_data['team'].location
                }
                if 'scouting_data' in serialized:
                    del serialized['scouting_data']
                return serialized
            return team_data

        if 'red_alliance' in strategy_data and 'teams' in strategy_data['red_alliance']:
            strategy_data['red_alliance']['teams'] = [serialize_team_data(td) for td in strategy_data['red_alliance']['teams']]
        if 'blue_alliance' in strategy_data and 'teams' in strategy_data['blue_alliance']:
            strategy_data['blue_alliance']['teams'] = [serialize_team_data(td) for td in strategy_data['blue_alliance']['teams']]

        return jsonify(strategy_data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/strategy/draw')
@login_required
def strategy_draw():
    """Strategy drawing page for matches"""
    # Only allow users with analytics or admin role
    user_roles = current_user.get_role_names()
    if not any(role in user_roles for role in ['admin', 'analytics']):
        flash('Insufficient permissions to access strategy drawing.', 'danger')
        return redirect(url_for('matches.index'))

    events = get_combined_dropdown_events()
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    event_id = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    event = None
    matches = []
    if event_id:
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        # Prefer an alliance synthetic entry when alliance mode is active
        try:
            # events list may contain synthetic alliance entries created in get_combined_dropdown_events
            evt = next((e for e in events if getattr(e, 'is_alliance', False) and (getattr(e, 'code', '') or '').upper() == str(current_event_code).upper()), None)
            if evt:
                event = evt
            else:
                event = get_event_by_code(current_event_code)
        except Exception:
            event = get_event_by_code(current_event_code)

    if event:
        # If the selected event is a synthetic alliance entry (id like 'alliance_CODE'),
        # match by event code across alliance members instead of by numeric id.
        try:
            is_synthetic = isinstance(getattr(event, 'id', None), str) and str(event.id).startswith('alliance_')
        except Exception:
            is_synthetic = False

        if is_synthetic:
            code = getattr(event, 'code', None)
            if code:
                from sqlalchemy import func
                matches = filter_matches_by_scouting_team().join(Event, Match.event_id == Event.id).filter(func.upper(Event.code) == str(code).upper()).all()
                matches = sorted(matches, key=match_sort_key)
            else:
                matches = []
        else:
            matches = filter_matches_by_scouting_team().filter(Match.event_id == event.id).all()
            # Use global match_sort_key for proper ordering (handles X-Y playoff format)
            matches = sorted(matches, key=match_sort_key)
    return render_template(
        'matches/strategy_draw.html',
        events=events,
        selected_event=event,
        matches=matches,
        game_config=game_config, **get_theme_context()
    )

@bp.route('/api/strategy_drawing/<int:match_id>', methods=['GET'])
@login_required
def get_strategy_drawing(match_id):
    # Use a single drawing per match (match_id is unique in the model). Fall back to global drawing.
    drawing = StrategyDrawing.query.filter_by(match_id=match_id).first()
    if drawing:
        bg_url = url_for('matches.get_strategy_background', filename=drawing.background_image) if drawing.background_image else None
        return jsonify({'data': drawing.data, 'last_updated': drawing.last_updated.isoformat() if drawing.last_updated else None, 'background_image': bg_url})
    else:
        return jsonify({'data': None, 'last_updated': None, 'background_image': None})


@bp.route('/api/strategy_drawing/<int:match_id>', methods=['POST'])
@login_required
def save_strategy_drawing(match_id):
    """Persist strategy drawing data for a match (fallback to REST when Socket.IO is unavailable)."""
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    drawing_data = payload.get('data') if payload else None
    if drawing_data is None:
        return jsonify({'error': 'Missing drawing data'}), 400

    try:
        # Use single per-match drawing (match_id unique)
        drawing = StrategyDrawing.query.filter_by(match_id=match_id).first()
        if not drawing:
            drawing = StrategyDrawing(match_id=match_id, data_json='{}')
            db.session.add(drawing)
        drawing.data = drawing_data
        db.session.commit()

        # Notify other clients via Socket.IO room if socketio is available
        try:
            room = f'strategy_match_{match_id}'
            socketio.emit('drawing_data', {
                'match_id': match_id,
                'data': drawing_data,
                'last_updated': drawing.last_updated.isoformat() if drawing.last_updated else None
            }, room=room, include_self=False)
        except Exception:
            current_app.logger.debug('SocketIO emit failed during REST save (non-fatal)')

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.exception('Failed to save strategy drawing')
        return jsonify({'error': str(e)}), 500

# Socket.IO events for real-time strategy drawing sync
@socketio.on('join_strategy_room')
def on_join_strategy_room(data):
    match_id = data.get('match_id')
    try:
        sid = getattr(request, 'sid', None)
    except Exception:
        sid = None
    if match_id:
        room = f'strategy_match_{match_id}'
        join_room(room)
        current_app.logger.debug(f"Socket join_strategy_room: sid={sid} joining room={room}")
        # Send current drawing data to the new client
        drawing = StrategyDrawing.query.filter_by(match_id=match_id).first()
        emit('drawing_data', {
            'match_id': match_id,
            'data': drawing.data if drawing else None,
            'last_updated': drawing.last_updated.isoformat() if drawing and drawing.last_updated else None
        })

@socketio.on('drawing_update')
def on_drawing_update(data):
    match_id = data.get('match_id')
    drawing_data = data.get('data')
    try:
        sid = getattr(request, 'sid', None)
    except Exception:
        sid = None
    if not match_id or drawing_data is None:
        return
    current_app.logger.debug(f"drawing_update received from sid={sid} for match={match_id}; points={len(drawing_data) if drawing_data else 0}")
    # Save to DB
    drawing = StrategyDrawing.query.filter_by(match_id=match_id).first()
    if not drawing:
        drawing = StrategyDrawing(match_id=match_id, data_json='{}')
        db.session.add(drawing)
    drawing.data = drawing_data
    db.session.commit()
    # Broadcast to all clients in the room (except sender)
    room = f'strategy_match_{match_id}'
    current_app.logger.debug(f"Broadcasting drawing_data to room={room} (include_self=False)")
    emit('drawing_data', {
        'match_id': match_id,
        'data': drawing_data,
        'last_updated': drawing.last_updated.isoformat() if drawing.last_updated else None
    }, room=room, include_self=False)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
STRATEGY_BG_UPLOAD_FOLDER = os.path.join('app', 'static', 'strategy_backgrounds')

@bp.route('/api/strategy_background', methods=['POST'])
@login_required
def upload_strategy_background():
    if 'background' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['background']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Determine team-specific folder (fall back to global if no scouting team)
    team_number = getattr(current_user, 'scouting_team_number', None)

    try:
        img = Image.open(file.stream)

        if team_number:
            team_folder = os.path.join(STRATEGY_BG_UPLOAD_FOLDER, str(team_number))
            os.makedirs(team_folder, exist_ok=True)
            save_path = os.path.join(team_folder, 'default_bg.png')
            img.convert('RGBA').save(save_path, format='PNG')
            bg_url = url_for('matches.get_strategy_background', filename=f"{team_number}/default_bg.png")
        else:
            # global default
            os.makedirs(STRATEGY_BG_UPLOAD_FOLDER, exist_ok=True)
            save_path = os.path.join(STRATEGY_BG_UPLOAD_FOLDER, 'default_bg.png')
            img.convert('RGBA').save(save_path, format='PNG')
            bg_url = url_for('matches.get_strategy_background', filename='default_bg.png')

    except Exception as e:
        return jsonify({'error': f'Image conversion failed: {str(e)}'}), 400

    # Notify via Socket.IO so clients can update their background image
    socketio.emit('background_image_update', {
        'match_id': None,
        'background_image': bg_url
    })
    return jsonify({'background_image': bg_url})

@bp.route('/strategy_backgrounds/<path:filename>')
def get_strategy_background(filename):
    # Serve team-specific or global strategy background files from the strategy_backgrounds folder.
    # filename may include a team subfolder (e.g. "5568/default_bg.png").
    return send_from_directory(os.path.abspath(STRATEGY_BG_UPLOAD_FOLDER), filename)

@bp.route('/data')
@analytics_required
def matches_data():
    """AJAX endpoint for matches data - used for real-time config updates"""
    try:
        # Allow optional event_id to request matches for a specific event (useful for strategy/live)
        event_id_param = request.args.get('event_id', type=int)
        # Get event code from config (alliance-aware)
        game_config = get_effective_game_config()
        current_event_code = game_config.get('current_event_code')
        
        if not current_event_code:
            return jsonify({
                'success': True,
                'matches': [],
                'current_event': None,
                'message': 'No event selected in configuration',
                'timestamp': utc_now_iso()
            })
        
        # Determine which event to return: prefer explicit event_id param if provided
        current_event = None
        if event_id_param:
            # Respect scouting-team filtering
            current_event = filter_events_by_scouting_team().filter(Event.id == event_id_param).first()
            if not current_event:
                return jsonify({
                    'success': True,
                    'matches': [],
                    'current_event': None,
                    'message': f'Event id {event_id_param} not found or not accessible',
                    'timestamp': utc_now_iso()
                })
        else:
            current_event = get_event_by_code(current_event_code)
        if not current_event:
            return jsonify({
                'success': True,
                'matches': [],
                'current_event': None,
                'message': f'Event {current_event_code} not found',
                'timestamp': utc_now_iso()
            })
        
        # Get matches for this event using event code matching for cross-team scenarios
        from sqlalchemy import func as match_func
        match_event_code = getattr(current_event, 'code', None)
        if match_event_code:
            matches_query = filter_matches_by_scouting_team().join(Event, Match.event_id == Event.id).filter(match_func.upper(Event.code) == match_event_code.upper())
        else:
            matches_query = filter_matches_by_scouting_team().filter_by(event_id=current_event.id)
        # Defensive check: ensure we only show matches for current scouting team
        from app.utils.team_isolation import get_current_scouting_team_number
        current_scouting_team = get_current_scouting_team_number()
        if current_scouting_team is not None:
            matches_query = matches_query.filter(Match.scouting_team_number == current_scouting_team)
        else:
            matches_query = matches_query.filter(Match.scouting_team_number.is_(None))
        matches = matches_query.all()
        # Use global match_sort_key for proper ordering (handles X-Y playoff format)
        matches = sorted(matches, key=match_sort_key)
        
        # Get team data for context - use event code matching for cross-team scenarios
        from sqlalchemy import func as ctx_func
        ctx_event_code = getattr(current_event, 'code', None)
        if ctx_event_code:
            teams = filter_teams_by_scouting_team().join(Team.events).filter(ctx_func.upper(Event.code) == ctx_event_code.upper()).all()
        else:
            teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).all()
        
        # Helper: format a datetime the same way the matches index page does
        # (server-side conversion so client never needs to guess timezone)
        from app.utils.timezone_utils import format_time_with_timezone as _fmt_tz
        _evt_tz = getattr(current_event, 'timezone', None) if current_event else None

        def _format_display_time(dt, evt_obj):
            if dt is None:
                return ''
            etz = getattr(evt_obj, 'timezone', None) if evt_obj else _evt_tz
            return _fmt_tz(dt, etz, '%I:%M %p')

        # Prepare matches data for JSON
        matches_data = []
        for match in matches:
            # Normalize scores so that negative sentinels like -1 are treated as None
            red_db = norm_db_score(match.red_score)
            blue_db = norm_db_score(match.blue_score)

            # Build alliance team lists robustly to support multiple schema shapes
            def _extract_alliance_teams(match_obj, prefix_red=True):
                teams_out = []
                try:
                    if prefix_red:
                        t1 = getattr(match_obj, 'red_1', None)
                        t2 = getattr(match_obj, 'red_2', None)
                        t3 = getattr(match_obj, 'red_3', None)
                    else:
                        t1 = getattr(match_obj, 'blue_1', None)
                        t2 = getattr(match_obj, 'blue_2', None)
                        t3 = getattr(match_obj, 'blue_3', None)
                    for t in (t1, t2, t3):
                        if t is not None:
                            teams_out.append(t)
                except Exception:
                    teams_out = []

                # Fallback: comma-separated alliance string (red_alliance / blue_alliance)
                if not teams_out:
                    try:
                        s = getattr(match_obj, 'red_alliance' if prefix_red else 'blue_alliance', None)
                        if s:
                            teams_out = [x.strip() for x in str(s).split(',') if x.strip()]
                    except Exception:
                        teams_out = []

                # Final fallback: list attribute like red_teams/blue_teams
                if not teams_out:
                    try:
                        lt = getattr(match_obj, 'red_teams' if prefix_red else 'blue_teams', None)
                        if lt:
                            if isinstance(lt, (list, tuple)):
                                teams_out = [str(x) for x in lt]
                            else:
                                teams_out = [x.strip() for x in str(lt).split(',') if x.strip()]
                    except Exception:
                        teams_out = []

                return teams_out

            # Robustly handle datetime-like fields that may be absent in some schemas
            _predicted_dt = getattr(match, 'predicted_time', None)
            _actual_dt = getattr(match, 'actual_time', None)
            _scheduled_dt = getattr(match, 'scheduled_time', None)
            _played_dt = _actual_dt or _scheduled_dt

            def _iso_utc(dt):
                """Serialize a datetime to ISO-8601 with UTC offset (+00:00).
                Datetimes are stored as naive UTC in SQLite; without the tz suffix
                browsers treat the string as local time (ES2015+) causing timing bugs."""
                if dt is None:
                    return None
                # If already timezone-aware, isoformat() includes the offset
                if getattr(dt, 'tzinfo', None) is not None:
                    return dt.isoformat()
                # Naive datetime assumed UTC – append explicit UTC offset
                return dt.isoformat() + '+00:00'

            def _to_utc_epoch_ms(dt):
                """Convert a datetime to UTC epoch milliseconds.
                Naive datetimes are treated as UTC (not local time).
                Returns None if dt is None."""
                if dt is None:
                    return None
                if getattr(dt, 'tzinfo', None) is not None:
                    return int(dt.timestamp() * 1000)
                # Naive → force UTC interpretation
                return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

            # Best time for scheduling purposes
            _best_dt = _predicted_dt or _scheduled_dt

            match_data = {
                'id': match.id,
                'event_id': match.event_id,
                'match_number': match.match_number,
                'comp_level': getattr(match, 'comp_level', None) or getattr(match, 'match_type', None),
                'set_number': getattr(match, 'set_number', None),
                'predicted_time': _iso_utc(_predicted_dt),
                'scheduled_time': _iso_utc(_scheduled_dt),
                'actual_time': _iso_utc(_actual_dt),
                'played_time': _iso_utc(_played_dt),
                'scheduled_time_ms': _to_utc_epoch_ms(_best_dt),
                'display_time': _format_display_time(_best_dt, current_event),
                'alliances': {
                    'red': {
                        'teams': _extract_alliance_teams(match, True),
                        'score': red_db
                    },
                    'blue': {
                        'teams': _extract_alliance_teams(match, False),
                        'score': blue_db
                    }
                },
                'winner': getattr(match, 'winner', None),
                'status': 'completed' if (_actual_dt or getattr(match, 'winner', None) or (red_db is not None or blue_db is not None)) else 'upcoming'
            }
            matches_data.append(match_data)

        # Get teams data
        teams_data = [{'id': team.id, 'team_number': team.team_number, 'name': getattr(team, 'team_name', None) or getattr(team, 'name', None) or ''} for team in teams]

        return jsonify({
            'success': True,
            'game_config': game_config,
            'current_event': {
                'id': current_event.id,
                'name': current_event.name,
                'code': current_event.code,
                'start_date': current_event.start_date.isoformat() if current_event.start_date else None,
                'end_date': current_event.end_date.isoformat() if current_event.end_date else None,
                'schedule_offset_minutes': getattr(current_event, 'schedule_offset', None) or 0,
                'offset_updated_at': _iso_utc(getattr(current_event, 'offset_updated_at', None)),
                'timezone': getattr(current_event, 'timezone', None),
            },
            'matches': matches_data,
            'teams': teams_data,
            'stats': {
                'total_matches': len(matches_data),
                'completed_matches': len([m for m in matches_data if m['status'] == 'completed']),
                'upcoming_matches': len([m for m in matches_data if m['status'] == 'upcoming'])
            },
            'timestamp': utc_now_iso(),
            'server_time_ms': int(datetime.now(timezone.utc).timestamp() * 1000)
        })
    except Exception as e:
        import traceback as _tb
        tb = _tb.format_exc()
        current_app.logger.error(f"Error in matches_data endpoint: {str(e)}\n{tb}")
        # Return traceback in JSON to aid local debugging (safe for dev environments)
        return jsonify({'success': False, 'error': str(e), 'trace': tb}), 500
