from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.routes.auth import analytics_required
from app.models import Match, Event, Team, ScoutingData
from app import db
from app.utils.api_utils import get_matches, ApiError, api_to_db_match_conversion, get_matches_dual_api
from app.utils.analysis import predict_match_outcome, get_match_details_with_teams
from datetime import datetime

bp = Blueprint('matches', __name__, url_prefix='/matches')

@bp.route('/')
@analytics_required
def index():
    """Display matches for the current event from configuration"""
    # Get event code from config
    game_config = current_app.config.get('GAME_CONFIG', {})
    current_event_code = game_config.get('current_event_code')
    
    # Get the current event
    event = None
    event_id = request.args.get('event_id', type=int)
    
    if event_id:
        # If a specific event ID is requested, use that
        event = Event.query.get_or_404(event_id)
    elif current_event_code:
        # Otherwise use the current event from config
        event = Event.query.filter_by(code=current_event_code).first()
    
    # Get all events for the dropdown
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    
    # Filter matches by the selected event
    if event:
        # Define custom ordering for match types
        match_type_order = {
            'practice': 1,
            'qualification': 2,
            'qualifier': 2,  # Alternative name for qualification matches
            'playoff': 3,
            'elimination': 3,  # Alternative name for playoff matches
        }
        
        # Get all matches for this event
        matches = Match.query.filter_by(event_id=event.id).all()
        
        # Sort matches by type (using our custom order) and then by match number
        matches = sorted(matches, key=lambda m: (
            match_type_order.get(m.match_type.lower(), 99),  # Unknown types go to the end
            m.match_number
        ))
    else:
        # If no event selected, don't show any matches
        matches = []
        flash("No current event selected. Use the dropdown to select an event or configure a default event code.", "warning")
    
    return render_template('matches/index.html', matches=matches, events=events, selected_event=event)

@bp.route('/sync_from_config')
def sync_from_config():
    """Sync matches from FIRST API using the event code from config file"""
    try:
        # Get event code from config
        game_config = current_app.config.get('GAME_CONFIG', {})
        event_code = game_config.get('current_event_code')
        
        if not event_code:
            flash("No event code found in configuration. Please add 'current_event_code' to your game_config.json file.", 'danger')
            return redirect(url_for('matches.index'))
        
        # Find or create the event in our database
        current_year = game_config.get('season', 2026)
        event = Event.query.filter_by(code=event_code).first()
        if not event:
            event = Event(
                name=f"Event {event_code}",  # Placeholder name until we get more data
                code=event_code,
                year=current_year
            )
            db.session.add(event)
            db.session.flush()  # Get the ID without committing yet
        
        # Fetch matches from the dual API using the event code
        match_data_list = get_matches_dual_api(event_code)
        
        # Track metrics for user feedback
        matches_added = 0
        matches_updated = 0
        
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
            
            # Check if the match already exists
            match = Match.query.filter_by(
                event_id=event.id,
                match_number=match_number,
                match_type=match_type
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
                db.session.add(match)
                matches_added += 1
        
        # Commit all changes
        db.session.commit()
        
        # Show success message
        flash(f"Matches sync complete! Added {matches_added} new matches and updated {matches_updated} existing matches.", 'success')
        
    except ApiError as e:
        flash(f"API Error: {str(e)}", 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f"Error syncing matches: {str(e)}", 'danger')
    
    return redirect(url_for('matches.index'))

@bp.route('/<int:match_id>')
def view(match_id):
    """View match details and related scouting data"""
    match = Match.query.get_or_404(match_id)
    
    # Get scouting data for this match
    scouting_data = ScoutingData.query.filter_by(match_id=match.id).all()
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    return render_template('matches/view.html', match=match, 
                          scouting_data=scouting_data, game_config=game_config)

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new match"""
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    events = Event.query.all()
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = current_event.teams
    else:
        teams = []  # No teams if no current event is set
    
    if request.method == 'POST':
        match_number = request.form.get('match_number', type=int)
        match_type = request.form.get('match_type')
        event_id = request.form.get('event_id', type=int)
        
        # Get alliance team numbers
        red_teams = []
        blue_teams = []
        for i in range(current_app.config['GAME_CONFIG']['alliance_size']):
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
        
        db.session.add(match)
        db.session.commit()
        
        flash(f'Match {match_type} {match_number} added successfully!', 'success')
        return redirect(url_for('matches.index'))
    
    return render_template('matches/add.html', events=events, teams=teams, 
                          alliance_size=current_app.config['GAME_CONFIG']['alliance_size'],
                          match_types=current_app.config['GAME_CONFIG']['match_types'])

@bp.route('/<int:match_id>/edit', methods=['GET', 'POST'])
def edit(match_id):
    """Edit match details"""
    match = Match.query.get_or_404(match_id)
    events = Event.query.all()
    
    # Get game configuration
    game_config = current_app.config['GAME_CONFIG']
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = Event.query.filter_by(code=current_event_code).first()
    
    # Get teams filtered by the current event if available
    if current_event:
        teams = current_event.teams
    else:
        teams = []  # No teams if no current event is set
    
    if request.method == 'POST':
        match.match_number = request.form.get('match_number', type=int)
        match.match_type = request.form.get('match_type')
        match.event_id = request.form.get('event_id', type=int)
        
        # Get alliance team numbers
        red_teams = []
        blue_teams = []
        for i in range(current_app.config['GAME_CONFIG']['alliance_size']):
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
                         alliance_size=current_app.config['GAME_CONFIG']['alliance_size'],
                         match_types=current_app.config['GAME_CONFIG']['match_types'])

@bp.route('/<int:match_id>/delete', methods=['POST'])
def delete(match_id):
    """Delete a match"""
    match = Match.query.get_or_404(match_id)
    
    # Delete associated scouting data
    ScoutingData.query.filter_by(match_id=match.id).delete()
    
    db.session.delete(match)
    db.session.commit()
    
    flash(f'Match deleted successfully!', 'success')
    return redirect(url_for('matches.index'))

@bp.route('/predict', methods=['GET', 'POST'])
def predict():
    """Predict the outcome of a match based on team performance"""
    # Get event code from config
    game_config = current_app.config.get('GAME_CONFIG', {})
    
    # Get the current event
    event = None
    selected_match = None
    prediction = None
    
    # Get all events for the dropdown
    events = Event.query.order_by(Event.year.desc(), Event.name).all()
    
    # Get event from URL parameter or form
    event_id = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    
    if event_id:
        # If a specific event ID is requested, use that
        event = Event.query.get_or_404(event_id)
        
        # Get all matches for this event
        matches = Match.query.filter_by(event_id=event.id).order_by(Match.match_type, Match.match_number).all()
        
        # Check if a specific match is requested
        match_id = request.args.get('match_id', type=int) or request.form.get('match_id', type=int)
        
        if match_id:
            # Get the match
            selected_match = Match.query.get_or_404(match_id)
            
            # Get match details with prediction
            match_details = get_match_details_with_teams(match_id)
            if match_details:
                prediction = match_details['prediction']
    else:
        matches = []
    
    return render_template(
        'matches/predict.html',
        events=events,
        selected_event=event,
        matches=matches,
        selected_match=selected_match,
        prediction=prediction,
        game_config=game_config
    )

@bp.route('/api/predict/<int:match_id>')
def api_predict(match_id):
    """API endpoint to get match prediction data"""
    match_details = get_match_details_with_teams(match_id)
    if not match_details:
        return jsonify({'error': 'Match not found'}), 404
        
    return jsonify({'match_details': match_details})

@bp.route('/predict/<int:match_id>/print')
@login_required
def predict_print(match_id):
    """Display a printable version of the match prediction"""
    from datetime import datetime
    
    # Get the match
    selected_match = Match.query.get_or_404(match_id)
    selected_event = Event.query.get(selected_match.event_id)
    
    # Get match details with prediction
    match_details = get_match_details_with_teams(match_id)
    if not match_details:
        flash('Unable to generate prediction for this match.', 'warning')
        return redirect(url_for('matches.predict'))
    
    # Get game configuration
    game_config = current_app.config.get('GAME_CONFIG', {})
    
    # Render the printable template with the prediction data
    return render_template(
        'matches/predict_printable.html',
        selected_match=selected_match,
        selected_event=selected_event,
        prediction=match_details['prediction'],
        game_config=game_config,
        now=datetime.now()
    )

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
    
    return render_template(
        'matches/strategy.html',
        events=events,
        selected_event=event,
        matches=matches,
        game_config=game_config
    )

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