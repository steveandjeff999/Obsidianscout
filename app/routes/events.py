from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import Event, Match, ScoutingData, Team
from app import db
from datetime import datetime, date
from app.utils.config_manager import get_current_game_config, get_effective_game_config, save_game_config
from app.utils.team_isolation import get_event_by_code, filter_events_by_scouting_team
from sqlalchemy.exc import IntegrityError

bp = Blueprint('events', __name__, url_prefix='/events')

@bp.route('/')
def index():
    """Display all events (filtered by current scouting team)"""
    events = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.name).all()
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
            # Delete all scouting data associated with matches from this event
            match_ids = [match.id for match in event.matches]
            if match_ids:
                ScoutingData.query.filter(ScoutingData.match_id.in_(match_ids)).delete(synchronize_session=False)
            
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

@bp.route('/set_current_event/<int:event_id>', methods=['GET'])
def set_current_event(event_id):
    """Set the current event in the game configuration"""
    event = Event.query.get_or_404(event_id)
    
    # Update the game configuration
    game_config = get_current_game_config()
    game_config['current_event_code'] = event.code
    
    # Save the updated configuration to file
    if save_game_config(game_config):
        # Update the app config as well
        current_app.config['GAME_CONFIG'] = game_config
        flash(f'Current event set to: {event.name}', 'success')
    else:
        flash(f'Error setting current event', 'danger')
    
    # Redirect to the referring page or specified route
    redirect_to = request.args.get('redirect_to')
    if redirect_to:
        return redirect(url_for(redirect_to))
    else:
        return redirect(url_for('events.index'))