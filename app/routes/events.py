from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import Event, Match, ScoutingData, Team, ScoutingAllianceEvent, StrategyShare, StrategyDrawing, AllianceSharedScoutingData
from sqlalchemy import func
from app import db
from datetime import datetime, date
from app.utils.config_manager import get_current_game_config, get_effective_game_config, save_game_config
from app.utils.team_isolation import get_event_by_code, filter_events_by_scouting_team, filter_matches_by_scouting_team, get_current_scouting_team_number
from app.models import TeamAllianceStatus
from sqlalchemy.exc import IntegrityError

bp = Blueprint('events', __name__, url_prefix='/events')

@bp.route('/')
def index():
    """Display all events (filtered by current scouting team)"""
    current_team = get_current_scouting_team_number()
    events = []

    # If alliance is active for this team, show only alliance events (from alliance members and alliance event codes)
    try:
        alliance = TeamAllianceStatus.get_active_alliance_for_team(current_team) if current_team else None
    except Exception:
        alliance = None

    if alliance:
        # Collect alliance member team numbers and explicit alliance event codes
        member_team_numbers = [m.team_number for m in alliance.get_active_members()]
        alliance_event_codes = alliance.get_shared_events() or []

        # Query events associated with members' teams
        try:
            member_events = Event.query.join(Event.teams).filter(Team.team_number.in_(member_team_numbers)).distinct().all()
        except Exception:
            member_events = []

        # Query events explicitly added to alliance
        try:
            code_events = Event.query.filter(Event.code.in_(alliance_event_codes)).all() if alliance_event_codes else []
        except Exception:
            code_events = []

        # Union the results
        combined = list(member_events)
        for e in code_events:
            if e not in combined:
                combined.append(e)

        events = sorted(combined, key=lambda x: (x.year if getattr(x, 'year', None) is not None else 0, x.name), reverse=True)
    else:
        events = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.name).all()

    # Deduplicate events by normalized code and prefer the most complete event
    # IMPORTANT: Keep team events and alliance events separate so both can appear with same code
    def event_score(e):
        score = 0
        if e.name: score += 10
        if e.location: score += 5
        if getattr(e, 'start_date', None): score += 5
        if getattr(e, 'end_date', None): score += 3
        if getattr(e, 'timezone', None): score += 2
        if e.year: score += 1
        return score

    # Separate dictionaries for team events and alliance events
    team_events_by_code = {}
    alliance_events_by_code = {}
    
    # Precompute alliance sets if alliance mode is active
    alliance_event_codes_upper = set([c.strip().upper() for c in (alliance.get_shared_events() if alliance else [])]) if alliance else set()
    member_team_numbers_set = set([m.team_number for m in alliance.get_active_members()]) if alliance else set()

    for e in events:
        code = (e.code or f'__id_{e.id}').strip().upper()
        
        # Determine if this event should be treated as an alliance event
        is_alliance_event = False
        try:
            # Compute stripped code (remove leading 4-digit year if present)
            from app.utils.api_utils import strip_year_prefix
            code_stripped = strip_year_prefix(code)

            if alliance:
                # Check if event code (raw or stripped) is in alliance shared events
                if code in alliance_event_codes_upper or code_stripped in alliance_event_codes_upper:
                    # Only mark as alliance if it's NOT owned by the current user's team
                    event_scouting_team = getattr(e, 'scouting_team_number', None)
                    if event_scouting_team != current_team:
                        is_alliance_event = True
                else:
                    # Check if event is owned by an alliance member (not current team)
                    event_scouting_team = getattr(e, 'scouting_team_number', None)
                    if event_scouting_team and event_scouting_team != current_team and event_scouting_team in member_team_numbers_set:
                        is_alliance_event = True
            
            # Also check ScoutingAllianceEvent table but only if not owned by current team
            if not is_alliance_event and not code.startswith('__id_'):
                event_scouting_team = getattr(e, 'scouting_team_number', None)
                if event_scouting_team != current_team:
                    sae = ScoutingAllianceEvent.query.filter(
                        func.upper(ScoutingAllianceEvent.event_code).in_([code, code_stripped]),
                        ScoutingAllianceEvent.is_active == True
                    ).first()
                    if sae is not None:
                        is_alliance_event = True
        except Exception:
            is_alliance_event = False
        try:
            setattr(e, 'is_alliance', is_alliance_event)
        except Exception:
            pass
        
        # Store in appropriate dictionary based on alliance status
        if is_alliance_event:
            if code in alliance_events_by_code:
                if event_score(e) > event_score(alliance_events_by_code[code]):
                    alliance_events_by_code[code] = e
            else:
                alliance_events_by_code[code] = e
        else:
            if code in team_events_by_code:
                if event_score(e) > event_score(team_events_by_code[code]):
                    team_events_by_code[code] = e
            else:
                team_events_by_code[code] = e

    # Combine both lists - team events first, then alliance events
    deduped_events = list(team_events_by_code.values()) + list(alliance_events_by_code.values())
    
    # Sort by year desc, then name
    try:
        deduped_events = sorted(deduped_events, key=lambda x: (getattr(x, 'year', 0) or 0, getattr(x, 'name', '') or ''), reverse=True)
    except Exception:
        pass

    events = deduped_events
    # Add current datetime to fix the 'now is undefined' error in the template
    now = datetime.now()
    return render_template('events/index.html', events=events, now=now)

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new event"""
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        year = request.form.get('year', type=int)
        location = request.form.get('location')
        start_date_raw = request.form.get('start_date')
        end_date_raw = request.form.get('end_date')

        # Parse incoming date strings into Python date objects (sqlite requires date objects)
        def _parse_date(d):
            if not d:
                return None
            try:
                # Expecting YYYY-MM-DD from <input type="date">
                return datetime.strptime(d, "%Y-%m-%d").date()
            except Exception:
                return None

        start_date = _parse_date(start_date_raw)
        end_date = _parse_date(end_date_raw)
        
        if not name or not year:
            flash('Event name and year are required!', 'danger')
            return render_template('events/add.html')
        
        # Normalize code and check if event code already exists
        if code:
            try:
                code = code.strip().upper()
            except Exception:
                pass
            existing_event = get_event_by_code(code)
            if existing_event:
                flash(f'Event with code {code} already exists!', 'danger')
                return render_template('events/add.html')
        
        event = Event(
            name=name,
            code=code,
            year=year,
            location=location,
            start_date=start_date,
            end_date=end_date
        )
        
        try:
            db.session.add(event)
            db.session.commit()
            flash('Event added successfully!', 'success')
            return redirect(url_for('events.index'))
        except IntegrityError:
            db.session.rollback()
            # Another process/user created an event with this code concurrently
            flash(f'Event with code {code} already exists (concurrent creation).', 'danger')
            return render_template('events/add.html')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding event: {str(e)}', 'danger')
    
    return render_template('events/add.html')

@bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
def edit(event_id):
    """Edit an event"""
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        # Read raw form values and do validation/normalization before assigning to the mapped `event` object
        name = request.form.get('name')
        new_code = request.form.get('code')
        year = request.form.get('year', type=int)
        location = request.form.get('location')
        start_date_raw = request.form.get('start_date')
        end_date_raw = request.form.get('end_date')

        # Helper to parse YYYY-MM-DD strings into date objects
        def _parse_date(d):
            if not d:
                return None
            try:
                return datetime.strptime(d, "%Y-%m-%d").date()
            except Exception:
                return None

        start_date = _parse_date(start_date_raw)
        end_date = _parse_date(end_date_raw)
        
        if not name or not year:
            flash('Event name and year are required!', 'danger')
            return render_template('events/edit.html', event=event)
        
        # Normalize and check if event code already exists on a different event
        # Normalize and check event code uniqueness using the proposed new value (don't assign to `event` yet)
        if new_code:
            try:
                new_code = new_code.strip().upper()
            except Exception:
                pass
            existing_event = get_event_by_code(new_code)
            if existing_event and existing_event.id != event_id:
                flash(f'Another event with code {new_code} already exists!', 'danger')
                return render_template('events/edit.html', event=event)
        
        # All validation passed; assign values to the event object and commit
        event.name = name
        event.code = new_code
        event.year = year
        event.location = location
        event.start_date = start_date
        event.end_date = end_date

        try:
            db.session.commit()
            flash('Event updated successfully!', 'success')
            return redirect(url_for('events.index'))
        except IntegrityError:
            db.session.rollback()
            flash(f'Another event with code {event.code} already exists (concurrent update).', 'danger')
            return render_template('events/edit.html', event=event)
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating event: {str(e)}', 'danger')
    
    return render_template('events/edit.html', event=event)

@bp.route('/<int:event_id>/delete', methods=['POST'])
def delete(event_id):
    """Delete an event and all associated matches"""
    event = Event.query.get_or_404(event_id)
    event_name = event.name  # Store name before deletion
    
    try:
        # Import the DisableReplication context manager
        from app.utils.real_time_replication import DisableReplication
        
        # Temporarily disable replication during bulk delete to prevent queue issues
        with DisableReplication():
            # Delete all scouting data and other dependent rows associated with matches from this event
            match_ids = [match.id for match in event.matches]
            if match_ids:
                ScoutingData.query.filter(ScoutingData.match_id.in_(match_ids)).delete(synchronize_session=False)
                # Strategy shares for these matches
                StrategyShare.query.filter(StrategyShare.match_id.in_(match_ids)).delete(synchronize_session=False)
                # Strategy drawings for these matches
                StrategyDrawing.query.filter(StrategyDrawing.match_id.in_(match_ids)).delete(synchronize_session=False)
                # Alliance-shared copies for these matches
                AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.match_id.in_(match_ids)).delete(synchronize_session=False)
            
            # Remove event associations from teams
            for team in event.teams:
                team.events.remove(event)
            
            # Delete all matches associated with this event (filtered by scouting team)
            filter_matches_by_scouting_team().filter_by(event_id=event_id).delete()
            
            # Finally delete the event itself
            db.session.delete(event)
            db.session.commit()
        
        # After the bulk delete is complete, queue a single replication operation
        from app.utils.real_time_replication import real_time_replicator
        real_time_replicator.replicate_operation(
            'delete', 
            'events', 
            {'id': event_id, 'name': event_name}, 
            str(event_id)
        )
        
        flash(f'Event "{event_name}" and all associated data deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting event: {str(e)}', 'danger')
    
    return redirect(url_for('events.index'))

@bp.route('/sync', methods=['POST'])
def sync():
    """Sync events from FIRST API for a specific year"""
    # This would be implemented to fetch events from FIRST API
    # Not implementing the full API sync here as it would require additional API utils
    flash('Event syncing not implemented in this version', 'warning')
    return redirect(url_for('events.index'))

@bp.route('/set_current_event/<event_identifier>', methods=['GET'])
def set_current_event(event_identifier):
    """Set the current event in the game configuration.

    Accepts either numeric event id (int) or an alliance identifier like 'alliance_CODE' or an event code string.
    """
    # Determine whether identifier is numeric id or an alliance/code string
    event = None
    event_code_to_set = None
    try:
        # Try numeric id first
        event_id_int = int(event_identifier)
        event = Event.query.get_or_404(event_id_int)
        event_code_to_set = event.code
    except (ValueError, TypeError):
        # Treat as string code or alliance identifier
        code = str(event_identifier)
        if code.startswith('alliance_'):
            code = code.split('alliance_', 1)[1]
        event_code_upper = code.strip().upper()
        # Try to find a team-scoped event first
        try:
            event = filter_events_by_scouting_team().filter(func.upper(Event.code) == event_code_upper).first()
        except Exception:
            event = None
        if event:
            event_code_to_set = event.code
        else:
            # Use the uppercase code even if no Event row exists locally
            event_code_to_set = event_code_upper

    # Update the game configuration
    game_config = get_current_game_config()
    game_config['current_event_code'] = event_code_to_set

    # Save the updated configuration to file
    if save_game_config(game_config):
        # Update the app config as well
        current_app.config['GAME_CONFIG'] = game_config
        flash(f'Current event set to: {event.name if event else event_code_to_set}', 'success')
    else:
        flash(f'Error setting current event', 'danger')

    # Redirect to the referring page or specified route
    redirect_to = request.args.get('redirect_to')
    if redirect_to:
        return redirect(url_for(redirect_to))
    else:
        return redirect(url_for('events.index'))