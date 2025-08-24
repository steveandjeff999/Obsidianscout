from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import Event, Match, ScoutingData, Team
from app import db
from datetime import datetime
from app.utils.config_manager import get_current_game_config, get_effective_game_config, save_game_config
from app.utils.team_isolation import get_event_by_code

bp = Blueprint('events', __name__, url_prefix='/events')

@bp.route('/')
def index():
    """Display all events"""
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
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
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        
        if not name or not year:
            flash('Event name and year are required!', 'danger')
            return render_template('events/add.html')
        
        # Check if event code already exists
        if code:
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
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding event: {str(e)}', 'danger')
    
    return render_template('events/add.html')

@bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
def edit(event_id):
    """Edit an event"""
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        event.name = request.form.get('name')
        event.code = request.form.get('code')
        event.year = request.form.get('year', type=int)
        event.location = request.form.get('location')
        event.start_date = request.form.get('start_date')
        event.end_date = request.form.get('end_date')
        
        if not event.name or not event.year:
            flash('Event name and year are required!', 'danger')
            return render_template('events/edit.html', event=event)
        
        # Check if event code already exists on a different event
        if event.code:
            existing_event = get_event_by_code(event.code)
            if existing_event and existing_event.id != event_id:
                flash(f'Another event with code {event.code} already exists!', 'danger')
                return render_template('events/edit.html', event=event)
        
        try:
            db.session.commit()
            flash('Event updated successfully!', 'success')
            return redirect(url_for('events.index'))
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
            
            # Delete all matches associated with this event
            Match.query.filter_by(event_id=event_id).delete()
            
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