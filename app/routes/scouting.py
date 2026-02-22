from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Match, Team, ScoutingData, Event, AllianceSharedScoutingData, QualitativeScoutingData
from app import db, socketio
import json
from datetime import datetime, timezone
from app.utils.timezone_utils import utc_now_iso
import qrcode
from io import BytesIO
import base64
from app.utils.config_manager import get_id_to_perm_id_mapping, get_current_game_config, get_effective_game_config, is_alliance_mode_active
from app.utils.theme_manager import ThemeManager
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code, get_all_teams_at_event, get_combined_dropdown_events
)
from app.utils.alliance_data import (
    get_all_scouting_data, get_events_with_scouting_data, 
    can_delete_scouting_entry, is_alliance_admin, get_active_alliance_id,
    normalize_scouting_entry, get_all_teams_for_alliance, get_all_matches_for_alliance
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
        
        # Check if current team has data sharing enabled
        current_member = ScoutingAllianceMember.query.filter_by(
            alliance_id=alliance.id,
            team_number=current_team,
            status='accepted'
        ).first()
        
        # If data sharing is disabled for this team, don't sync their data to others
        if current_member and not getattr(current_member, 'is_data_sharing_active', True):
            return
        
        # Also save to AllianceSharedScoutingData for centralized alliance storage
        existing_shared = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance.id,
            original_scouting_data_id=scouting_data_entry.id,
            is_active=True
        ).first()
        
        if existing_shared:
            # Update existing shared data
            existing_shared.data = scouting_data_entry.data
            existing_shared.scout_name = scouting_data_entry.scout_name
            existing_shared.scout_id = scouting_data_entry.scout_id
            existing_shared.scouting_station = scouting_data_entry.scouting_station
            existing_shared.alliance = scouting_data_entry.alliance
            existing_shared.timestamp = scouting_data_entry.timestamp
            existing_shared.last_edited_by_team = current_team
            existing_shared.last_edited_at = datetime.now(timezone.utc)
        else:
            # Create new shared data entry
            shared_data = AllianceSharedScoutingData.create_from_scouting_data(
                scouting_data_entry, alliance.id, current_team
            )
            db.session.add(shared_data)
        
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
    if current_event_code:
        current_event_code = str(current_event_code).strip()

    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)  # Use filtered function

    # Also get combined events to allow correct synthetic/alliance selection from URL params
    force_selected_event = False
    try:
        events = get_combined_dropdown_events()
    except Exception:
        events = []

    # Prefer synthetic alliance entry when configured (override local copy when alliance active)
    try:
        if current_event_code and events:
            code_up = str(current_event_code).upper()
            evt = next((e for e in events if getattr(e, 'is_alliance', False) and (getattr(e, 'code', '') or '').upper() == code_up), None)
            if evt and get_active_alliance_id():
                current_event = evt
    except Exception:
        pass

    # Respect raw event_id URL params that may specify synthetic ids or codes
    try:
        raw_event_param = request.args.get('event_id')
        if raw_event_param and events:
            if isinstance(raw_event_param, str):
                if raw_event_param.startswith('alliance_'):
                    evt = next((e for e in events if str(getattr(e, 'id', '')) == raw_event_param), None)
                    if evt:
                        current_event = evt
                else:
                    code_up = raw_event_param.upper()
                    evt = next((e for e in events if (getattr(e, 'code', '') or '').upper() == code_up), None)
                    if evt:
                        current_event = evt
    except Exception:
        pass

    # Check if alliance mode is active
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # If no current_event and not in alliance mode, default to the current team's most-recent event
    try:
        if not current_event and not is_alliance_mode:
            team_event = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.start_date.desc(), Event.id.desc()).first()
            if team_event:
                current_event = team_event
    except Exception:
        pass

    # Get teams - use alliance teams if in alliance mode
    if is_alliance_mode:
        if current_event:
            try:
                is_synthetic = isinstance(getattr(current_event, 'id', None), str) and str(current_event.id).startswith('alliance_')
            except Exception:
                is_synthetic = False
            if is_synthetic:
                teams, _ = get_all_teams_for_alliance(event_code=getattr(current_event, 'code', None))
            else:
                teams, _ = get_all_teams_for_alliance(event_id=current_event.id)
        else:
            teams, _ = get_all_teams_for_alliance()
    else:
        # Get teams filtered by the current event and scouting team
        if current_event:
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func
            event_code = getattr(current_event, 'code', None)
            if event_code:
                teams = filter_teams_by_scouting_team().join(
                    Team.events
                ).filter(func.upper(Event.code) == event_code.upper()).order_by(Team.team_number).all()
            else:
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
    
    # Get matches - use alliance matches if in alliance mode
    if is_alliance_mode:
        if current_event:
            all_matches, _ = get_all_matches_for_alliance(event_id=current_event.id)
        else:
            all_matches, _ = get_all_matches_for_alliance()
    else:
        # Get matches filtered by the current event if available
        if current_event:
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func as sqlfunc
            evt_code = getattr(current_event, 'code', None)
            if evt_code:
                all_matches = filter_matches_by_scouting_team().join(
                    Event, Match.event_id == Event.id
                ).filter(sqlfunc.upper(Event.code) == evt_code.upper()).all()
            else:
                all_matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).all()
        else:
            all_matches = filter_matches_by_scouting_team().all()
    
    matches = sorted(all_matches, key=lambda m: (
        match_type_order.get(m.match_type.lower(), 99),  # Unknown types go to the end
        m.match_number
    ))
    
    # Get recent scouting data - use alliance data if alliance mode is active
    if is_alliance_mode:
        recent_scouting_data = AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        ).order_by(AllianceSharedScoutingData.timestamp.desc()).limit(5).all()
    else:
        # Exclude alliance-copied data (scout_name starts with [Alliance-)
        recent_scouting_data = ScoutingData.query.filter(
            ScoutingData.scouting_team_number == current_user.scouting_team_number,
            db.or_(
                ScoutingData.scout_name == None,
                ~ScoutingData.scout_name.like('[Alliance-%')
            )
        ).order_by(ScoutingData.timestamp.desc()).limit(5).all()
    
    return render_template('scouting/index.html', 
                          teams=teams, 
                          matches=matches,
                          scouting_data=recent_scouting_data,  
                          game_config=game_config,
                          force_selected_event=force_selected_event if 'force_selected_event' in locals() else False,
                          is_alliance_mode=is_alliance_mode,
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
    
    # Check if alliance mode is active
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None

    # If no current_event and not in alliance mode, default to the current team's most-recent event
    try:
        if not current_event and not is_alliance_mode:
            team_event = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.start_date.desc(), Event.id.desc()).first()
            if team_event:
                current_event = team_event
    except Exception:
        pass
    
    # Get teams - use alliance teams if in alliance mode
    if is_alliance_mode:
        if current_event:
            teams, _ = get_all_teams_for_alliance(event_id=current_event.id)
        else:
            teams, _ = get_all_teams_for_alliance()
    else:
        # Get teams filtered by the current event and scouting team
        if current_event:
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func
            event_code = getattr(current_event, 'code', None)
            if event_code:
                teams = filter_teams_by_scouting_team().join(
                    Team.events
                ).filter(func.upper(Event.code) == event_code.upper()).order_by(Team.team_number).all()
            else:
                teams = filter_teams_by_scouting_team().join(
                    Team.events
                ).filter(Event.id == current_event.id).order_by(Team.team_number).all()
        else:
            teams = []  # No teams if no current event is set

    # Deduplicate team listings by team_number to avoid duplicate logical teams
    try:
        from app.utils.team_isolation import dedupe_team_list, get_alliance_team_numbers, get_current_scouting_team_number
        alliance_team_nums = get_alliance_team_numbers() or []
        current_scouting_team = get_current_scouting_team_number()
        teams = dedupe_team_list(list(teams or []), prefer_alliance=bool(alliance_id), alliance_team_numbers=alliance_team_nums, current_scouting_team=current_scouting_team)
    except Exception:
        teams = list(teams or [])

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
    
    # Get matches - use alliance matches if in alliance mode
    if is_alliance_mode:
        if current_event:
            all_matches, _ = get_all_matches_for_alliance(event_id=current_event.id)
        else:
            all_matches, _ = get_all_matches_for_alliance()
    else:
        # Get matches filtered by the current event if available
        if current_event:
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func as sql_func
            event_code = getattr(current_event, 'code', None)
            if event_code:
                all_matches = filter_matches_by_scouting_team().join(
                    Event, Match.event_id == Event.id
                ).filter(sql_func.upper(Event.code) == event_code.upper()).all()
            else:
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
        
        # Check if alliance mode is active
        alliance_id = get_active_alliance_id()
        is_alliance_mode = alliance_id is not None
        
        # Create or update scouting data
        if existing_data:
            existing_data.data = data
            existing_data.scout_name = scout_name
            existing_data.scout_id = scout_id
            existing_data.scouting_station = scouting_station
            existing_data.alliance = alliance
            existing_data.timestamp = datetime.now(timezone.utc)
            
            # If alliance mode is active, also update or create alliance shared data
            if is_alliance_mode:
                existing_shared = AllianceSharedScoutingData.query.filter_by(
                    alliance_id=alliance_id,
                    original_scouting_data_id=existing_data.id,
                    is_active=True
                ).first()
                
                if existing_shared:
                    # Update existing shared data
                    existing_shared.data = data
                    existing_shared.scout_name = scout_name
                    existing_shared.scout_id = scout_id
                    existing_shared.scouting_station = scouting_station
                    existing_shared.alliance = alliance
                    existing_shared.timestamp = datetime.now(timezone.utc)
                    existing_shared.last_edited_by_team = current_user.scouting_team_number
                    existing_shared.last_edited_at = datetime.now(timezone.utc)
                else:
                    # Create new shared data entry
                    shared_data = AllianceSharedScoutingData.create_from_scouting_data(
                        existing_data, alliance_id, current_user.scouting_team_number
                    )
                    db.session.add(shared_data)
            
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
            db.session.flush()  # Get the ID for the new record
            
            # If alliance mode is active, also create alliance shared data
            if is_alliance_mode:
                shared_data = AllianceSharedScoutingData.create_from_scouting_data(
                    new_data, alliance_id, current_user.scouting_team_number
                )
                db.session.add(shared_data)
            
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
    
    # Get game configuration for default values (alliance-aware)
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
    """List all scouting data - uses alliance shared data when alliance mode is active"""
    # If the user is ONLY a scout (no analytics or admin role), redirect to the scouting dashboard with a message
    if current_user.has_role('scout') and not current_user.has_role('analytics') and not current_user.has_role('admin'):
        flash('Access to the full scouting data list is restricted. Please contact an administrator for assistance.', 'warning')
        return redirect(url_for('scouting.index'))
    
    # Get scouting data - automatically uses alliance shared data if alliance mode is active
    scouting_data, is_alliance_mode, alliance_id = get_all_scouting_data()
    
    # Get events with scouting data
    events, _, _ = get_events_with_scouting_data()
    
    # Check if user is alliance admin (for delete permissions)
    user_is_alliance_admin = is_alliance_admin(alliance_id) if is_alliance_mode else False
    
    return render_template('scouting/list.html', 
                         scouting_data=scouting_data,
                         events=events,
                         is_alliance_mode=is_alliance_mode,
                         alliance_id=alliance_id,
                         user_is_alliance_admin=user_is_alliance_admin,
                         **get_theme_context())

@bp.route('/view/<int:id>')
@login_required
def view_data(id):
    """View a specific scouting data entry - supports both regular and alliance shared data"""
    # If the user is ONLY a scout (no analytics or admin role), redirect to the scouting dashboard with a message
    if current_user.has_role('scout') and not current_user.has_role('analytics') and not current_user.has_role('admin'):
        flash('Access to view detailed scouting data is restricted. Please contact an administrator for assistance.', 'warning')
        return redirect(url_for('scouting.index'))
    
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # Check for shared_id parameter (alliance mode)
    shared_id = request.args.get('shared_id', type=int)
    
    if is_alliance_mode and shared_id:
        # Viewing alliance shared data
        scouting_data = AllianceSharedScoutingData.query.filter_by(
            id=shared_id,
            alliance_id=alliance_id,
            is_active=True
        ).first_or_404()
    elif is_alliance_mode:
        # Try to find in alliance data first
        scouting_data = AllianceSharedScoutingData.query.filter_by(
            id=id,
            alliance_id=alliance_id,
            is_active=True
        ).first()
        if not scouting_data:
            # Fall back to regular data
            scouting_data = ScoutingData.query.filter_by(id=id, scouting_team_number=current_user.scouting_team_number).first_or_404()
    else:
        scouting_data = ScoutingData.query.filter_by(id=id, scouting_team_number=current_user.scouting_team_number).first_or_404()
    
    # Get game configuration
    game_config = get_effective_game_config()
    
    # Check delete permissions
    can_delete = can_delete_scouting_entry(scouting_data, is_alliance_mode, alliance_id)
    user_is_alliance_admin = is_alliance_admin(alliance_id) if is_alliance_mode else False
    
    return render_template('scouting/view.html', scouting_data=scouting_data, 
                          game_config=game_config,
                          is_alliance_mode=is_alliance_mode,
                          alliance_id=alliance_id,
                          can_delete=can_delete,
                          user_is_alliance_admin=user_is_alliance_admin,
                          **get_theme_context())

@bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_data(id):
    """Delete a scouting data entry - enforces alliance delete permissions"""
    # If the user is ONLY a scout (no analytics or admin role), redirect to the scouting dashboard with a message
    if current_user.has_role('scout') and not current_user.has_role('analytics') and not current_user.has_role('admin'):
        flash('You do not have permission to delete scouting data. Please contact an administrator for assistance.', 'danger')
        return redirect(url_for('scouting.index'))
    
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # Check for shared_id in request (alliance mode delete)
    data = request.get_json() if request.is_json else {}
    shared_id = data.get('shared_id') or request.form.get('shared_id')
    
    if is_alliance_mode and shared_id:
        # Deleting alliance shared data
        scouting_data = AllianceSharedScoutingData.query.filter_by(
            id=shared_id,
            alliance_id=alliance_id
        ).first_or_404()
        
        # Check permissions
        if not can_delete_scouting_entry(scouting_data, is_alliance_mode, alliance_id):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                return jsonify({'success': False, 'error': 'Only alliance admins or the original scout can delete this data'}), 403
            flash('Only alliance admins or the original scout can delete this data.', 'danger')
            return redirect(url_for('scouting.list_data'))
        
        team_number = scouting_data.team.team_number if scouting_data.team else 'Unknown'
        match_number = scouting_data.match.match_number if scouting_data.match else 'Unknown'
        
        # Use the alliance delete endpoint logic
        from app.models import AllianceDeletedData
        AllianceDeletedData.mark_deleted(
            alliance_id=alliance_id,
            data_type='scouting',
            match_id=scouting_data.match_id,
            team_id=scouting_data.team_id,
            alliance_color=scouting_data.alliance,
            source_team=scouting_data.source_scouting_team_number,
            deleted_by=current_user.scouting_team_number
        )
        db.session.delete(scouting_data)
        db.session.commit()
    else:
        # Regular delete
        scouting_data = ScoutingData.query.filter_by(id=id, scouting_team_number=current_user.scouting_team_number).first_or_404()
        
        # In alliance mode, check if user can delete their own team's data
        if is_alliance_mode and not can_delete_scouting_entry(scouting_data, is_alliance_mode, alliance_id):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                return jsonify({'success': False, 'error': 'Only alliance admins or the original scout can delete this data'}), 403
            flash('Only alliance admins or the original scout can delete this data.', 'danger')
            return redirect(url_for('scouting.list_data'))
        
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
    
    # If no current_event, default to the current team's most-recent event
    try:
        if not current_event:
            team_event = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.start_date.desc(), Event.id.desc()).first()
            if team_event:
                current_event = team_event
    except Exception:
        pass
    
    # Get ALL teams at the current event (regardless of scouting_team_number)
    if current_event:
        teams = get_all_teams_at_event(event_id=current_event.id)
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
        # Use event code matching to handle cross-team event lookups
        from sqlalchemy import func as offline_func
        evt_code = getattr(current_event, 'code', None)
        if evt_code:
            all_matches = filter_matches_by_scouting_team().join(
                Event, Match.event_id == Event.id
            ).filter(offline_func.upper(Event.code) == evt_code.upper()).all()
        else:
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
            # Sync to alliance if active
            auto_sync_alliance_data(existing_data)
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
            # Sync to alliance if active
            auto_sync_alliance_data(new_data)
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
            'timestamp': utc_now_iso()
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
    
    # If no current_event, default to the current team's most-recent event
    try:
        if not current_event:
            team_event = filter_events_by_scouting_team().order_by(Event.year.desc(), Event.start_date.desc(), Event.id.desc()).first()
            if team_event:
                current_event = team_event
    except Exception:
        pass
    
    # Get all text elements from configuration
    text_elements = game_config.get('post_match', {}).get('text_elements', [])

    # Check for alliance mode
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None
    
    # Get scouting data with text elements - use alliance data if in alliance mode
    if is_alliance_mode:
        from sqlalchemy import func
        query = (AllianceSharedScoutingData.query.filter_by(
            alliance_id=alliance_id,
            is_active=True
        )
        .join(Match)
        .join(Event)
        .join(Team)
        .order_by(AllianceSharedScoutingData.timestamp.desc()))
        
        # Filter by current event code if available (not event_id in alliance mode)
        if current_event and current_event.code:
            query = query.filter(func.upper(Event.code) == func.upper(current_event.code))
    else:
        query = (ScoutingData.query.filter(
            ScoutingData.scouting_team_number == current_user.scouting_team_number,
            db.or_(
                ScoutingData.scout_name == None,
                ~ScoutingData.scout_name.like('[Alliance-%')
            )
        )
                 .join(Match)
                 .join(Event)
                 .join(Team)
                 .order_by(ScoutingData.timestamp.desc()))
        
        # Filter by current event if available (use event code matching for cross-team scenarios)
        if current_event:
            from sqlalchemy import func as text_func
            evt_code = getattr(current_event, 'code', None)
            if evt_code:
                query = query.filter(text_func.upper(Event.code) == evt_code.upper())
            else:
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
    
    # Get combined/deduped events but only include those that have scouting data
    from app.utils.team_isolation import get_combined_dropdown_events, get_alliance_team_numbers
    # Determine the set of team numbers to include in scouting data queries (current team + alliance members)
    current_team = current_user.scouting_team_number
    alliance_team_numbers = get_alliance_team_numbers() or []
    team_filter_numbers = set(alliance_team_numbers)
    if current_team is not None:
        team_filter_numbers.add(current_team)

    # Find all event codes or ids that have scouting data for this set of teams
    try:
        if team_filter_numbers:
            event_ids_with_data = set([m.event_id for m in Match.query.join(ScoutingData).filter(ScoutingData.scouting_team_number.in_(list(team_filter_numbers))).all() if getattr(m, 'event_id', None)])
            event_codes_with_data = set([getattr(m.event, 'code', '').upper() for m in Match.query.join(ScoutingData).filter(ScoutingData.scouting_team_number.in_(list(team_filter_numbers))).all() if getattr(m, 'event', None) and getattr(m.event, 'code', None)])
        else:
            event_ids_with_data = set([m.event_id for m in Match.query.join(ScoutingData).filter(ScoutingData.scouting_team_number == current_team).all() if getattr(m, 'event_id', None)])
            event_codes_with_data = set([getattr(m.event, 'code', '').upper() for m in Match.query.join(ScoutingData).filter(ScoutingData.scouting_team_number == current_team).all() if getattr(m, 'event', None) and getattr(m.event, 'code', None)])
    except Exception:
        event_ids_with_data = set()
        event_codes_with_data = set()

    events_combined = get_combined_dropdown_events()
    events = []
    for ev in events_combined:
        # Allow if actual ORM event id is known and present in data set
        ev_id = getattr(ev, 'id', None)
        ev_code = getattr(ev, 'code', '')
        if ev_id and ev_id in event_ids_with_data:
            events.append(ev)
            continue
        if ev_code and ev_code.upper() in event_codes_with_data:
            events.append(ev)
            continue
    
    # Collect qualitative scouting notes
    qual_query = QualitativeScoutingData.query.filter_by(
        scouting_team_number=current_user.scouting_team_number
    ).join(Match).join(Event).order_by(QualitativeScoutingData.timestamp.desc())
    if current_event and getattr(current_event, 'code', None):
        from sqlalchemy import func as _sqf
        qual_query = qual_query.filter(_sqf.upper(Event.code) == current_event.code.upper())
    qualitative_with_notes = []
    for qentry in qual_query.all():
        qdata = qentry.data
        notes_list = []
        for alliance_key in ['red', 'blue', 'individual']:
            alliance_data = qdata.get(alliance_key, {})
            if not isinstance(alliance_data, dict):
                continue
            for team_key, team_data in alliance_data.items():
                if isinstance(team_data, dict) and (team_data.get('notes') or '').strip():
                    notes_list.append({
                        'team_num': team_key.replace('team_', ''),
                        'alliance': alliance_key,
                        'notes': team_data['notes'].strip()
                    })
        if notes_list:
            qualitative_with_notes.append({'entry': qentry, 'notes_list': notes_list})

    return render_template('scouting/text_elements.html',
                         scouting_entries=scouting_entries_with_text,
                         text_elements=text_elements,
                         events=events,
                         current_event=current_event,
                         game_config=game_config,
                         qualitative_with_notes=qualitative_with_notes,
                         **get_theme_context())


@bp.route('/qualitative')
@login_required
def qualitative_scouting():
    """Display qualitative scouting form"""
    # Get game configuration and current event (respect alliance config)
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code') if isinstance(game_config, dict) else None
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)

    # Respect alliance mode
    alliance_id = get_active_alliance_id()
    is_alliance_mode = alliance_id is not None

    # Determine matches to show: prefer current_event if available
    if is_alliance_mode:
        # Use alliance-specific match set when in alliance mode
        if current_event:
            matches, _ = get_all_matches_for_alliance(event_id=current_event.id)
        else:
            matches, _ = get_all_matches_for_alliance()
    else:
        if current_event:
            # Use event code matching to handle cross-team event lookups
            from sqlalchemy import func as sqlfunc
            evt_code = getattr(current_event, 'code', None)
            if evt_code:
                matches = filter_matches_by_scouting_team().join(
                    Event, Match.event_id == Event.id
                ).filter(sqlfunc.upper(Event.code) == evt_code.upper()).order_by(
                    Event.start_date.desc(), Match.match_type, Match.match_number
                ).all()
            else:
                matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).order_by(
                    Event.start_date.desc(), Match.match_type, Match.match_number
                ).all()
        else:
            # No current_event: show all matches filtered by scouting team
            matches = filter_matches_by_scouting_team().join(Event).order_by(
                Event.start_date.desc(), Match.match_type, Match.match_number
            ).all()
    
    # Get existing qualitative scouting data
    existing_data = QualitativeScoutingData.query.filter_by(
        scouting_team_number=current_user.scouting_team_number
    ).order_by(QualitativeScoutingData.timestamp.desc()).all()
    
    return render_template('scouting/qualitative.html',
                         matches=matches,
                         existing_data=existing_data,
                         **get_theme_context())


@bp.route('/qualitative/match/<int:match_id>')
@login_required
def get_match_teams(match_id):
    """API endpoint to get teams for a specific match"""
    match = filter_matches_by_scouting_team().filter_by(id=match_id).first_or_404()
    
    # Get existing data for this match if any
    existing = QualitativeScoutingData.query.filter_by(
        match_id=match_id,
        scouting_team_number=current_user.scouting_team_number
    ).first()
    
    return jsonify({
        'success': True,
        'match': {
            'id': match.id,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'event_code': match.event.code if match.event else '',
            'red_teams': match.red_teams,
            'blue_teams': match.blue_teams
        },
        'existing_data': existing.to_dict() if existing else None
    })


@bp.route('/qualitative/save', methods=['POST'])
@login_required
def save_qualitative_scouting():
    """Save Qualitative scouting data"""
    try:
        data = request.get_json()
        individual_team = data.get('individual_team', False)
        
        if individual_team:
            # Individual team scouting mode (from a match, single team)
            team_number = data.get('team_number')
            match_id = data.get('match_id')
            team_data = data.get('team_data', {})
            show_auto = data.get('show_auto_climb', False)
            show_endgame = data.get('show_endgame_climb', False)
            match_summary = data.get('match_summary') or {}
            
            if not team_number or not match_id:
                return jsonify({'success': False, 'message': 'Missing team number or match'}), 400

            # Server-side validation: ranking required for individual entries
            individual_block = team_data.get('individual', {})
            team_key = f'team_{team_number}'
            indiv_entry = individual_block.get(team_key)
            if not indiv_entry or indiv_entry.get('ranking') is None:
                return jsonify({'success': False, 'message': 'Ranking required for individual team entries'}), 400

            # If Auto/Endgame fields are visible in the UI, require them here
            if show_auto and not (indiv_entry and indiv_entry.get('auto_climb_result')):
                return jsonify({'success': False, 'message': 'Auto climb required when Auto Climb is visible'}), 400
            if show_endgame and not (indiv_entry and indiv_entry.get('endgame_climb_result')):
                return jsonify({'success': False, 'message': 'Endgame climb result required when Endgame Climb is visible'}), 400
            
            # Prepare stored data (include match_summary if present)
            store_obj = {
                'individual': team_data.get('individual', {}),
                'team_number': team_number
            }
            if match_summary:
                store_obj['_match_summary'] = match_summary

            # Individual team entries are always new (one per team per match)
            qualitative_data = QualitativeScoutingData(
                match_id=match_id,
                scouting_team_number=current_user.scouting_team_number,
                scout_name=current_user.username,
                scout_id=current_user.id,
                alliance_scouted=team_key,
                data_json=json.dumps(store_obj)
            )
            db.session.add(qualitative_data)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Qualitative scouting for team {team_number} saved successfully',
                'entry_id': qualitative_data.id
            })
        else:
            # Match-based scouting mode (existing logic)
            match_id = data.get('match_id')
            alliance_scouted = data.get('alliance_scouted')
            team_data = data.get('team_data', {})
            
            if not match_id or not alliance_scouted:
                return jsonify({'success': False, 'message': 'Missing required fields'}), 400

            # Respect UI visibility flags: require Auto/Endgame only when visible
            show_auto = data.get('show_auto_climb', False)
            show_endgame = data.get('show_endgame_climb', False)
            match_summary = data.get('match_summary') or {}

            # Server-side validation: require rankings for all teams in the selected alliance(s)
            if alliance_scouted in ('red', 'both'):
                for k, v in (team_data.get('red') or {}).items():
                    if v.get('ranking') is None:
                        return jsonify({'success': False, 'message': 'All teams in the selected alliance must be ranked'}), 400
                    if show_auto and not v.get('auto_climb_result'):
                        return jsonify({'success': False, 'message': 'Auto climb required for all teams in the selected alliance(s) when Auto Climb is visible'}), 400
                    if show_endgame and not v.get('endgame_climb_result'):
                        return jsonify({'success': False, 'message': 'Endgame climb result required for all teams in the selected alliance(s) when Endgame Climb is visible'}), 400
            if alliance_scouted in ('blue', 'both'):
                for k, v in (team_data.get('blue') or {}).items():
                    if v.get('ranking') is None:
                        return jsonify({'success': False, 'message': 'All teams in the selected alliance must be ranked'}), 400
                    if show_auto and not v.get('auto_climb_result'):
                        return jsonify({'success': False, 'message': 'Auto climb required for all teams in the selected alliance(s) when Auto Climb is visible'}), 400
                    if show_endgame and not v.get('endgame_climb_result'):
                        return jsonify({'success': False, 'message': 'Endgame climb result required for all teams in the selected alliance(s) when Endgame Climb is visible'}), 400
            
            # Attach match_summary into stored data so view/leaderboard can surface it
            if match_summary:
                team_data['_match_summary'] = match_summary

            # Check if entry already exists
            existing = QualitativeScoutingData.query.filter_by(
                match_id=match_id,
                scouting_team_number=current_user.scouting_team_number
            ).first()
            
            if existing:
                # Update existing entry
                existing.alliance_scouted = alliance_scouted
                existing.data = team_data
                existing.timestamp = datetime.now(timezone.utc)
                existing.scout_name = current_user.username
                existing.scout_id = current_user.id
            else:
                # Create new entry
                qualitative_data = QualitativeScoutingData(
                    match_id=match_id,
                    scouting_team_number=current_user.scouting_team_number,
                    scout_name=current_user.username,
                    scout_id=current_user.id,
                    alliance_scouted=alliance_scouted,
                    data_json=json.dumps(team_data)
                )
                db.session.add(qualitative_data)
            
            db.session.commit()
            
            # Get the entry ID (either existing or newly created)
            entry_id = existing.id if existing else qualitative_data.id
            
            return jsonify({
                'success': True,
                'message': 'Qualitative scouting data saved successfully',
                'entry_id': entry_id
            })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving Qualitative scouting data: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error saving data: {str(e)}'
        }), 500


@bp.route('/qualitative/view/<int:entry_id>')
@login_required
def view_qualitative_data(entry_id):
    """View a specific Qualitative scouting entry"""
    entry = QualitativeScoutingData.query.filter_by(
        id=entry_id,
        scouting_team_number=current_user.scouting_team_number
    ).first_or_404()
    
    return render_template('scouting/qualitative_view.html',
                         entry=entry,
                         data=entry.data,
                         **get_theme_context())


@bp.route('/qualitative/delete/<int:entry_id>', methods=['POST'])
@login_required
def delete_qualitative_data(entry_id):
    """Delete a Qualitative scouting entry"""
    try:
        entry = QualitativeScoutingData.query.filter_by(
            id=entry_id,
            scouting_team_number=current_user.scouting_team_number
        ).first_or_404()
        
        db.session.delete(entry)
        db.session.commit()
        
        flash('Qualitative scouting data deleted successfully', 'success')
        return redirect(url_for('scouting.qualitative_scouting'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting Qualitative scouting data: {str(e)}")
        flash(f'Error deleting data: {str(e)}', 'danger')
        return redirect(url_for('scouting.qualitative_scouting'))


@bp.route('/qualitative/list')
@login_required
def list_qualitative_data():
    """Display all Qualitative scouting data in a list view"""
    # Get all Qualitative scouting data for the current team
    entries = QualitativeScoutingData.query.filter_by(
        scouting_team_number=current_user.scouting_team_number
    ).join(Match).join(Event).order_by(
        Event.start_date.desc(),
        Match.match_type,
        Match.match_number
    ).all()
    
    # Group entries by event
    from collections import defaultdict
    entries_by_event = defaultdict(list)
    for entry in entries:
        event_code = entry.match.event.code if entry.match.event else 'Unknown'
        entries_by_event[event_code].append(entry)
    
    return render_template('scouting/qualitative_list.html',
                         entries_by_event=dict(entries_by_event),
                         total_entries=len(entries),
                         **get_theme_context())


@bp.route('/qualitative/leaderboard')
@login_required
def qualitative_leaderboard():
    """Display a leaderboard of teams ranked by qualitative scouting rankings"""
    from collections import defaultdict

    # Get events that have qualitative scouting data for this team
    events_with_data = (
        Event.query
        .join(Match, Match.event_id == Event.id)
        .join(QualitativeScoutingData, QualitativeScoutingData.match_id == Match.id)
        .filter(QualitativeScoutingData.scouting_team_number == current_user.scouting_team_number)
        .distinct()
        .order_by(Event.start_date.desc())
        .all()
    )

    # Optional event filter from query param
    selected_event_id = request.args.get('event_id', type=int)

    # Build base query
    base_query = QualitativeScoutingData.query.filter_by(
        scouting_team_number=current_user.scouting_team_number
    )
    if selected_event_id:
        base_query = base_query.join(Match, QualitativeScoutingData.match_id == Match.id).filter(
            Match.event_id == selected_event_id
        )
    all_entries = base_query.all()

    # Aggregate rankings by team
    team_rankings = defaultdict(lambda: {
        'rankings': [],
        'notes': [],
        'appearances': 0,
        'roles': {'cycling': 0, 'stealing': 0, 'scoring': 0, 'feeding': 0, 'defending': 0, 'did_not_contribute': 0},
        'auto_success': 0,
        'auto_fail': 0,
        'endgame_success': 0,
        'endgame_fail': 0,
        'feeder': {'continuous': 0, 'stop_to_shoot': 0, 'dump': 0}
    })

    for entry in all_entries:
        data = entry.data

        # Handle individual team entries (check first since they also have match_id now)
        if entry.alliance_scouted and entry.alliance_scouted.startswith('team_'):
            team_num = entry.alliance_scouted.replace('team_', '')
            individual_data = data.get('individual', {})
            for team_key, team_data in individual_data.items():
                rating = team_data.get('overall_rating') or team_data.get('ranking')
                if rating:
                    team_rankings[team_num]['rankings'].append(rating)
                    team_rankings[team_num]['appearances'] += 1
                    if team_data.get('notes'):
                        team_rankings[team_num]['notes'].append(team_data['notes'])
                    # Roles are stored as flat keys directly on team_data
                    for role in ['cycling', 'stealing', 'scoring', 'feeding', 'defending', 'did_not_contribute']:
                        if team_data.get(role):
                            team_rankings[team_num]['roles'][role] += 1
        # Handle match-based entries (full alliance scouting)
        elif entry.match_id:
            for alliance in ['red', 'blue']:
                if alliance in data:
                    for team_key, team_data in data[alliance].items():
                        team_num = team_key.replace('team_', '')
                        rating = team_data.get('overall_rating') or team_data.get('ranking')
                        if rating:
                            team_rankings[team_num]['rankings'].append(rating)
                            team_rankings[team_num]['appearances'] += 1
                            if team_data.get('notes'):
                                team_rankings[team_num]['notes'].append(team_data['notes'])
                            # Roles are stored as flat keys directly on team_data
                            for role in ['cycling', 'stealing', 'scoring', 'feeding', 'defending', 'did_not_contribute']:
                                if team_data.get(role):
                                    team_rankings[team_num]['roles'][role] += 1
                            # Track auto climb
                            if team_data.get('auto_climb_result') == 'success':
                                team_rankings[team_num]['auto_success'] += 1
                            elif team_data.get('auto_climb_result') == 'fail':
                                team_rankings[team_num]['auto_fail'] += 1
                            # Track endgame climb
                            if team_data.get('endgame_climb_result') == 'success':
                                team_rankings[team_num]['endgame_success'] += 1
                            elif team_data.get('endgame_climb_result') == 'fail':
                                team_rankings[team_num]['endgame_fail'] += 1
                            # Track feeder types
                            for f in (team_data.get('feeder_type') or []):
                                if f in team_rankings[team_num]['feeder']:
                                    team_rankings[team_num]['feeder'][f] += 1
                                else:
                                    team_rankings[team_num]['feeder'][f] = team_rankings[team_num]['feeder'].get(f, 0) + 1

    # Calculate average rankings and prepare leaderboard data
    leaderboard = []
    for team_num, data in team_rankings.items():
        if data['rankings']:
            avg_ranking = sum(data['rankings']) / len(data['rankings'])
            leaderboard.append({
                'team_number': team_num,
                'average_ranking': round(avg_ranking, 2),
                'total_appearances': data['appearances'],
                'rankings': data['rankings'],
                'notes': data['notes'],
                'roles': data['roles'],
                'auto_success': data.get('auto_success', 0),
                'auto_fail': data.get('auto_fail', 0),
                'endgame_success': data.get('endgame_success', 0),
                'endgame_fail': data.get('endgame_fail', 0),
                'feeder': data.get('feeder', {})
            })

    # Sort by average overall rating (5 is best), highest first
    leaderboard.sort(key=lambda x: x['average_ranking'], reverse=True)

    return render_template('scouting/qualitative_leaderboard.html',
                         leaderboard=leaderboard,
                         total_teams=len(leaderboard),
                         events=events_with_data,
                         selected_event_id=selected_event_id,
                         **get_theme_context())


@bp.route('/qualitative/qr/<int:entry_id>')
@login_required
def qualitative_qr_code(entry_id):
    """Generate QR code for Qualitative scouting data"""
    entry = QualitativeScoutingData.query.filter_by(
        id=entry_id,
        scouting_team_number=current_user.scouting_team_number
    ).first_or_404()
    
    # Create QR code data with qualitative flag
    if entry.alliance_scouted and entry.alliance_scouted.startswith('team_'):
        # Individual team scouting
        data = entry.data
        qr_data = {
            'qualitative': True,
            'individual_team': True,
            'match_id': entry.match_id,
            'match_number': entry.match.match_number if entry.match else None,
            'match_type': entry.match.match_type if entry.match else None,
            'event_code': entry.match.event.code if entry.match and entry.match.event else '',
            'team_number': data.get('team_number', entry.alliance_scouted.replace('team_', '')),
            'alliance_scouted': entry.alliance_scouted,
            'scout_name': entry.scout_name,
            'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
            'team_data': entry.data
        }
    elif entry.match:
        # Match-based alliance scouting
        qr_data = {
            'qualitative': True,
            'match_id': entry.match_id,
            'match_number': entry.match.match_number,
            'match_type': entry.match.match_type,
            'event_code': entry.match.event.code if entry.match.event else '',
            'alliance_scouted': entry.alliance_scouted,
            'scout_name': entry.scout_name,
            'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
            'team_data': entry.data
        }
    else:
        # Fallback
        qr_data = {
            'qualitative': True,
            'scout_name': entry.scout_name,
            'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
            'team_data': entry.data
        }
    
    # Convert to JSON
    json_data = json.dumps(qr_data, separators=(',', ':'))
    
    # Generate QR code
    import qrcode
    from io import BytesIO
    import base64
    
    qr = qrcode.QRCode(version=None, box_size=10, border=4)
    qr.add_data(json_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_img = base64.b64encode(buffered.getvalue()).decode()
    
    return render_template('scouting/qualitative_qr.html',
                         entry=entry,
                         qr_img=qr_img,
                         qr_data=json.dumps(qr_data, indent=2),
                         **get_theme_context())
