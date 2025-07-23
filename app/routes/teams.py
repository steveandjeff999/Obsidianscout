from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from app.routes.auth import analytics_required
from app.models import Team, Event, ScoutingData
from app import db
from app.utils.api_utils import get_teams, ApiError, api_to_db_team_conversion, get_event_details, get_teams_dual_api, get_event_details_dual_api
from datetime import datetime
import statistics
from app.utils.theme_manager import ThemeManager

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('teams', __name__, url_prefix='/teams')

@bp.route('/')
@analytics_required
def index():
    """Display teams for the selected event"""
    # Get event code from config
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    
    # Get the current event
    event = None
    event_id = request.args.get('event_id', type=int)
    
    # Get all events for the dropdown
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    
    if event_id:
        # If a specific event ID is requested, use that
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        # Otherwise use the current event from config
        event = Event.query.filter_by(code=current_event_code).first()
        
        # If the config has an event code but it's not in the database yet,
        # suggest syncing teams to create the event
        if not event and events:
            flash(f"Event with code '{current_event_code}' not found. Please sync teams to create this event.", "warning")
    
    # Filter teams by the selected event
    if event:
        teams = event.teams
    else:
        # If no event selected, don't show any teams
        teams = []
        
        if not events:
            flash("No events found in the database. Add an event or sync teams to create events.", "info")
        else:
            flash("Please select an event to view teams.", "info")
    
    return render_template('teams/index.html', teams=teams, events=events, selected_event=event, **get_theme_context())

@bp.route('/sync_from_config')
def sync_from_config():
    """Sync teams from FIRST API using the event code from config file"""
    try:
        # Get event code from config
        game_config = current_app.config.get('GAME_CONFIG', {})
        event_code = game_config.get('current_event_code')
        
        if not event_code:
            flash("No event code found in configuration. Please add 'current_event_code' to your game_config.json file.", 'danger')
            return redirect(url_for('teams.index'))
        
        # Find or create the event in our database
        current_year = game_config.get('season', 2026)
        event = Event.query.filter_by(code=event_code).first()
        
        if not event:
            try:
                # Try to get event details from dual API
                event_details = get_event_details_dual_api(event_code)
                
                # Convert date strings to datetime.date objects
                start_date_str = event_details.get('dateStart')
                end_date_str = event_details.get('dateEnd')
                
                start_date = None
                end_date = None
                
                # Parse start date if present
                if start_date_str:
                    try:
                        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
                    except ValueError:
                        print(f"Could not parse start date: {start_date_str}")
                
                # Parse end date if present
                if end_date_str:
                    try:
                        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
                    except ValueError:
                        print(f"Could not parse end date: {end_date_str}")
                
                event = Event(
                    name=event_details.get('name', f"Event {event_code}"),
                    code=event_code,
                    year=event_details.get('year', current_year),
                    location=event_details.get('location', ''),
                    start_date=start_date,
                    end_date=end_date
                )
            except:
                # If API call fails, create minimal event
                event = Event(
                    name=f"Event {event_code}",
                    code=event_code,
                    year=current_year
                )
            
            db.session.add(event)
            db.session.commit()  # Commit to get the ID

        # Fetch teams from the dual API using the event code
        team_data_list = get_teams_dual_api(event_code)
        
        # Track metrics for user feedback
        teams_added = 0
        teams_updated = 0
        
        # Process each team from the API
        for team_data in team_data_list:
            
            if not team_data or not team_data.get('team_number'):
                continue
                
            team_number = team_data.get('team_number')
            
            # Check if the team already exists
            team = Team.query.filter_by(team_number=team_number).first()
            
            if team:
                # Update existing team
                team.team_name = team_data.get('team_name', team.team_name)
                team.location = team_data.get('location', team.location)
                teams_updated += 1
            else:
                # Add new team
                team = Team(**team_data)
                db.session.add(team)
                db.session.flush()  # Flush to get the team ID
                teams_added += 1
            
            # Associate this team with the current event if not already associated
            try:
                # Check if association already exists to avoid unique constraint violation
                if event not in team.events:
                    team.events.append(event)
                    db.session.flush()  # Flush after each team-event association
            except Exception as e:
                # Log the error but continue processing other teams
                print(f"Error associating team {team.team_number} with event: {str(e)}")
                continue
        
        # Commit all changes
        db.session.commit()
        
        # Show success message
        flash(f"Teams sync complete! Added {teams_added} new teams and updated {teams_updated} existing teams.", 'success')
        
    except ApiError as e:
        flash(f"API Error: {str(e)}", 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f"Error syncing teams: {str(e)}", 'danger')
    
    return redirect(url_for('teams.index'))

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new team"""
    # Get all events for the form
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    
    # Get default event from config or URL parameter
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    default_event_id = None
    
    if current_event_code:
        event = Event.query.filter_by(code=current_event_code).first()
        if event:
            default_event_id = event.id
    
    # Get event from URL parameter if provided (overrides default)
    event_id_param = request.args.get('event_id', type=int)
    if event_id_param:
        default_event_id = event_id_param
    
    if request.method == 'POST':
        team_number = request.form.get('team_number', type=int)
        team_name = request.form.get('team_name')
        location = request.form.get('location')
        
        # Get the selected events (can be multiple)
        event_ids = request.form.getlist('events', type=int)
        
        # Validate that team number is provided
        if not team_number:
            flash('Team number is required', 'danger')
            return render_template('teams/add.html', events=events, default_event_id=default_event_id, **get_theme_context())
        
        # Check if team already exists
        existing_team = Team.query.filter_by(team_number=team_number).first()
        if existing_team:
            flash(f'Team {team_number} already exists', 'danger')
            return render_template('teams/add.html', events=events, default_event_id=default_event_id, **get_theme_context())
        
        # Create new team
        team = Team(team_number=team_number, team_name=team_name, location=location)
        
        try:
            db.session.add(team)
            db.session.flush()  # Flush to get the team ID
            
            # Associate team with selected events
            if event_ids:
                for event_id in event_ids:
                    event = Event.query.get(event_id)
                    if event:
                        team.events.append(event)
                
                # Use the last selected event as the return URL
                return_event_id = event_ids[-1]
                
                db.session.commit()
                flash(f'Team {team_number} added successfully and associated with selected events', 'success')
                return redirect(url_for('teams.index', event_id=return_event_id))
            else:
                db.session.commit()
                flash(f'Team {team_number} added successfully (not associated with any events)', 'success')
                return redirect(url_for('teams.index'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding team: {str(e)}', 'danger')
    
    return render_template('teams/add.html', events=events, default_event_id=default_event_id, **get_theme_context())

@bp.route('/<int:team_number>/edit', methods=['GET', 'POST'])
def edit(team_number):
    """Edit a team"""
    team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    # Get all events for the form
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    
    if request.method == 'POST':
        # new_team_number = request.form.get('team_number', type=int)
        team_name = request.form.get('team_name')
        location = request.form.get('location')
        
        # Get the selected events (can be multiple)
        event_ids = request.form.getlist('events', type=int)
        
        # Update team
        # Note: We're not allowing team number changes to avoid complications
        # team.team_number = new_team_number
        team.team_name = team_name
        team.location = location
        
        try:
            # Update team-event associations
            # First, remove all existing associations
            team.events = []
            
            # Then add the selected events
            if event_ids:
                for event_id in event_ids:
                    event = Event.query.get(event_id)
                    if event:
                        team.events.append(event)
            
            db.session.commit()
            flash(f'Team {team.team_number} updated successfully', 'success')
            
            # Redirect to the teams list filtered by one of the selected events
            if event_ids:
                return redirect(url_for('teams.index', event_id=event_ids[0]))
            else:
                return redirect(url_for('teams.index'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating team: {str(e)}', 'danger')
    
    return render_template('teams/edit.html', team=team, events=events, **get_theme_context())

@bp.route('/<int:team_number>/delete', methods=['POST'])
def delete(team_number):
    """Delete a team"""
    team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    try:
        db.session.delete(team)
        db.session.commit()
        flash(f'Team {team.team_number} deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting team: {str(e)}', 'danger')
    
    return redirect(url_for('teams.index'))

@bp.route('/<int:team_number>/view')
def view(team_number):
    """View team details"""
    team = Team.query.filter_by(team_number=team_number).first_or_404()
    
    # Get scouting data for this team
    scouting_data = ScoutingData.query.filter_by(team_id=team.id).order_by(ScoutingData.match_id).all()
    
    # Get game configuration for metrics calculation
    game_config = current_app.config.get('GAME_CONFIG', {})
    
    # Calculate key metrics for this team if we have scouting data
    metrics = {}
    component_metrics = {}  # Stores just the component metrics for separate display
    metric_info = {}  # Stores metadata about each metric
    
    # Find the component metrics and total metric from game config
    component_metric_ids = []
    total_metric_id = None
    total_metric_name = "Total Points"
    
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            metric_id = metric.get('id')
            metric_info[metric_id] = metric
            
            # Check if this is a component metric or the total metric
            if metric.get('is_total_component'):
                component_metric_ids.append(metric_id)
            elif 'total' in metric_id.lower() or 'tot' == metric_id.lower():
                total_metric_id = metric_id
                total_metric_name = metric.get('name', "Total Points")
    
    # If no component metrics defined in config, use default IDs
    if not component_metric_ids:
        component_metric_ids = ["apt", "tpt", "ept"]
    
    # If no total metric defined, use default ID
    if not total_metric_id:
        total_metric_id = "tot"
    
    if scouting_data:
        # Initialize metric arrays
        metric_values = {metric_id: [] for metric_id in component_metric_ids}
        metric_values[total_metric_id] = []
        
        # Process all scouting data entries to calculate metrics
        for data in scouting_data:
            for metric_id in component_metric_ids:
                metric_values[metric_id].append(data.calculate_metric(metric_id))
            
            metric_values[total_metric_id].append(data.calculate_metric(total_metric_id))
        
        # Calculate averages
        for metric_id, values in metric_values.items():
            if values:
                metrics[metric_id] = sum(values) / len(values)
                if metric_id in component_metric_ids:
                    component_metrics[metric_id] = metrics[metric_id]
        
        # Add other key metrics from game config if they exist
        if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
            for metric in game_config['data_analysis']['key_metrics']:
                metric_id = metric.get('id')
                # Skip metrics we've already calculated
                if metric_id in metrics:
                    continue
                
                # Skip metrics that don't have a formula
                if not metric.get('formula'):
                    continue
                
                # Calculate this metric for each scouting entry and average
                metric_values = []
                for data in scouting_data:
                    value = data.calculate_metric(metric.get('formula', ''))
                    if value is not None:
                        metric_values.append(value)
                
                # Calculate average if we have values
                if metric_values:
                    metrics[metric_id] = sum(metric_values) / len(metric_values)
    
    return render_template(
        'teams/view.html', 
        team=team, 
        scouting_data=scouting_data, 
        metrics=metrics, 
        game_config=game_config,
        component_metrics=component_metrics,
        metric_info=metric_info,
        total_metric_id=total_metric_id,
        total_metric_name=total_metric_name,
        **get_theme_context()
    )

@bp.route('/ranks')
@analytics_required
def ranks():
    """Display team rankings for the selected event based on average total points"""
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    event_id = request.args.get('event_id', type=int)
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    event = None
    if event_id:
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        event = Event.query.filter_by(code=current_event_code).first()
    teams = event.teams if event else []
    # Determine the total metric id from config
    total_metric_id = None
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            if 'total' in metric.get('id', '').lower() or metric.get('id', '').lower() == 'tot':
                total_metric_id = metric['id']
                break
    if not total_metric_id:
        total_metric_id = 'tot'
    # Calculate average total points for each team
    team_rankings = []
    for team in teams:
        scouting_data = ScoutingData.query.filter_by(team_id=team.id).all()
        if scouting_data:
            total_points = [data.calculate_metric(total_metric_id) for data in scouting_data]
            avg_points = sum(total_points) / len(total_points) if total_points else 0
        else:
            avg_points = 0
        team_rankings.append({
            'team': team,
            'avg_points': avg_points,
            'num_entries': len(scouting_data)
        })
    # Sort by average points descending
    team_rankings.sort(key=lambda x: x['avg_points'], reverse=True)
    return render_template('teams/ranks.html',
        team_rankings=team_rankings,
        events=events,
        selected_event=event,
        total_metric_id=total_metric_id,
        **get_theme_context()
    )