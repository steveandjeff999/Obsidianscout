from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import Match, Event, Team, ScoutingData
from app import db
from app.utils.api_utils import get_matches, ApiError, api_to_db_match_conversion, get_matches_dual_api
from datetime import datetime, timezone
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
from app.utils.team_isolation import (
    filter_matches_by_scouting_team, filter_events_by_scouting_team,
    filter_teams_by_scouting_team, assign_scouting_team_to_model, get_event_by_code
)
from sqlalchemy import or_

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }


def norm_db_score(val):
    """Normalize a score value coming from the DB/API: treat negative or invalid scores as None.

    Many APIs use -1 as a sentinel for "no score yet". Treat those as None so the UI
    and status logic don't consider the match played.
    """
    try:
        if val is None:
            return None
        v = int(val)
        if v < 0:
            return None
        return v
    except Exception:
        return None

bp = Blueprint('matches', __name__, url_prefix='/matches')

@bp.route('/')
@analytics_required
def index():
    """Display matches for the current event from configuration"""
    # Get event code from config
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    
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
    
    # Get all events for the dropdown (filtered by scouting team)
    events = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.name).all()
    
    # Filter matches by the selected event and scouting team
    if event:
        # Define custom ordering for match types
        match_type_order = {
            'practice': 1,
            'qualification': 2,
            'qualifier': 2,  # Alternative name for qualification matches
            'playoff': 3,
            'elimination': 3,  # Alternative name for playoff matches
        }
        # Build base query for this event (filtered by scouting team)
        query = filter_matches_by_scouting_team().filter(Match.event_id == event.id)

        # Apply optional filters from the request
        q = (request.args.get('q') or '').strip()
        match_type = (request.args.get('match_type') or '').strip()

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
        matches = sorted(matches, key=lambda m: (
            match_type_order.get((m.match_type or '').lower(), 99),
            m.match_number
        ))
    else:
        # If no event selected, don't show any matches
        matches = []
        flash("No current event selected. Use the dropdown to select an event or configure a default event code.", "warning")
    
    # Compute display scores: prefer API (match.red_score/blue_score) and fall back to local scouting data
    display_scores = {}
    try:
        # Only attempt local fallback if we have an authenticated user with a scouting team
        scouting_team_number = current_user.scouting_team_number if getattr(current_user, 'is_authenticated', False) else None
    except Exception:
        scouting_team_number = None

    def _compute_local_scores_for_match(m):
        # Gather scouting entries for this match and scouting team
        if not scouting_team_number:
            return (None, None)
        entries = ScoutingData.query.filter_by(match_id=m.id, scouting_team_number=scouting_team_number).all()
        if not entries:
            return (None, None)

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
            elif tn in blue_team_numbers:
                blue_sum += pts
                any_points = any_points or pts > 0

        if not any_points:
            return (None, None)
        return (red_sum, blue_sum)


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
            r, b = _compute_local_scores_for_match(match)
            if r is not None or b is not None:
                display_scores[match.id] = {
                    'red_score': r,
                    'blue_score': b,
                    'source': 'local'
                }
            else:
                display_scores[match.id] = {'red_score': None, 'blue_score': None, 'source': None}

    return render_template('matches/index.html', matches=matches, events=events, selected_event=event, display_scores=display_scores, **get_theme_context())

@bp.route('/sync_from_config')
def sync_from_config():
    """Sync matches from FIRST API using the event code from config file"""
    try:
        # Get event code from config
        game_config = get_effective_game_config()
        event_code = game_config.get('current_event_code')
        
        if not event_code:
            flash("No event code found in configuration. Please add 'current_event_code' to your game_config.json file.", 'danger')
            return redirect(url_for('matches.index'))
        
        # Find or create the event in our database (filtered by scouting team)
        current_year = game_config.get('season', 2026)
        event = get_event_by_code(event_code)
        if not event:
            # Try to fetch full event details including timezone from API
            from app.utils.api_utils import get_event_details_dual_api
            event_details = get_event_details_dual_api(event_code)
            
            if event_details:
                event = Event(
                    name=event_details.get('name', f"Event {event_code}"),
                    code=event_code,
                    timezone=event_details.get('timezone'),  # Store timezone from API
                    location=event_details.get('location'),
                    start_date=event_details.get('start_date'),
                    end_date=event_details.get('end_date'),
                    year=event_details.get('year', current_year)
                )
            else:
                # Fallback to placeholder
                event = Event(
                    name=f"Event {event_code}",
                    code=event_code,
                    year=current_year
                )
            assign_scouting_team_to_model(event)  # Assign current scouting team
            db.session.add(event)
            db.session.flush()  # Get the ID without committing yet
        
        # Fetch matches from the dual API using the event code
        match_data_list = get_matches_dual_api(event_code)
        
        # Track metrics for user feedback
        matches_added = 0
        matches_updated = 0
        
        # Import DisableReplication to prevent queue issues during bulk operations
        from app.utils.real_time_replication import DisableReplication
        
        # Temporarily disable replication during bulk sync to prevent queue issues
        with DisableReplication():
            # Process each match from the API
            for match_data in match_data_list:
                # Set the event_id for the match
                match_data['event_id'] = event.id
                
                if not match_data:
                    continue
                    
                match_number = match_data.get('match_number')
                match_type = match_data.get('match_type')
                
                if not match_number or not match_type:
                    continue
                
                # Check if the match already exists for this scouting team
                match = filter_matches_by_scouting_team().filter(
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
                    matches_updated += 1
                else:
                    # Add new match
                    match = Match(**match_data)
                    assign_scouting_team_to_model(match)  # Assign current scouting team
                    db.session.add(match)
                    matches_added += 1
            
            # Commit all changes
            db.session.commit()
        
        # Update match times from API after syncing matches
        try:
            from app.utils.match_time_fetcher import update_match_times
            times_updated = update_match_times(event_code, current_app.config.get('TEAM_NUMBER'))
            if times_updated > 0:
                print(f"✅ Updated scheduled times for {times_updated} matches")
        except Exception as e:
            print(f"⚠️  Could not update match times: {e}")
        
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
        flash(f"API Error: {str(e)}", 'danger')
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
        event_code = game_config.get('current_event_code')
        
        if not event_code:
            flash("No event code found in configuration.", 'danger')
            return redirect(url_for('matches.index'))
        
        # Update match times
        from app.utils.match_time_fetcher import update_match_times
        times_updated = update_match_times(event_code, current_app.config.get('TEAM_NUMBER'))
        
        if times_updated > 0:
            flash(f"✅ Updated scheduled times for {times_updated} matches!", 'success')
        else:
            flash("No match times needed updating.", 'info')
        
    except Exception as e:
        flash(f"Error updating match times: {str(e)}", 'danger')
    
    return redirect(url_for('matches.index'))


@bp.route('/<int:match_id>')
def view(match_id):
    """View match details and related scouting data"""
    match = Match.query.get_or_404(match_id)
    
    # Get scouting data for this match
    scouting_data = ScoutingData.query.filter_by(match_id=match.id, scouting_team_number=current_user.scouting_team_number).all()
    
    # Get game configuration
    game_config = get_effective_game_config()
    # Compute display score for this match (prefer API, fallback to local scouting data)
    display_score = {'red_score': None, 'blue_score': None, 'source': None}
    # Normalize stored scores so negative sentinel values don't mark the match as played
    red_db = norm_db_score(match.red_score)
    blue_db = norm_db_score(match.blue_score)
    if red_db is not None or blue_db is not None:
        display_score = {'red_score': red_db, 'blue_score': blue_db, 'source': 'api'}
    else:
        try:
            scouting_team_number = current_user.scouting_team_number if getattr(current_user, 'is_authenticated', False) else None
        except Exception:
            scouting_team_number = None

        if scouting_team_number:
            entries = ScoutingData.query.filter_by(match_id=match.id, scouting_team_number=scouting_team_number).all()
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
                    elif tn in blue_team_numbers:
                        blue_sum += pts
                        any_points = any_points or pts > 0

                if any_points:
                    display_score = {'red_score': red_sum, 'blue_score': blue_sum, 'source': 'local'}

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
    
    events = filter_events_by_scouting_team().all()
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
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
                    db.session.add(team_obj)
                    db.session.flush()
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Failed to create team {tn}: {e}")
                    return None

            # Associate the team with the event if not already
            try:
                ev = Event.query.get(event_id)
                if ev and ev not in team_obj.events:
                    team_obj.events.append(ev)
                    db.session.flush()
            except Exception:
                db.session.rollback()

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
    events = filter_events_by_scouting_team().all()
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()
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
    
    # Delete associated scouting data
    ScoutingData.query.filter_by(match_id=match.id, scouting_team_number=current_user.scouting_team_number).delete()
    
    db.session.delete(match)
    db.session.commit()
    
    flash(f'Match deleted successfully!', 'success')
    return redirect(url_for('matches.index'))

@bp.route('/strategy')
@analytics_required
def strategy():
    """Match strategy analysis page"""
    # Get all events for the dropdown
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    
    # Get event from URL parameter or form
    event_id = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    event = None
    matches = []
    
    if event_id:
        # If a specific event ID is requested, use that
        event = Event.query.get_or_404(event_id)
        
        # Get all matches for this event
        matches = Match.query.filter_by(event_id=event.id).all()
        # Custom match type order: practice, qualification, quarterfinals, semifinals, finals
        match_type_order = {
            'practice': 1,
            'qualification': 2,
            'qualifier': 2,  # Alternative name for qualification matches
            'quarterfinal': 3,
            'quarterfinals': 3,
            'semifinal': 4,
            'semifinals': 4,
            'final': 5,
            'finals': 5
        }
        def match_sort_key(m):
            return (
                match_type_order.get(m.match_type.lower(), 99),
                m.match_number
            )
        matches = sorted(matches, key=match_sort_key)
    
    # Get game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})
    
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


@bp.route('/strategy/all')
@analytics_required
def strategy_all():
    """Show a compact strategy summary card for every match in an event."""
    # Get all events for the dropdown
    events = Event.query.order_by(Event.year.desc(), Event.name).all()

    # Get event from URL parameter or form
    event_id = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    event = None
    matches = []
    summaries = []

    if event_id:
        event = Event.query.get_or_404(event_id)
        matches = Match.query.filter_by(event_id=event.id).all()
        # Keep same ordering as other strategy pages
        match_type_order = {
            'practice': 1,
            'qualification': 2,
            'qualifier': 2,
            'quarterfinal': 3,
            'quarterfinals': 3,
            'semifinal': 4,
            'semifinals': 4,
            'final': 5,
            'finals': 5
        }
        def match_sort_key(m):
            return (
                match_type_order.get(m.match_type.lower(), 99),
                m.match_number
            )
        matches = sorted(matches, key=match_sort_key)

    # Get game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})

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
            if not scouting_team_number:
                return (None, None)
            entries = ScoutingData.query.filter_by(match_id=m.id, scouting_team_number=scouting_team_number).all()
            if not entries:
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
                elif tn in blue_team_numbers:
                    blue_sum += pts
                    any_points = any_points or pts > 0

            if not any_points:
                return (None, None)
            return (red_sum, blue_sum)
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
                if red_score is None and blue_score is None:
                    rloc, bloc = _compute_local_scores_for_match(m)
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

                    # If we still don't have any actual/local scores, prefer predicted outcome scores from analysis
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
                    rloc, bloc = _compute_local_scores_for_match(m)
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
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    game_config = current_app.config.get('GAME_CONFIG', {})
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

    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    event_id = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    event = None
    matches = []
    if event_id:
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        event = get_event_by_code(current_event_code)
    if event:
        matches = Match.query.filter_by(event_id=event.id).all()
        match_type_order = {
            'practice': 1,
            'qualification': 2,
            'qualifier': 2,
            'quarterfinal': 3,
            'quarterfinals': 3,
            'semifinal': 4,
            'semifinals': 4,
            'final': 5,
            'finals': 5
        }
        def match_sort_key(m):
            return (
                match_type_order.get(m.match_type.lower(), 99),
                m.match_number
            )
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
    if match_id:
        room = f'strategy_match_{match_id}'
        join_room(room)
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
    if not match_id or drawing_data is None:
        return
    # Save to DB
    drawing = StrategyDrawing.query.filter_by(match_id=match_id).first()
    if not drawing:
        drawing = StrategyDrawing(match_id=match_id, data_json='{}')
        db.session.add(drawing)
    drawing.data = drawing_data
    db.session.commit()
    # Broadcast to all clients in the room (except sender)
    room = f'strategy_match_{match_id}'
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
        # Get event code from config (alliance-aware)
        game_config = get_effective_game_config()
        current_event_code = game_config.get('current_event_code')
        
        if not current_event_code:
            return jsonify({
                'success': True,
                'matches': [],
                'current_event': None,
                'message': 'No event selected in configuration',
                'timestamp': datetime.now().isoformat()
            })
        
        # Get current event
        current_event = get_event_by_code(current_event_code)
        if not current_event:
            return jsonify({
                'success': True,
                'matches': [],
                'current_event': None,
                'message': f'Event {current_event_code} not found',
                'timestamp': datetime.now().isoformat()
            })
        
        # Get matches for this event
        matches = filter_matches_by_scouting_team().filter_by(event_id=current_event.id).order_by(Match.match_number).all()
        
        # Get team data for context
        teams = db.session.query(Team).join(Team.events).filter(Event.id == current_event.id).all()
        
        # Prepare matches data for JSON
        matches_data = []
        for match in matches:
            # Normalize scores so that negative sentinels like -1 are treated as None
            red_db = norm_db_score(match.red_score)
            blue_db = norm_db_score(match.blue_score)
            match_data = {
                'id': match.id,
                'match_number': match.match_number,
                'comp_level': match.comp_level,
                'set_number': match.set_number,
                'predicted_time': match.predicted_time.isoformat() if match.predicted_time else None,
                'actual_time': match.actual_time.isoformat() if match.actual_time else None,
                # played_time is provided to explicitly indicate when the match was played (if available).
                # Some API sources (TBA) may supply actual_time and our updater can store that into scheduled_time
                # so fall back to scheduled_time when actual_time is not set.
                'played_time': (match.actual_time.isoformat() if match.actual_time else (match.scheduled_time.isoformat() if match.scheduled_time else None)),
                'alliances': {
                    'red': {
                        'teams': [match.red_1, match.red_2, match.red_3],
                        'score': red_db
                    },
                    'blue': {
                        'teams': [match.blue_1, match.blue_2, match.blue_3],
                        'score': blue_db
                    }
                },
                'winner': match.winner,
                # Consider a match "played" if an actual_time exists or a winner/score is present (after normalization)
                'status': 'played' if (match.actual_time or match.winner or (red_db is not None or blue_db is not None)) else 'upcoming'
            }
            matches_data.append(match_data)
        
        # Get teams data
        teams_data = [{'id': team.id, 'team_number': team.team_number, 'name': team.name or ''} for team in teams]
        
        return jsonify({
            'success': True,
            'game_config': game_config,
            'current_event': {
                'id': current_event.id,
                'name': current_event.name,
                'code': current_event.code,
                'start_date': current_event.start_date.isoformat() if current_event.start_date else None,
                'end_date': current_event.end_date.isoformat() if current_event.end_date else None
            },
            'matches': matches_data,
            'teams': teams_data,
            'stats': {
                'total_matches': len(matches_data),
                'completed_matches': len([m for m in matches_data if m['status'] == 'completed']),
                'upcoming_matches': len([m for m in matches_data if m['status'] == 'upcoming'])
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in matches_data endpoint: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
