from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Match, Team, ScoutingData, Event
from app import db, socketio
import json
from datetime import datetime, timezone
import qrcode
from io import BytesIO
import base64
from app.utils.config_manager import get_id_to_perm_id_mapping, get_current_game_config, get_effective_game_config, is_alliance_mode_active
from app.utils.theme_manager import ThemeManager
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code
)

bp = Blueprint('scouting', __name__, url_prefix='/scouting')

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

def auto_sync_alliance_data(scouting_data_entry):
    """Automatically sync new scouting data to alliance members if alliance mode is active"""
    try:
        # Check if alliance mode is active for current user's team
        if not is_alliance_mode_active():
            return
        
        # Import here to avoid circular imports
        from app.models import TeamAllianceStatus, ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceSync
        
        current_team = current_user.scouting_team_number
        
        # Get the active alliance for this team
        alliance_status = TeamAllianceStatus.query.filter_by(
            team_number=current_team,
            is_alliance_mode_active=True
        ).first()
        
        if not alliance_status or not alliance_status.active_alliance:
            return
            
        alliance = alliance_status.active_alliance
        
        # Get alliance shared events to verify we should sync this data
        alliance_events = alliance.get_shared_events()
        
        # Check if this scouting data is for a shared event
        match_event_code = scouting_data_entry.match.event.code
        if alliance_events and match_event_code not in alliance_events:
            return  # Don't sync data for non-shared events
        
        # Prepare the scouting data for sync
        sync_data = {
            'team_number': scouting_data_entry.team.team_number,
            'match_number': scouting_data_entry.match.match_number,
            'match_type': scouting_data_entry.match.match_type,
            'event_code': match_event_code,
            'alliance': scouting_data_entry.alliance,
            'scout_name': scouting_data_entry.scout_name,
            'data': scouting_data_entry.data,
            'timestamp': scouting_data_entry.timestamp.isoformat()
        }
        
        # Send data to alliance members via Socket.IO
        sync_count = 0
        active_members = alliance.get_active_members()
        
        for member in active_members:
            if member.team_number != current_team:
                # Create sync record
                sync_record = ScoutingAllianceSync(
                    alliance_id=alliance.id,
                    from_team_number=current_team,
                    to_team_number=member.team_number,
                    data_type='scouting',
                    data_count=1
                )
                db.session.add(sync_record)
                sync_count += 1
                
                # Emit real-time sync to that team
                socketio.emit('alliance_data_sync_auto', {
                    'from_team': current_team,
                    'alliance_name': alliance.alliance_name,
                    'scouting_data': [sync_data],
                    'pit_data': [],
                    'sync_id': sync_record.id,
                    'type': 'auto_sync'
                }, room=f'team_{member.team_number}')
                
        if sync_count > 0:
            db.session.commit()
            print(f"Auto-synced scouting data for Team {scouting_data_entry.team.team_number} Match {scouting_data_entry.match.match_number} to {sync_count} alliance members")
            
    except Exception as e:
        print(f"Error in auto-sync alliance data: {str(e)}")
        # Don't raise the exception to prevent disrupting the main save operation

@bp.route('/')
@login_required
def index():
    """Scouting dashboard page"""
    # Get game configuration (using alliance config if active)
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)  # Use filtered function
    
    # Get teams filtered by the current event and scouting team
    if current_event:
        teams = filter_teams_by_scouting_team().join(
            Team.events
        ).filter(Event.id == current_event.id).order_by(Team.team_number).all()
    else:
        teams = []  # No teams if no current event is set
    
    # Define custom ordering for match types
    match_type_order = {
        'practice': 1,
        'qualification': 2,
        'qualifier': 2,  # Alternative name for qualification matches
        'playoff': 3,
        'elimination': 3,  # Alternative name for playoff matches
    }
    
    # Get matches filtered by the current event if available
    if current_event:
        all_matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).all()
    else:
        all_matches = filter_matches_by_scouting_team().all()
    
    matches = sorted(all_matches, key=lambda m: (
        match_type_order.get(m.match_type.lower(), 99),  # Unknown types go to the end
        m.match_number
    ))
    
    # Get recent scouting data
    recent_scouting_data = ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number).order_by(ScoutingData.timestamp.desc()).limit(5).all()
    
    return render_template('scouting/index.html', 
                          teams=teams, 
                          matches=matches,
                          scouting_data=recent_scouting_data,  
                          game_config=game_config,
                          **get_theme_context())

@bp.route('/form', methods=['GET', 'POST'])
def scouting_form():
    """Dynamic scouting form based on game configuration"""
    # Get game configuration (using alliance config if active)
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)  # Use filtered function
    
    # Get teams filtered by the current event and scouting team
    if current_event:
        teams = filter_teams_by_scouting_team().join(
            Team.events
        ).filter(Event.id == current_event.id).order_by(Team.team_number).all()
    else:
        teams = []  # No teams if no current event is set

    # Sort teams by team_number (already sorted in query but keeping for consistency)
    teams = sorted(teams, key=lambda t: t.team_number)
    
    # Define custom ordering for match types
    match_type_order = {
        'practice': 1,
        'qualification': 2,
        'qualifier': 2,  # Alternative name for qualification matches
        'playoff': 3,
        'elimination': 3,  # Alternative name for playoff matches
    }
    
    # Get matches filtered by the current event if available
    if current_event:
        all_matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).all()
    else:
        all_matches = filter_matches_by_scouting_team().all()
    
    matches = sorted(all_matches, key=lambda m: (
        match_type_order.get(m.match_type.lower(), 99),  # Unknown types go to the end
        m.match_number
    ))
    
    # For AJAX team/match selection
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        current_app.logger.info(f"AJAX form request received - User: {current_user.username}")
        
        team_id = request.form.get('team_id', type=int)
        match_id = request.form.get('match_id', type=int)
        
        current_app.logger.info(f"Team ID: {team_id}, Match ID: {match_id}")
        
        if not team_id or not match_id:
            current_app.logger.warning("Missing team_id or match_id in AJAX request")
            return jsonify({'success': False, 'message': 'Both team and match must be selected'})
        
        try:
            team = Team.query.get_or_404(team_id)
            match = Match.query.get_or_404(match_id)
            current_app.logger.info(f"Found team: {team.team_number}, match: {match.match_number}")
        except Exception as e:
            current_app.logger.error(f"Error fetching team/match: {str(e)}")
            return jsonify({'success': False, 'message': 'Team or match not found'})
        
        # Determine alliance color
        alliance = 'unknown'
        if str(team.team_number) in match.red_alliance.split(','):
            alliance = 'red'
        elif str(team.team_number) in match.blue_alliance.split(','):
            alliance = 'blue'
        
        # Check if data already exists
        existing_data = ScoutingData.query.filter_by(
            team_id=team.id,
            match_id=match.id,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        # Initialize form data
        form_data = {}
        data_corruption_warning = None
        if existing_data:
            try:
                form_data = existing_data.data
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                current_app.logger.error(f"Error parsing existing data for team {team_id}, match {match_id}: {str(e)}")
                form_data = {}
                data_corruption_warning = 'Warning: Could not load existing form data due to data corruption. Starting with fresh form.'
        else:
            # Initialize with defaults from config for all periods
            for period in ['auto_period', 'teleop_period', 'endgame_period']:
                if period in game_config:
                    for element in game_config[period].get('scoring_elements', []):
                        if 'id' in element and 'default' in element:
                            form_data[element['id']] = element['default']
            
            # Add post-match elements
            if 'post_match' in game_config:
                for element_type in ['rating_elements', 'text_elements']:
                    if element_type in game_config['post_match']:
                        for element in game_config['post_match'][element_type]:
                            if 'id' in element and 'default' in element:
                                form_data[element['id']] = element['default']
                                
            # Add any custom identifiers if they exist
            if 'custom_identifiers' in game_config:
                for element in game_config['custom_identifiers'].get('elements', []):
                    if 'id' in element and 'default' in element:
                        form_data[element['id']] = element['default']
        
        # Render just the form content for the AJAX response
        try:
            theme_context = get_theme_context()
        except Exception as e:
            current_app.logger.error(f"Error getting theme context: {str(e)}")
            theme_context = {}
            
        try:
            html = render_template('scouting/partials/form_content.html', 
                                team=team, 
                                match=match,
                                form_data=form_data,
                                game_config=game_config,
                                alliance=alliance,
                                existing_data=existing_data,
                                **theme_context)
        except Exception as e:
            current_app.logger.error(f"Error rendering form template: {str(e)}")
            return jsonify({
                'success': False, 
                'message': f'Error rendering form template: {str(e)}'
            })
        
        response_data = {
            'success': True, 
            'html': html,
            'team_number': team.team_number,
            'team_name': team.team_name,
            'match_type': match.match_type,
            'match_number': match.match_number,
            'alliance': alliance,
            'team_id': team.id,
            'match_id': match.id
        }
        
        # Include warning if there was data corruption
        if data_corruption_warning:
            response_data['warning'] = data_corruption_warning
            
        return jsonify(response_data)
    
    # For normal form submission (non-AJAX)
    elif request.method == 'POST':
        team_id = request.form.get('team_id', type=int)
        match_id = request.form.get('match_id', type=int)
        
        if not team_id or not match_id:
            flash('Please select a team and match', 'warning')
            return render_template('scouting/form.html', teams=teams, matches=matches, 
                                game_config=game_config, team=None, match=None,
                                **get_theme_context())
        
        team = Team.query.get_or_404(team_id)
        match = Match.query.get_or_404(match_id)
        
        # Determine alliance color
        alliance = request.form.get('alliance', 'unknown')
        
        scout_name = request.form.get('scout_name')
        scouting_station = request.form.get('scouting_station', type=int)
        # Keep track of the user id who submitted this; store account id and optional display name
        scout_id = getattr(current_user, 'id', None)
        if not scout_name or scout_name.strip() == '':
            # Use account username as display name when none provided
            scout_name = getattr(current_user, 'username', 'Unknown')
        
        # Build data dictionary from form
        data = {}
        
        # Process all form fields dynamically based on their element type
        id_map = get_id_to_perm_id_mapping()
        for key, value in request.form.items():
            # Skip non-data fields
            if key in ['csrf_token', 'scout_name', 'scouting_station', 'team_id', 'match_id', 'alliance']:
                continue
                
            # Find the element in the game config to determine its type
            element_type = _get_element_type_from_config(key, get_effective_game_config())
            perm_id = id_map.get(key, key)
            
            # Process based on type
            if element_type == 'boolean':
                # HTML checkbox fields are only included when checked
                data[perm_id] = key in request.form
            elif element_type == 'counter':
                # Convert to integer
                data[perm_id] = int(request.form.get(key, 0))
            elif element_type == 'select':
                # Store selection as-is
                data[perm_id] = value
            elif element_type == 'rating':
                # Convert to integer
                data[perm_id] = int(value)
            else:
                # For text fields and any other types
                data[perm_id] = value
        
        # Check if data already exists
        existing_data = ScoutingData.query.filter_by(
            team_id=team.id,
            match_id=match.id,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        # Create or update scouting data
        if existing_data:
            existing_data.data = data
            existing_data.scout_name = scout_name
            existing_data.scout_id = scout_id
            existing_data.scouting_station = scouting_station
            existing_data.alliance = alliance
            existing_data.timestamp = datetime.now(timezone.utc)
            flash('Scouting data updated successfully!', 'success')
        else:
            new_data = ScoutingData(
                team_id=team.id,
                match_id=match.id,
                scout_name=scout_name,
                scout_id=scout_id,
                scouting_station=scouting_station,
                alliance=alliance,
                data_json=json.dumps(data),
                scouting_team_number=current_user.scouting_team_number
            )
            db.session.add(new_data)
            flash('Scouting data saved successfully!', 'success')
        
        db.session.commit()
        
        # Redirect to QR code page without parameters in URL
        return redirect(url_for('scouting.qr_code_display') + f'?team_id={team.id}&match_id={match.id}')
    
    # Initial page load (GET request)
    team_id = request.args.get('team_id', type=int)
    match_id = request.args.get('match_id', type=int)
    
    # If team_id and match_id are provided in the URL, load that specific form
    if team_id and match_id:
        team = Team.query.get_or_404(team_id)
        match = Match.query.get_or_404(match_id)
        
        # Determine alliance color
        alliance = 'unknown'
        if str(team.team_number) in match.red_alliance.split(','):
            alliance = 'red'
        elif str(team.team_number) in match.blue_alliance.split(','):
            alliance = 'blue'
        
        # Check if data already exists
        existing_data = ScoutingData.query.filter_by(
            team_id=team.id,
            match_id=match.id,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        # Initialize form data
        form_data = {}
        if existing_data:
            try:
                form_data = existing_data.data
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                current_app.logger.error(f"Error parsing existing data for team {team_id}, match {match_id}: {str(e)}")
                form_data = {}
                flash('Warning: Could not load existing form data due to data corruption. Starting with fresh form.', 'warning')
        else:
            # Initialize with defaults
            for period in ['auto_period', 'teleop_period', 'endgame_period']:
                if period in game_config:
                    for element in game_config[period].get('scoring_elements', []):
                        if 'id' in element and 'default' in element:
                            form_data[element['id']] = element['default']
            
            # Add post-match elements
            if 'post_match' in game_config:
                for element_type in ['rating_elements', 'text_elements']:
                    if element_type in game_config['post_match']:
                        for element in game_config['post_match'][element_type]:
                            if 'id' in element and 'default' in element:
                                form_data[element['id']] = element['default']
                                
            # Add any custom identifiers
            if 'custom_identifiers' in game_config:
                for element in game_config['custom_identifiers'].get('elements', []):
                    if 'id' in element and 'default' in element:
                        form_data[element['id']] = element['default']
        
        return render_template('scouting/form.html', 
                              teams=teams, 
                              matches=matches,
                              game_config=game_config, 
                              team=team, 
                              match=match,
                              form_data=form_data,
                              alliance=alliance,
                              existing_data=existing_data,
                              **get_theme_context())
    else:
        # Show form with team/match selection first
        return render_template('scouting/form.html', 
                              teams=teams, 
                              matches=matches,
                              game_config=game_config, 
                              team=None, 
                              match=None,
                              show_team_match_selection=True,
                              **get_theme_context())  # Flag to show selection form

@bp.route('/qr')
def qr_code_display():
    """Generate Data Matrix code for scouting data (without URL parameters)"""
    # Get parameters from query string but don't expose in URL
    team_id = request.args.get('team_id', type=int)
    match_id = request.args.get('match_id', type=int)
    
    if not team_id or not match_id:
        flash('Missing team or match information', 'error')
        return redirect(url_for('scouting.index'))
    
    team = Team.query.get_or_404(team_id)
    match = Match.query.get_or_404(match_id)
    
    # Get scouting data
    scouting_data = ScoutingData.query.filter_by(
        team_id=team.id,
        match_id=match.id,
        scouting_team_number=current_user.scouting_team_number
    ).first_or_404()
    
    # Get game configuration for default values
    game_config = get_current_game_config()
    
    # Process scouting data to minimize size
    compact_data = {}
    id_map = get_id_to_perm_id_mapping()
    perm_id_to_id = {v: k for k, v in id_map.items()}
    for key, value in scouting_data.data.items():
        # Skip default values and empty/zero values to reduce barcode size
        if value == 0 or value == "" or value == False:
            continue
            
        # Store only non-default values
        # Use the current id in the QR code to save space, assuming the client-side scanner will use the latest config
        current_id = perm_id_to_id.get(key, key)
        compact_data[current_id] = value
    
    # Create minimized barcode data with shorter keys
    data_matrix_data = {
        't': team.team_number,              # team_number
        'm': match.match_number,            # match_number
        'mt': match.match_type,             # match_type
        'a': scouting_data.alliance,        # alliance
        's': scouting_data.scout_name,      # scout_name
        'd': compact_data                   # scouting_data (minimized)
    }
    
    # Convert to compact JSON with minimal whitespace
    json_data = json.dumps(data_matrix_data, separators=(',', ':'))
    
    # For display purposes, show the original data
    display_data = {
        'team_number': team.team_number,
        'match_number': match.match_number,
        'match_type': match.match_type,
        'alliance': scouting_data.alliance,
        'scout_name': scouting_data.scout_name,
        'compact_data': compact_data
    }
    
    return render_template('scouting/datamatrix.html', 
                          team=team, 
                          match=match,
                          barcode_data=json_data,  
                          scouting_data=scouting_data,
                          display_data=json.dumps(display_data, indent=2),
                          **get_theme_context())

def _get_element_type_from_config(element_id, game_config):
    """Helper function to get the type of an element from the game configuration"""
    # Check all periods for this element ID
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in game_config:
            for element in game_config[period].get('scoring_elements', []):
                if element.get('id') == element_id:
                    return element.get('type')
    
    # Check post-match elements
    if 'post_match' in game_config:
        # Check rating elements
        for element in game_config['post_match'].get('rating_elements', []):
            if element.get('id') == element_id:
                return 'rating'
        # Check text elements
        for element in game_config['post_match'].get('text_elements', []):
            if element.get('id') == element_id:
                return 'text'
    
    # Check custom identifiers section if it exists
    if 'custom_identifiers' in game_config:
        for element in game_config['custom_identifiers'].get('elements', []):
            if element.get('id') == element_id:
                return element.get('type', 'text')
    
    # Default to text if not found
    return 'text'

@bp.route('/qr/<int:team_id>/<int:match_id>')
def qr_code(team_id, match_id):
    """Generate Data Matrix code for scouting data"""
    team = Team.query.get_or_404(team_id)
    match = Match.query.get_or_404(match_id)
    
    # Get scouting data
    scouting_data = ScoutingData.query.filter_by(
        team_id=team.id,
        match_id=match.id,
        scouting_team_number=current_user.scouting_team_number
    ).first_or_404()
    
    # Get game configuration for default values
    game_config = get_effective_game_config()
    
    # Process scouting data to minimize size
    compact_data = {}
    id_map = get_id_to_perm_id_mapping()
    perm_id_to_id = {v: k for k, v in id_map.items()}
    for key, value in scouting_data.data.items():
        # Skip default values and empty/zero values to reduce barcode size
        if value == 0 or value == "" or value == False:
            continue
            
        # Store only non-default values
        current_id = perm_id_to_id.get(key, key)
        compact_data[current_id] = value
    
    # Create minimized barcode data with shorter keys
    data_matrix_data = {
        't': team.team_number,              # team_number
        'm': match.match_number,            # match_number
        'mt': match.match_type,             # match_type
        'a': scouting_data.alliance,        # alliance
        's': scouting_data.scout_name,      # scout_name
        'd': compact_data                   # scouting_data (minimized)
    }
    
    # Convert to compact JSON with minimal whitespace
    json_data = json.dumps(data_matrix_data, separators=(',', ':'))
    
    # For display purposes, show the original data
    display_data = {
        'team_number': team.team_number,
        'match_number': match.match_number,
        'match_type': match.match_type,
        'alliance': scouting_data.alliance,
        'scout_name': scouting_data.scout_name,
        'compact_data': compact_data
    }
    
    return render_template('scouting/datamatrix.html', 
                          team=team, 
                          match=match,
                          barcode_data=json_data,  
                          scouting_data=scouting_data,
                          display_data=json.dumps(display_data, indent=2),
                          **get_theme_context())

@bp.route('/list')
@login_required
def list_data():
    """List all scouting data"""
    # If the user is ONLY a scout (no analytics or admin role), redirect to the scouting dashboard with a message
    if current_user.has_role('scout') and not current_user.has_role('analytics') and not current_user.has_role('admin'):
        flash('Access to the full scouting data list is restricted. Please contact an administrator for assistance.', 'warning')
        return redirect(url_for('scouting.index'))
    
    scouting_data = (ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number)
                     .join(Match)
                     .join(Event)
                     .join(Team)
                     .order_by(ScoutingData.timestamp.desc())
                     .all())
    
    # Get all events that have scouting data
    events = (Event.query
             .join(Match)
             .join(ScoutingData).filter(ScoutingData.scouting_team_number==current_user.scouting_team_number)
             .distinct()
             .order_by(Event.name)
             .all())
    
    return render_template('scouting/list.html', 
                         scouting_data=scouting_data,
                         events=events,
                         **get_theme_context())

@bp.route('/view/<int:id>')
@login_required
def view_data(id):
    """View a specific scouting data entry"""
    # If the user is ONLY a scout (no analytics or admin role), redirect to the scouting dashboard with a message
    if current_user.has_role('scout') and not current_user.has_role('analytics') and not current_user.has_role('admin'):
        flash('Access to view detailed scouting data is restricted. Please contact an administrator for assistance.', 'warning')
        return redirect(url_for('scouting.index'))
        
    scouting_data = ScoutingData.query.filter_by(id=id, scouting_team_number=current_user.scouting_team_number).first_or_404()
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    return render_template('scouting/view.html', scouting_data=scouting_data, 
                          game_config=game_config,
                          **get_theme_context())

@bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_data(id):
    """Delete a scouting data entry"""
    # If the user is ONLY a scout (no analytics or admin role), redirect to the scouting dashboard with a message
    if current_user.has_role('scout') and not current_user.has_role('analytics') and not current_user.has_role('admin'):
        flash('You do not have permission to delete scouting data. Please contact an administrator for assistance.', 'danger')
        return redirect(url_for('scouting.index'))
        
    scouting_data = ScoutingData.query.filter_by(id=id, scouting_team_number=current_user.scouting_team_number).first_or_404()

    team_number = scouting_data.team.team_number
    match_number = scouting_data.match.match_number

    db.session.delete(scouting_data)
    db.session.commit()

    # If request is AJAX or expects JSON, return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'success': True, 'message': f'Scouting data for Team {team_number} in Match {match_number} deleted!'})

    flash(f'Scouting data for Team {team_number} in Match {match_number} deleted!', 'success')
    return redirect(url_for('scouting.list_data'))

@bp.route('/offline')
def offline_data():
    """Manage offline scouting data"""
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
    
    # Define custom ordering for match types
    match_type_order = {
        'practice': 1,
        'qualification': 2,
        'qualifier': 2,  # Alternative name for qualification matches
        'playoff': 3,
        'elimination': 3,  # Alternative name for playoff matches
    }
    
    # Get matches filtered by the current event if available
    if current_event:
        all_matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).all()
    else:
        all_matches = filter_matches_by_scouting_team().all()
    
    matches = sorted(all_matches, key=lambda m: (
        match_type_order.get(m.match_type.lower(), 99),  # Unknown types go to the end
        m.match_number
    ))
    
    return render_template('scouting/offline.html', 
                           teams=teams, 
                           matches=matches, 
                           game_config=game_config,
                           **get_theme_context())

@bp.route('/api/submit_offline', methods=['POST'])
def submit_offline_data():
    """API endpoint for submitting offline scouting data"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'})
            
        team_id = data.get('team_id')
        match_id = data.get('match_id')
        
        if not team_id or not match_id:
            return jsonify({'success': False, 'message': 'Missing team or match ID'})
            
        # Check if team and match exist
        team = Team.query.get(team_id)
        match = Match.query.get(match_id)
        
        if not team or not match:
            return jsonify({'success': False, 'message': 'Team or match not found'})
            
        # Process the form data
        scout_name = data.get('scout_name')
        alliance = data.get('alliance', 'unknown')
        scout_id = getattr(current_user, 'id', None)
        if not scout_name or str(scout_name).strip() == '':
            scout_name = getattr(current_user, 'username', 'Unknown (offline)')
        
        # Extract actual scouting data
        scouting_data = {}
        for key, value in data.items():
            # Skip metadata fields
            if key in ['team_id', 'match_id', 'scout_name', 'alliance', 'generated_at', 'generated_offline', 'saved_at', 'saved_offline']:
                continue
            scouting_data[key] = value
        
        # Check if entry already exists
        existing_data = ScoutingData.query.filter_by(
            team_id=team_id,
            match_id=match_id,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        if existing_data:
            existing_data.data = scouting_data
            existing_data.scout_name = scout_name
            existing_data.scout_id = scout_id
            existing_data.alliance = alliance
            existing_data.timestamp = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Offline data updated successfully'})
        else:
            new_data = ScoutingData(
                team_id=team_id,
                match_id=match_id,
                scout_name=scout_name,
                scout_id=scout_id,
                alliance=alliance,
                data_json=json.dumps(scouting_data),
                scouting_team_number=current_user.scouting_team_number
            )
            db.session.add(new_data)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Offline data saved successfully'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@bp.route('/api/save', methods=['POST'])
def save_scouting_data():
    """API endpoint for saving scouting data via AJAX"""
    try:
        team_id = request.form.get('team_id', type=int)
        match_id = request.form.get('match_id', type=int)
        
        if not team_id or not match_id:
            return jsonify({'success': False, 'message': 'Both team and match must be provided'})
        
        team = Team.query.get_or_404(team_id)
        match = Match.query.get_or_404(match_id)
        
        # Get other form data
        alliance = request.form.get('alliance', 'unknown')
        scout_name = request.form.get('scout_name')
        scouting_station = request.form.get('scouting_station', type=int)
        scout_id = getattr(current_user, 'id', None)
        if not scout_name or scout_name.strip() == '':
            scout_name = getattr(current_user, 'username', 'Unknown')
        
        # Build data dictionary from form
        data = {}
        
        # Process all form fields dynamically based on their element type
        id_map = get_id_to_perm_id_mapping()
        for key, value in request.form.items():
            # Skip non-data fields
            if key in ['csrf_token', 'scout_name', 'scouting_station', 'team_id', 'match_id', 'alliance']:
                continue
                
            # Find the element in the game config to determine its type
            element_type = _get_element_type_from_config(key, get_effective_game_config())
            perm_id = id_map.get(key, key)
            
            # Process based on type
            if element_type == 'boolean':
                # HTML checkbox fields are only included when checked
                data[perm_id] = key in request.form
            elif element_type == 'counter':
                # Convert to integer
                data[perm_id] = int(request.form.get(key, 0))
            elif element_type == 'select':
                # Store selection as-is
                data[perm_id] = value
            elif element_type == 'rating':
                # Convert to integer
                data[perm_id] = int(value)
            else:
                # For text fields and any other types
                data[perm_id] = value
        
        # Check if data already exists
        existing_data = ScoutingData.query.filter_by(
            team_id=team.id,
            match_id=match.id,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        # Create or update scouting data
        if existing_data:
            existing_data.data = data
            existing_data.scout_name = scout_name
            existing_data.scout_id = scout_id
            existing_data.scouting_station = scouting_station
            existing_data.alliance = alliance
            existing_data.timestamp = datetime.now(timezone.utc)
            message = 'Scouting data updated successfully!'
            saved_entry = existing_data
        else:
            new_data = ScoutingData(
                team_id=team.id,
                match_id=match.id,
                scout_name=scout_name,
                scout_id=scout_id,
                scouting_station=scouting_station,
                alliance=alliance,
                data_json=json.dumps(data),
                scouting_team_number=current_user.scouting_team_number
            )
            db.session.add(new_data)
            message = 'Scouting data saved successfully!'
            saved_entry = new_data
        
        db.session.commit()
        
        # Automatically sync to alliance members if alliance mode is active
        auto_sync_alliance_data(saved_entry)
        
        # Return success response with redirection URL
        return jsonify({
            'success': True, 
            'message': message,
            'redirect_url': url_for('scouting.qr_code_display', team_id=team.id, match_id=match.id)
        })
        
    except Exception as e:
        # Return error response
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api_save', methods=['POST'])
def api_save():
    """API endpoint for AJAX form submission"""
    try:
        team_id = request.form.get('team_id', type=int)
        match_id = request.form.get('match_id', type=int)
        
        if not team_id or not match_id:
            return jsonify({'success': False, 'message': 'Both team and match must be provided'})
        
        team = Team.query.get_or_404(team_id)
        match = Match.query.get_or_404(match_id)
        
        # Get other form data
        alliance = request.form.get('alliance', 'unknown')
        scout_name = request.form.get('scout_name')
        scouting_station = request.form.get('scouting_station', type=int)
        scout_id = getattr(current_user, 'id', None)
        if not scout_name or scout_name.strip() == '':
            scout_name = getattr(current_user, 'username', 'Unknown')
        
        # Build data dictionary from form
        data = {}
        
        # Process all form fields dynamically based on their element type
        id_map = get_id_to_perm_id_mapping()
        for key, value in request.form.items():
            # Skip non-data fields
            if key in ['csrf_token', 'scout_name', 'scouting_station', 'team_id', 'match_id', 'alliance']:
                continue
                
            # Find the element in the game config to determine its type
            element_type = _get_element_type_from_config(key, current_app.config['GAME_CONFIG'])
            perm_id = id_map.get(key, key)
            
            # Process based on type
            if element_type == 'boolean':
                # HTML checkbox fields are only included when checked
                data[perm_id] = key in request.form
            elif element_type == 'counter':
                # Convert to integer
                data[perm_id] = int(request.form.get(key, 0))
            elif element_type == 'select':
                # Store selection as-is
                data[perm_id] = value
            elif element_type == 'rating':
                # Convert to integer
                data[perm_id] = int(value)
            else:
                # For text fields and any other types
                data[perm_id] = value
        
        # Check if data already exists
        existing_data = ScoutingData.query.filter_by(
            team_id=team.id,
            match_id=match.id,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        # Create or update scouting data
        if existing_data:
            existing_data.data = data
            existing_data.scout_name = scout_name
            existing_data.scout_id = scout_id
            existing_data.scouting_station = scouting_station
            existing_data.alliance = alliance
            existing_data.timestamp = datetime.now(timezone.utc)
            message = 'Scouting data updated successfully!'
            action = 'updated'
            saved_entry = existing_data
        else:
            new_data = ScoutingData(
                team_id=team.id,
                match_id=match.id,
                scout_name=scout_name,
                scout_id=scout_id,
                scouting_station=scouting_station,
                alliance=alliance,
                data_json=json.dumps(data),
                scouting_team_number=current_user.scouting_team_number
            )
            db.session.add(new_data)
            message = 'Scouting data saved successfully!'
            action = 'created'
            saved_entry = new_data
        
        db.session.commit()
        
        # Automatically sync to alliance members if alliance mode is active
        auto_sync_alliance_data(saved_entry)
        
        # Return success response without the redirect URL
        return jsonify({
            'success': True, 
            'message': message,
            'team_number': team.team_number,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'action': action,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        # Return error response with detailed message
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/text-elements')
@login_required
def view_text_elements():
    """View all submitted text elements across all scouting data"""
    # Get game configuration to identify text elements
    game_config = get_effective_game_config()
    
    # Get current event based on configuration
    current_event_code = game_config.get('current_event_code')
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
    
    # Get all text elements from configuration
    text_elements = game_config.get('post_match', {}).get('text_elements', [])
    
    if not text_elements:
        flash('No text elements are configured in the game configuration.', 'info')
        return redirect(url_for('scouting.index'))
    
    # Get scouting data with text elements
    query = (ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number)
             .join(Match)
             .join(Event)
             .join(Team)
             .order_by(ScoutingData.timestamp.desc()))
    
    # Filter by current event if available
    if current_event:
        query = query.filter(Event.id == current_event.id)
    
    all_scouting_data = query.all()
    
    # Filter out entries that have text data
    scouting_entries_with_text = []
    for entry in all_scouting_data:
        has_text_data = False
        text_data = {}
        
        for element in text_elements:
            element_id = element.get('id')
            if element_id and entry.data.get(element_id):
                value = entry.data.get(element_id, '').strip()
                if value:  # Only include non-empty text
                    text_data[element_id] = value
                    has_text_data = True
        
        if has_text_data:
            scouting_entries_with_text.append({
                'entry': entry,
                'text_data': text_data
            })
    
    # Get all events that have scouting data for the filter
    events = (Event.query
             .join(Match)
             .join(ScoutingData).filter(ScoutingData.scouting_team_number==current_user.scouting_team_number)
             .distinct()
             .order_by(Event.name)
             .all())
    
    return render_template('scouting/text_elements.html',
                         scouting_entries=scouting_entries_with_text,
                         text_elements=text_elements,
                         events=events,
                         current_event=current_event,
                         game_config=game_config,
                         **get_theme_context())