from flask import Blueprint, render_template, current_app, redirect, url_for, request, flash, send_from_directory, get_flashed_messages, jsonify
from flask_login import login_required, current_user
import json
import os
import copy
from functools import wraps
from flask_socketio import emit, join_room
from app import socketio
import markdown2
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import (get_current_game_config, get_effective_game_config, save_game_config, 
                                     get_available_default_configs, reset_config_to_default)
from flask import request, jsonify
from app import load_chat_history
from app.models import User
from datetime import datetime
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code, validate_user_in_same_team
)

connected_devices = {}

HELP_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'help')

def update_device_list():
    device_list = [
        {'id': k, 'status': v['status']} for k, v in connected_devices.items()
    ]
    socketio.emit('update_device_list', device_list)

@socketio.on('usb_device_connected')
def handle_usb_device_connected(data):
    device_id = data.get('device', 'Unknown Device')
    connected_devices[device_id] = {'status': 'Connected'}
    update_device_list()
    emit('usb_data_to_device', {'data': 'Device connected!'}, broadcast=True)

@socketio.on('usb_data')
def handle_usb_data(data):
    # Relay data to all dashboard clients (could be filtered by device if needed)
    emit('usb_data_to_device', {'data': data['data']}, broadcast=True)

def get_help_files():
    files = []
    for f in os.listdir(HELP_FOLDER):
        if f.lower().endswith('.md'):
            files.append(f)
    files.sort()
    return files

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme,
        'theme_css_variables': theme_manager.get_theme_css_variables()
    }

bp = Blueprint('main', __name__)

@bp.route('/')
@login_required
def index():
    """Main dashboard page"""
    from app.models import Team, Match, ScoutingData, Event
    
    # Block scouts from accessing the dashboard
    if current_user.has_role('scout') and not current_user.has_role('admin') and not current_user.has_role('analytics'):
        flash("You don't have permission to access the dashboard. Redirected to scouting page.", "warning")
        return redirect(url_for('scouting.index'))

    # Get game configuration from app config (use effective config for dashboard display)
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
    
    # Get matches filtered by the current event and scouting team
    if current_event:
        matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).order_by(Match.match_type, Match.match_number).all()
    else:
        matches = []  # No matches if no current event is set
    
    scout_entries = ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number).order_by(ScoutingData.timestamp.desc()).limit(5).all()
    
    # Get total count of scouting entries for the dashboard
    total_scout_entries = ScoutingData.query.filter_by(scouting_team_number=current_user.scouting_team_number).count()
    
    return render_template('index.html', 
                          game_config=game_config,
                          teams=teams,
                          matches=matches,
                          scout_entries=scout_entries,
                          total_scout_entries=total_scout_entries,
                          **get_theme_context())

@bp.route('/about')
@login_required
def about():
    """About page with info about the scouting system"""
    return render_template('about.html', **get_theme_context())

@bp.route('/sponsors')
@login_required
def sponsors():
    """Sponsors page to thank site sponsors"""
    return render_template('sponsors.html', **get_theme_context())

@bp.route('/config')
@login_required
def config():
    """View the current game configuration"""
    game_config = get_current_game_config()
    return render_template('config.html', game_config=game_config, **get_theme_context())

@bp.route('/config/edit')
def edit_config():
    """Edit the game configuration"""
    game_config = copy.deepcopy(get_current_game_config())
    default_configs = get_available_default_configs()
    return render_template('config_edit.html', game_config=game_config, default_configs=default_configs, **get_theme_context())

@bp.route('/config/simple-edit')
def simple_edit_config():
    """Simple form-based configuration editor"""
    game_config = copy.deepcopy(get_current_game_config())
    
    # Ensure all required sections exist with proper defaults
    game_config = ensure_complete_config_structure(game_config)
    
    default_configs = get_available_default_configs()
    return render_template('config_simple_edit_simplified.html', game_config=game_config, default_configs=default_configs, **get_theme_context())

def ensure_complete_config_structure(config):
    """Ensures the configuration has all required sections with proper defaults"""
    
    # Check if this is a completely empty/new config
    is_new_config = not config.get('game_name') and not any(
        config.get(period, {}).get('scoring_elements', []) 
        for period in ['auto_period', 'teleop_period', 'endgame_period']
    )
    
    # Default complete structure
    default_structure = {
        'game_name': config.get('game_name', ''),
        'season': config.get('season', 2024),
        'version': config.get('version', '1.0.0'),
        'alliance_size': config.get('alliance_size', 3),
        'scouting_stations': config.get('scouting_stations', 6),
        'current_event_code': config.get('current_event_code', ''),
        'match_types': config.get('match_types', ['Qualification']),
        'preferred_api_source': config.get('preferred_api_source', 'first'),
        'auto_period': {
            'duration_seconds': config.get('auto_period', {}).get('duration_seconds', 15),
            'scoring_elements': config.get('auto_period', {}).get('scoring_elements', [])
        },
        'teleop_period': {
            'duration_seconds': config.get('teleop_period', {}).get('duration_seconds', 135),
            'scoring_elements': config.get('teleop_period', {}).get('scoring_elements', [])
        },
        'endgame_period': {
            'duration_seconds': config.get('endgame_period', {}).get('duration_seconds', 30),
            'scoring_elements': config.get('endgame_period', {}).get('scoring_elements', [])
        },
        'game_pieces': config.get('game_pieces', []),
        'post_match': {
            'rating_elements': config.get('post_match', {}).get('rating_elements', []),
            'text_elements': config.get('post_match', {}).get('text_elements', [])
        },
        'api_settings': {
            'username': config.get('api_settings', {}).get('username', ''),
            'auth_token': config.get('api_settings', {}).get('auth_token', ''),
            'base_url': config.get('api_settings', {}).get('base_url', 'https://frc-api.firstinspires.org')
        },
        'tba_api_settings': {
            'auth_key': config.get('tba_api_settings', {}).get('auth_key', ''),
            'base_url': config.get('tba_api_settings', {}).get('base_url', 'https://www.thebluealliance.com/api/v3')
        }
    }
    
    # Only add data_analysis section if it already exists in the config (backwards compatibility)
    if 'data_analysis' in config:
        default_structure['data_analysis'] = {
            'key_metrics': config.get('data_analysis', {}).get('key_metrics', [])
        }
    
    # For completely new configs, add some helpful starter elements
    if is_new_config:
        default_structure['auto_period']['scoring_elements'] = [
            {
                'id': 'auto_speaker_notes',
                'perm_id': 'auto_speaker_notes',
                'name': 'Speaker Notes Scored',
                'type': 'counter',
                'default': 0,
                'points': 5
            }
        ]
        default_structure['teleop_period']['scoring_elements'] = [
            {
                'id': 'teleop_speaker_notes',
                'perm_id': 'teleop_speaker_notes',
                'name': 'Speaker Notes Scored',
                'type': 'counter',
                'default': 0,
                'points': 2
            },
            {
                'id': 'teleop_amp_notes',
                'perm_id': 'teleop_amp_notes', 
                'name': 'Amp Notes Scored',
                'type': 'counter',
                'default': 0,
                'points': 1
            }
        ]
        default_structure['endgame_period']['scoring_elements'] = [
            {
                'id': 'endgame_climb',
                'perm_id': 'endgame_climb',
                'name': 'Climb Success',
                'type': 'boolean',
                'default': False,
                'points': 3
            }
        ]
        default_structure['post_match']['rating_elements'] = [
            {
                'id': 'defense_rating',
                'name': 'Defense Rating',
                'type': 'rating',
                'min': 1,
                'max': 5,
                'default': 3
            }
        ]
        default_structure['post_match']['text_elements'] = [
            {
                'id': 'general_comments',
                'name': 'General Comments',
                'type': 'text',
                'multiline': True
            }
        ]
    
    # Preserve any additional fields that might exist in the original config
    for key, value in config.items():
        if key not in default_structure:
            default_structure[key] = value
    
    return default_structure

@bp.route('/config/reset', methods=['POST'])
def reset_config():
    """Reset configuration to a default template"""
    try:
        default_file = request.form.get('default_config')
        config_type = request.form.get('config_type', 'game')
        
        if not default_file:
            flash('No default configuration selected', 'error')
            return redirect(url_for('main.edit_config'))
        
        success, message = reset_config_to_default(default_file, config_type)
        
        if success:
            flash(message, 'success')
        else:
            flash(f'Error: {message}', 'error')
            
        return redirect(url_for('main.edit_config'))
        
    except Exception as e:
        flash(f'Error resetting configuration: {str(e)}', 'error')
        return redirect(url_for('main.edit_config'))

@bp.route('/config/save', methods=['POST'])
def save_config():
    """Save the updated game configuration"""
    try:
        # Check if this is coming from the simple editor
        if request.form.get('simple_edit') == 'true':
            return save_simple_config()
        
        # Get the JSON data from the form
        updated_config = json.loads(request.form.get('config_json', '{}'))
        
        # Validate the configuration structure (basic validation)
        required_keys = ['game_name', 'season', 'alliance_size', 'match_types', 
                        'auto_period', 'teleop_period', 'endgame_period', 'data_analysis']
        for key in required_keys:
            if key not in updated_config:
                flash(f"Missing required configuration key: {key}", "danger")
                return redirect(url_for('main.edit_config'))
        
        # Save the updated configuration
        if save_game_config(updated_config):
            # Update the configuration in the app
            current_app.config['GAME_CONFIG'] = updated_config
            flash('Configuration updated successfully!', 'success')
        else:
            flash('Error saving configuration.', 'danger')
        return redirect(url_for('main.config'))
    except json.JSONDecodeError:
        flash('Invalid JSON configuration', 'danger')
        return redirect(url_for('main.edit_config'))
    except Exception as e:
        flash(f'Error updating configuration: {str(e)}', 'danger')
        return redirect(url_for('main.edit_config'))

def save_simple_config():
    """Save configuration from the simple editor"""
    try:
        # --- DEBUG: dump incoming form keys for diagnosis ---
        try:
            debug_path = os.path.join(current_app.instance_path, 'config_save_debug.log')
            with open(debug_path, 'a', encoding='utf-8') as dbg:
                dbg.write(f"--- Save attempt at {datetime.utcnow().isoformat()} by {getattr(current_user, 'username', 'unknown')} ---\n")
                dbg.write("Form keys:\n")
                for k in request.form.keys():
                    dbg.write(f"  {k}\n")
                dbg.write("\n")
        except Exception:
            # Best-effort logging; don't block save on logging errors
            pass

        # Get current config as base and ensure it has complete structure
        updated_config = copy.deepcopy(get_current_game_config())
        updated_config = ensure_complete_config_structure(updated_config)
            
        # Keep an original snapshot so we can preserve existing data if the submitted form is incomplete
        original_config = copy.deepcopy(updated_config)

        # If the client provided a serialized simple_payload JSON, prefer it (more reliable)
        simple_payload = None
        try:
            payload_raw = request.form.get('simple_payload')
            if payload_raw:
                simple_payload = json.loads(payload_raw)
        except Exception:
            simple_payload = None
        # DEBUG: record whether we got a payload
        try:
            debug_path = os.path.join(current_app.instance_path, 'config_save_debug.log')
            with open(debug_path, 'a', encoding='utf-8') as dbg:
                dbg.write(f"simple_payload_present: {bool(simple_payload)}\n")
                if simple_payload:
                    dbg.write(f"simple_payload_keys: {list(simple_payload.keys())}\n")
        except Exception:
            pass
        
        # Update basic settings
        updated_config['game_name'] = request.form.get('game_name', '')
        updated_config['season'] = int(request.form.get('season', 2024))
        updated_config['version'] = request.form.get('version', '1.0.0')
        updated_config['alliance_size'] = int(request.form.get('alliance_size', 3))
        updated_config['scouting_stations'] = int(request.form.get('scouting_stations', 6))
        updated_config['current_event_code'] = request.form.get('current_event_code', '')
        
        # Update match types
        match_types = []
        for match_type in ['practice', 'qualification', 'playoff']:
            if request.form.get(f'match_type_{match_type}'):
                match_types.append(match_type.title())
        updated_config['match_types'] = match_types
        
        # Update period durations
        updated_config['auto_period']['duration_seconds'] = int(request.form.get('auto_duration', 15))
        updated_config['teleop_period']['duration_seconds'] = int(request.form.get('teleop_duration', 135))
        updated_config['endgame_period']['duration_seconds'] = int(request.form.get('endgame_duration', 30))
        
        # Update scoring elements for each period
        for period in ['auto', 'teleop', 'endgame']:
            period_key = f'{period}_period'
            elements = []

            # If client provided a serialized payload, use it to construct elements reliably
            if simple_payload and isinstance(simple_payload.get(period), list):
                for el in simple_payload.get(period, []):
                    try:
                        element = {
                            'id': el.get('id'),
                            'perm_id': el.get('perm_id') or el.get('id'),
                            'name': el.get('name'),
                            'type': el.get('type'),
                                    'default': parse_default_value(el.get('default', ''), el.get('type'))
                        }
                        
                        # Preserve display_in_predictions flag from payload when present
                        try:
                            if 'display_in_predictions' in el:
                                element['display_in_predictions'] = el.get('display_in_predictions')
                            else:
                                element['display_in_predictions'] = False
                        except Exception:
                            element['display_in_predictions'] = False
                        if element['type'] != 'select' and element['type'] != 'multiple_choice' and 'points' in el:
                            try:
                                element['points'] = float(el.get('points'))
                            except Exception:
                                element['points'] = 0
                        if el.get('game_piece_id'):
                            element['game_piece_id'] = el.get('game_piece_id')
                        if element['type'] == 'select':
                            opts = el.get('options') or []
                            pts = el.get('points') or {}
                            # sanitize
                            element['options'] = [str(o) for o in opts if o is not None]
                            element['points'] = {str(k): float(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '', 1).isdigit()) else 0 for k, v in (pts.items() if isinstance(pts, dict) else [])}
                        elif element['type'] == 'multiple_choice':
                            opts = el.get('options') or []
                            element['options'] = []
                            # Handle the new multiple choice format with individual point values
                            for opt in opts:
                                if isinstance(opt, dict) and 'name' in opt:
                                    element['options'].append({
                                        'name': str(opt['name']),
                                        'points': float(opt.get('points', 0))
                                    })
                                elif isinstance(opt, str):
                                    # Fallback for simple string options
                                    element['options'].append({
                                        'name': str(opt),
                                        'points': float(el.get('points', 0))
                                    })
                        elements.append(element)
                    except Exception:
                        # skip malformed element
                        pass
            else:
                # Fallback: parse flattened form fields (legacy)
                # Find all elements for this period
                element_indices = set()
                for key in request.form.keys():
                    if key.startswith(f'{period}_element_id_'):
                        index = key.split('_')[-1]
                        try:
                            element_indices.add(int(index))
                        except Exception:
                            pass

                for index in sorted(element_indices):
                    element_id = request.form.get(f'{period}_element_id_{index}')
                    element_name = request.form.get(f'{period}_element_name_{index}')
                    element_type = request.form.get(f'{period}_element_type_{index}')

                    if element_id and element_name and element_type:
                        element = {
                            'id': element_id,
                            'perm_id': element_id,
                            'name': element_name,
                            'type': element_type,
                            'default': parse_default_value(request.form.get(f'{period}_element_default_{index}', '0'), element_type)
                        }
                        # Read display_in_predictions checkbox for this element if present
                        try:
                            element['display_in_predictions'] = bool(request.form.get(f'{period}_element_display_predictions_{index}'))
                        except Exception:
                            element['display_in_predictions'] = False

                        # Add points if provided (for non-select and non-multiple-choice types)
                        points = request.form.get(f'{period}_element_points_{index}')
                        if points and element_type not in ['select', 'multiple_choice']:
                            try:
                                element['points'] = float(points)
                            except ValueError:
                                element['points'] = 0

                        # Add game piece ID if provided
                        game_piece_id = request.form.get(f'{period}_element_game_piece_{index}')
                        if game_piece_id:
                            element['game_piece_id'] = game_piece_id

                        # Handle select options with per-option points
                        if element_type == 'select':
                            options = []
                            points_dict = {}
                            # Collect option indices present in the submitted form for this element.
                            prefixes = [
                                f'{period}_element_option_value_{index}_',
                                f'{period}_element_option_label_{index}_',
                                f'{period}_element_option_points_{index}_'
                            ]
                            option_indices = set()
                            for k in request.form.keys():
                                for p in prefixes:
                                    if k.startswith(p):
                                        try:
                                            idx = int(k[len(p):])
                                            option_indices.add(idx)
                                        except Exception:
                                            pass

                            for opt_idx in sorted(option_indices):
                                opt_val = request.form.get(f'{period}_element_option_value_{index}_{opt_idx}')
                                opt_points = request.form.get(f'{period}_element_option_points_{index}_{opt_idx}')
                                if opt_val is None:
                                    continue
                                options.append(opt_val)
                                try:
                                    points_dict[opt_val] = float(opt_points) if opt_points is not None else 0
                                except ValueError:
                                    points_dict[opt_val] = 0

                            if options:
                                element['options'] = options
                                element['points'] = points_dict
                            else:
                                # Preserve previously-saved options/points for this element if present.
                                try:
                                    prev_elements = original_config.get(period_key, {}).get('scoring_elements', [])
                                    for prev in prev_elements:
                                        if prev.get('id') == element.get('id') or prev.get('perm_id') == element.get('id'):
                                            if prev.get('options'):
                                                element['options'] = prev.get('options')
                                            if prev.get('points') and isinstance(prev.get('points'), dict):
                                                element['points'] = prev.get('points')
                                            break
                                except Exception:
                                    pass
                        
                        # Handle multiple choice options with individual point values (fallback)
                        elif element_type == 'multiple_choice':
                            options = []
                            # Collect option indices present in the submitted form for this element
                            option_indices = set()
                            for k in request.form.keys():
                                if k.startswith(f'{period}_element_option_name_{index}_'):
                                    try:
                                        idx = int(k.split('_')[-1])
                                        option_indices.add(idx)
                                    except Exception:
                                        pass

                            for opt_idx in sorted(option_indices):
                                opt_name = request.form.get(f'{period}_element_option_name_{index}_{opt_idx}')
                                opt_points = request.form.get(f'{period}_element_option_points_{index}_{opt_idx}')
                                if opt_name and opt_name.strip():
                                    try:
                                        options.append({
                                            'name': opt_name.strip(),
                                            'points': float(opt_points) if opt_points is not None else 0
                                        })
                                    except ValueError:
                                        options.append({
                                            'name': opt_name.strip(),
                                            'points': 0
                                        })

                            if options:
                                element['options'] = options
                                element['default'] = options[0]['name'] if options else ''
                            else:
                                # Preserve previously-saved options for this element if present
                                try:
                                    prev_elements = original_config.get(period_key, {}).get('scoring_elements', [])
                                    for prev in prev_elements:
                                        if prev.get('id') == element.get('id') or prev.get('perm_id') == element.get('id'):
                                            if prev.get('options'):
                                                element['options'] = prev.get('options')
                                            if prev.get('default'):
                                                element['default'] = prev.get('default')
                                            break
                                except Exception:
                                    pass
                        
                        elements.append(element)
            
            # Merge with original elements to preserve fields that may be missing from the submitted form
            try:
                prev_elements = { (e.get('id'), e.get('perm_id')): e for e in original_config.get(period_key, {}).get('scoring_elements', []) }
                merged = []
                for el in elements:
                    merged_el = el.copy()
                    # Try matching by id or perm_id
                    match = None
                    for key in prev_elements:
                        prev = prev_elements[key]
                        if prev.get('id') == el.get('id') or prev.get('perm_id') == el.get('id') or prev.get('id') == el.get('perm_id'):
                            match = prev
                            break
                    if match:
                        # Preserve options and points if they are missing in the new element
                        if merged_el.get('type') == 'select':
                            if 'options' not in merged_el or not merged_el.get('options'):
                                if match.get('options'):
                                    merged_el['options'] = match.get('options')
                            if 'points' not in merged_el or not merged_el.get('points'):
                                if match.get('points'):
                                    merged_el['points'] = match.get('points')
                    merged.append(merged_el)
                # Debug: log previous and merged elements
                try:
                    debug_path = os.path.join(current_app.instance_path, 'config_save_debug.log')
                    with open(debug_path, 'a', encoding='utf-8') as dbg:
                        dbg.write(f"Previous {period_key} scoring_elements:\n")
                        dbg.write(json.dumps(original_config.get(period_key, {}).get('scoring_elements', []), indent=2))
                        dbg.write("\nMerged parsed elements:\n")
                        dbg.write(json.dumps(merged, indent=2))
                        dbg.write("\n---\n")
                except Exception:
                    pass
                updated_config[period_key]['scoring_elements'] = merged
            except Exception:
                updated_config[period_key]['scoring_elements'] = elements

        # --- DEBUG: log parsed endgame elements ---
        try:
            debug_path = os.path.join(current_app.instance_path, 'config_save_debug.log')
            with open(debug_path, 'a', encoding='utf-8') as dbg:
                dbg.write("Parsed endgame scoring_elements:\n")
                dbg.write(json.dumps(updated_config.get('endgame_period', {}).get('scoring_elements', []), indent=2))
                dbg.write("\n\n")
        except Exception:
            pass
        
        # Update game pieces
        game_pieces = []
        piece_indices = set()
        for key in request.form.keys():
            if key.startswith('game_piece_id_'):
                index = key.split('_')[-1]
                piece_indices.add(int(index))
        
        for index in sorted(piece_indices):
            piece_id = request.form.get(f'game_piece_id_{index}')
            piece_name = request.form.get(f'game_piece_name_{index}')
            
            if piece_id and piece_name:
                piece = {
                    'id': piece_id,
                    'name': piece_name,
                    'auto_points': float(request.form.get(f'game_piece_auto_points_{index}', 0)),
                    'teleop_points': float(request.form.get(f'game_piece_teleop_points_{index}', 0)),
                    'bonus_points': float(request.form.get(f'game_piece_bonus_points_{index}', 0))
                }
                game_pieces.append(piece)
        
        updated_config['game_pieces'] = game_pieces
        
        # Update post-match elements
        # Rating elements
        rating_elements = []
        rating_indices = set()
        for key in request.form.keys():
            if key.startswith('rating_element_id_'):
                index = key.split('_')[-1]
                rating_indices.add(int(index))
        
        for index in sorted(rating_indices):
            element_id = request.form.get(f'rating_element_id_{index}')
            element_name = request.form.get(f'rating_element_name_{index}')
            
            if element_id and element_name:
                element = {
                    'id': element_id,
                    'name': element_name,
                    'type': 'rating',
                    'min': int(request.form.get(f'rating_element_min_{index}', 1)),
                    'max': int(request.form.get(f'rating_element_max_{index}', 5)),
                    'default': int(request.form.get(f'rating_element_default_{index}', 3))
                }
                rating_elements.append(element)
        
        # Text elements
        text_elements = []
        text_indices = set()
        for key in request.form.keys():
            if key.startswith('text_element_id_'):
                index = key.split('_')[-1]
                text_indices.add(int(index))
        
        for index in sorted(text_indices):
            element_id = request.form.get(f'text_element_id_{index}')
            element_name = request.form.get(f'text_element_name_{index}')
            
            if element_id and element_name:
                element = {
                    'id': element_id,
                    'name': element_name,
                    'type': 'text',
                    'multiline': bool(request.form.get(f'text_element_multiline_{index}'))
                }
                text_elements.append(element)
        
        updated_config['post_match'] = {
            'rating_elements': rating_elements,
            'text_elements': text_elements
        }
        
        # Update key metrics
        key_metrics = []
        metric_indices = set()
        for key in request.form.keys():
            if key.startswith('metric_id_'):
                index = key.split('_')[-1]
                metric_indices.add(int(index))
        
        for index in sorted(metric_indices):
            metric_id = request.form.get(f'metric_id_{index}')
            metric_name = request.form.get(f'metric_name_{index}')
            
            if metric_id and metric_name:
                metric = {
                    'id': metric_id,
                    'name': metric_name,
                    'aggregate': request.form.get(f'metric_aggregate_{index}', 'average'),
                    'display_in_predictions': bool(request.form.get(f'metric_display_predictions_{index}')),
                    'auto_generated': bool(request.form.get(f'metric_auto_generated_{index}')),
                    'is_total_component': bool(request.form.get(f'metric_total_component_{index}'))
                }
                
                # Add formula if provided
                formula = request.form.get(f'metric_formula_{index}')
                if formula:
                    metric['formula'] = formula
                
                key_metrics.append(metric)
        
        updated_config['data_analysis'] = {
            'key_metrics': key_metrics
        }
        
        # Update preferred API source
        updated_config['preferred_api_source'] = request.form.get('preferred_api_source', 'first')
        
        # Update API settings if provided
        if request.form.get('api_username') or request.form.get('api_auth_token'):
            updated_config['api_settings'] = {
                'username': request.form.get('api_username', ''),
                'auth_token': request.form.get('api_auth_token', ''),
                'base_url': request.form.get('api_base_url', 'https://frc-api.firstinspires.org')
            }
        
        # Update TBA API settings if provided
        if request.form.get('tba_auth_key') or request.form.get('tba_base_url'):
            updated_config['tba_api_settings'] = {
                'auth_key': request.form.get('tba_auth_key', ''),
                'base_url': request.form.get('tba_base_url', 'https://www.thebluealliance.com/api/v3')
            }
        
        # Save the configuration
        if save_game_config(updated_config):
            # Update app config
            current_app.config['GAME_CONFIG'] = updated_config
            flash('Configuration updated successfully!', 'success')
        else:
            flash('Error saving configuration.', 'danger')
        return redirect(url_for('main.config'))
        
    except Exception as e:
        flash(f'Error updating configuration: {str(e)}', 'danger')
        return redirect(url_for('main.simple_edit_config'))

@bp.route('/help')
def help_page():
    files = get_help_files()
    selected = request.args.get('file')
    if not files:
        return render_template('help.html', files=[], content="No help files found.", selected=None, **get_theme_context())
    if not selected or selected not in files:
        selected = files[0]
    with open(os.path.join(HELP_FOLDER, selected), encoding='utf-8') as f:
        md_content = f.read()
    html_content = markdown2.markdown(md_content)
    return render_template('help.html', files=files, content=html_content, selected=selected, **get_theme_context())

@bp.route('/chat')
@login_required
def chat_page():
    return render_template('chat.html')

@bp.route('/chat/dm-history')
@login_required
def dm_history():
    from flask_login import current_user
    from app import load_user_chat_history
    username = current_user.username
    other_user = request.args.get('user')
    
    # Validate that the other user is in the same scouting team
    if not validate_user_in_same_team(other_user):
        return jsonify({'history': []})  # Return empty history for users from different teams
    
    team_number = getattr(current_user, 'scouting_team_number', 'no_team')
    history = load_user_chat_history(username, other_user, team_number)
    return jsonify({'history': history})

@bp.route('/chat/group-history')
@login_required
def group_history():
    from flask_login import current_user
    from app import load_group_chat_history

    group = request.args.get('group', 'main')
    team_number = getattr(current_user, 'scouting_team_number', 'no_team')
    history = []
    try:
        history = load_group_chat_history(team_number, group)
    except Exception:
        history = []
    return jsonify({'history': history})


@bp.route('/chat/group-members')
@login_required
def chat_group_members():
    """Return the list of members for a given group within the current user's scouting team."""
    from flask_login import current_user
    from app import load_group_members
    group = request.args.get('group', 'main')
    team_number = getattr(current_user, 'scouting_team_number', 'no_team')
    try:
        members = load_group_members(team_number, group) or []
    except Exception:
        members = []
    return jsonify({'members': members})

@bp.route('/chat/dm', methods=['POST'])
@login_required
def send_dm():
    from flask_login import current_user
    data = request.get_json()
    sender = current_user.username
    recipient = data.get('recipient')
    text = data.get('message')
    
    # Validate that recipient is in the same scouting team
    if not validate_user_in_same_team(recipient):
        return {'success': False, 'message': 'Cannot send message to user from different scouting team.'}, 403
    
    from app import save_chat_message
    import uuid
    message = {
        'id': str(uuid.uuid4()),
        'sender': sender,
        'recipient': recipient,
        'text': text,
        'timestamp': datetime.utcnow().isoformat(),
        'reactions': []
    }
    save_chat_message(message)
    # Emit real-time DM event to both sender and recipient
    from app import socketio
    socketio.emit('dm_message', message, room=sender)
    socketio.emit('dm_message', message, room=recipient)
    return {'success': True, 'message': 'Message sent.'}

@bp.route('/chat/edit-message', methods=['POST'])
@login_required
def edit_message():
    from flask_login import current_user
    import json
    data = request.get_json()
    message_id = data.get('message_id')
    new_text = data.get('text')
    
    if not message_id or not new_text:
        return {'success': False, 'message': 'Message ID and text required.'}, 400
    
    from app import find_message_in_user_files
    team_number = getattr(current_user, 'scouting_team_number', 'no_team')
    username = current_user.username
    
    # Find the message across all possible files
    message_info = find_message_in_user_files(message_id, username, team_number)
    
    if not message_info:
        return {'success': False, 'message': 'Message not found.'}, 404
    
    message = message_info['message']
    
    # Check if user owns this message (only user messages can be edited, not assistant responses)
    if message.get('sender') != username:
        return {'success': False, 'message': 'Cannot edit other users messages.'}, 403
    
    if message.get('sender') == 'assistant':
        return {'success': False, 'message': 'Cannot edit assistant messages.'}, 403
    
    # Update the message
    history = message_info['history']
    history[message_info['index']]['text'] = new_text
    history[message_info['index']]['edited'] = True
    history[message_info['index']]['edited_timestamp'] = datetime.utcnow().isoformat()
    
    # Save the updated history
    message_info['save_func'](history)
    
    # Emit socket event for real-time updates
    from app import socketio
    emit_data = {
        'message_id': message_id, 
        'text': new_text, 
        'reactions': message.get('reactions', [])
    }
    
    message_type = message_info['file_type']
    # Only emit updates for assistant and direct messages. Group messaging was removed.
    if message_type == 'assistant':
        socketio.emit('message_updated', emit_data, room=username)
    elif message_type == 'dm' and message.get('recipient'):
        # Emit to both sender and recipient for DM messages
        socketio.emit('message_updated', emit_data, room=message['sender'])
        socketio.emit('message_updated', emit_data, room=message['recipient'])
    
    return {'success': True, 'message': 'Message edited.'}

@bp.route('/chat/delete-message', methods=['POST'])
@login_required
def delete_message():
    from flask_login import current_user
    import json
    data = request.get_json()
    message_id = data.get('message_id')
    
    if not message_id:
        return {'success': False, 'message': 'Message ID required.'}, 400
    
    from app import find_message_in_user_files
    team_number = getattr(current_user, 'scouting_team_number', 'no_team')
    username = current_user.username
    
    # Find the message across all possible files
    message_info = find_message_in_user_files(message_id, username, team_number)
    
    if not message_info:
        return {'success': False, 'message': 'Message not found.'}, 404
    
    message = message_info['message']
    
    # Check if user owns this message (only user messages can be deleted, not assistant responses)
    if message.get('sender') != username:
        return {'success': False, 'message': 'Cannot delete other users messages.'}, 403
    
    if message.get('sender') == 'assistant':
        return {'success': False, 'message': 'Cannot delete assistant messages.'}, 403
    
    # Remove the message
    history = message_info['history']
    history.pop(message_info['index'])
    
    # Save the updated history
    message_info['save_func'](history)
    
    # Emit socket event for real-time updates
    from app import socketio
    emit_data = {'message_id': message_id}
    
    message_type = message_info['file_type']
    # Only emit deletions for assistant and direct messages. Group messaging was removed.
    if message_type == 'assistant':
        socketio.emit('message_deleted', emit_data, room=username)
    elif message_type == 'dm' and message.get('recipient'):
        # Emit to both sender and recipient for DM messages
        socketio.emit('message_deleted', emit_data, room=message['sender'])
        socketio.emit('message_deleted', emit_data, room=message['recipient'])
    
    return {'success': True, 'message': 'Message deleted.'}

@bp.route('/chat/react-message', methods=['POST'])
@login_required
def react_to_message():
    from flask_login import current_user
    import json
    data = request.get_json()
    message_id = data.get('message_id')
    emoji = data.get('emoji')
    
    if not message_id or not emoji:
        return {'success': False, 'message': 'Message ID and emoji required.'}, 400
    
    from app import find_message_in_user_files
    team_number = getattr(current_user, 'scouting_team_number', 'no_team')
    username = current_user.username
    
    # Find the message across all possible files
    message_info = find_message_in_user_files(message_id, username, team_number)
    
    if not message_info:
        return {'success': False, 'message': 'Message not found.'}, 404
    
    message = message_info['message']
    
    # Update reactions
    history = message_info['history']
    if 'reactions' not in history[message_info['index']]:
        history[message_info['index']]['reactions'] = []
    
    updated_reactions = toggle_reaction(history[message_info['index']]['reactions'], username, emoji)
    history[message_info['index']]['reactions'] = updated_reactions
    
    # Save the updated history
    # Also store a grouped summary on the message so it's available when loading history
    reaction_summary = group_reactions(updated_reactions)
    try:
        history[message_info['index']]['reactions_summary'] = reaction_summary
    except Exception:
        pass
    message_info['save_func'](history)
    
    
    # Emit socket event for real-time updates
    from app import socketio
    emit_data = {
        'message_id': message_id,
        'reactions': reaction_summary
    }
    
    # Emit reaction updates. For group messages, broadcast to the team+group room so others see updated counts.
    message_type = message_info['file_type']
    if message_type == 'assistant':
        socketio.emit('message_updated', emit_data, room=username)
    elif message_type == 'dm' and message.get('recipient'):
        # Emit to both sender and recipient for DM messages
        socketio.emit('message_updated', emit_data, room=message['sender'])
        socketio.emit('message_updated', emit_data, room=message['recipient'])
    elif message_type == 'group':
        # message should contain 'group' and 'team' properties
        grp = message.get('group') or message.get('group_name')
        team = message.get('team') or message.get('team_number')
        try:
            room_name = f"group_{team}_{grp}"
            socketio.emit('message_updated', emit_data, room=room_name)
        except Exception:
            # If we can't construct the room, fall back to no-op
            pass
    
    return {'success': True, 'reactions': reaction_summary}

def toggle_reaction(reactions, username, emoji):
    """Toggle a user's reaction with a specific emoji"""
    # Find existing reaction by this user with this emoji
    existing = next((r for r in reactions if r.get('user') == username and r.get('emoji') == emoji), None)
    
    if existing:
        # Remove existing reaction (toggle off)
        reactions.remove(existing)
    else:
        # Add new reaction
        reactions.append({
            'user': username,
            'emoji': emoji,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    return reactions

def group_reactions(reactions):
    """Group reactions by emoji and count them"""
    emoji_counts = {}
    for reaction in reactions:
        emoji = reaction.get('emoji')
        if emoji:
            if emoji not in emoji_counts:
                emoji_counts[emoji] = 0
            emoji_counts[emoji] += 1
    
    # Convert to list format expected by frontend
    return [{'emoji': emoji, 'count': count} for emoji, count in emoji_counts.items()]

def get_chat_folder():
    """Get the chat folder path and ensure it exists"""
    chat_folder = os.path.join(current_app.instance_path, 'chat')
    if not os.path.exists(chat_folder):
        os.makedirs(chat_folder, exist_ok=True)
    return chat_folder

def get_user_chat_state_file(username):
    """Get the path to a user's chat state file"""
    # Prefer to place user chat state files under instance/chat/users/<scouting_team_number>/
    try:
        team_segment = 'no_team'
        # Try to resolve the user's scouting team from the database first
        try:
            from app.models import User
            user = User.query.filter_by(username=username).first()
            if user and getattr(user, 'scouting_team_number', None):
                team_segment = str(user.scouting_team_number)
        except Exception:
            # Fallback to current_user if DB lookup is not available in this context
            try:
                from flask_login import current_user
                if current_user and getattr(current_user, 'scouting_team_number', None):
                    team_segment = str(current_user.scouting_team_number)
            except Exception:
                pass

        folder = os.path.join(current_app.instance_path, 'chat', 'users', team_segment)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f'chat_state_{username}.json')
    except Exception:
        # As a final fallback, use the original chat folder
        fallback = os.path.join(get_chat_folder(), f'chat_state_{username}.json')
        try:
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
        except Exception:
            pass
        return fallback

@bp.route('/chat/state', methods=['GET', 'POST'])
@login_required
def chat_state():
    import os, json
    from flask_login import current_user
    state_file = get_user_chat_state_file(current_user.username)
    if request.method == 'POST':
        data = request.get_json()
        # Ensure unreadCount is always present
        if 'unreadCount' not in data:
            data['unreadCount'] = 0
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {'success': True}
    else:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                if 'unreadCount' not in state:
                    state['unreadCount'] = 0
                return jsonify(state)
        else:
            return jsonify({'joinedGroups': [], 'currentGroup': '', 'lastDmUser': '', 'unreadCount': 0})

# Helper endpoint to increment unread count
@bp.route('/chat/increment-unread', methods=['POST'])
@login_required
def increment_unread():
    import os, json
    from flask_login import current_user
    state_file = get_user_chat_state_file(current_user.username)
    state = {'joinedGroups': [], 'currentGroup': '', 'lastDmUser': '', 'unreadCount': 0}
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    # If request provides a JSON body, merge lastSource info
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    if body and isinstance(body, dict) and 'lastSource' in body:
        state['lastSource'] = body.get('lastSource')
    # increment unread count
    state['unreadCount'] = state.get('unreadCount', 0) + 1
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return {'success': True, 'unreadCount': state['unreadCount']}

# Helper endpoint to reset unread count
@bp.route('/chat/reset-unread', methods=['POST'])
@login_required
def reset_unread():
    import os, json
    from flask_login import current_user
    state_file = get_user_chat_state_file(current_user.username)
    state = {'joinedGroups': [], 'currentGroup': '', 'lastDmUser': '', 'unreadCount': 0}
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    state['unreadCount'] = 0
    # Clear pointer to last source when user opens/clears chat
    if 'lastSource' in state:
        try:
            del state['lastSource']
        except Exception:
            state['lastSource'] = None
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return {'success': True}

@bp.route('/users', methods=['GET'])
@login_required
def users_page():
    users = User.query.filter_by(scouting_team_number=current_user.scouting_team_number).all()
    return render_template('users/index.html', users=users)

@bp.route('/users/<int:user_id>')
@login_required
def user_profile(user_id):
    user = User.query.filter_by(id=user_id, scouting_team_number=current_user.scouting_team_number).first_or_404()
    return render_template('users/profile.html', user=user)

@bp.route('/api/chat/users', methods=['GET'])
@login_required
def get_chat_users():
    """Get users from the same scouting team for chat purposes."""
    from app.utils.team_isolation import filter_users_by_scouting_team
    users = filter_users_by_scouting_team().all()
    # Exclude current user from the list
    users = [user for user in users if user.username != current_user.username]
    return jsonify([{'username': user.username, 'id': user.id} for user in users])

@bp.route('/admin/global-config', methods=['GET', 'POST'])
@login_required
def admin_global_config():
    """Admin panel for global config management and broadcasting"""
    # Require admin role
    if not current_user.has_role('admin'):
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'reload_all':
            try:
                # Trigger a global config reload for all users
                from app.utils.config_manager import get_effective_game_config, get_effective_pit_config
                from datetime import datetime
                
                # Get fresh config data
                fresh_config = {
                    'game_config': get_effective_game_config(),
                    'pit_config': get_effective_pit_config(),
                    'timestamp': datetime.now().isoformat()
                }
                
                # Broadcast to ALL users
                socketio.emit('global_config_changed', {
                    'type': 'admin_reload',
                    'effective_game_config': fresh_config['game_config'],
                    'effective_pit_config': fresh_config['pit_config'],
                    'timestamp': fresh_config['timestamp'],
                    'message': 'Configuration reloaded by administrator',
                    'force_reload': True
                })
                
                flash('Global configuration reload broadcast to all users.', 'success')
                
            except Exception as e:
                flash(f'Error broadcasting config reload: {str(e)}', 'error')
        
        elif action == 'broadcast_message':
            try:
                message = request.form.get('message', '').strip()
                if message:
                    # Broadcast custom message to all users
                    socketio.emit('global_config_changed', {
                        'type': 'admin_message',
                        'message': message,
                        'timestamp': datetime.now().isoformat(),
                        'show_notification': True
                    })
                    
                    flash(f'Message broadcast to all users: "{message}"', 'success')
                else:
                    flash('Message cannot be empty.', 'error')
                    
            except Exception as e:
                flash(f'Error broadcasting message: {str(e)}', 'error')
        
        return redirect(url_for('main.admin_global_config'))
    
    # GET request - show admin panel
    from app.utils.config_manager import get_effective_game_config, get_effective_pit_config, is_alliance_mode_active, get_active_alliance_info
    
    current_config = {
        'game_config': get_effective_game_config(),
        'pit_config': get_effective_pit_config(),
        'alliance_status': {
            'is_active': is_alliance_mode_active(),
            'alliance_info': get_active_alliance_info()
        }
    }
    
    return render_template('admin/global_config.html', 
                          current_config=current_config,
                          **get_theme_context())

@bp.route('/sync-monitor')
@login_required
def enhanced_sync_monitor():
    """Enhanced sync monitoring dashboard with reliability features"""
    return render_template('sync_monitor_enhanced.html', **get_theme_context())

@bp.route('/api/sync-status')
@login_required
def api_sync_status():
    """API endpoint to check sync status and statistics"""
    from app.models import Team, Match, Event, ScoutingData
    from app.utils.config_manager import get_effective_game_config
    
    game_config = get_effective_game_config()
    current_event_code = game_config.get('current_event_code')
    
    # Get basic statistics
    total_teams = filter_teams_by_scouting_team().count()
    total_matches = filter_matches_by_scouting_team().count()
    total_events = filter_events_by_scouting_team().count()
    
    # Get current event info
    current_event = None
    if current_event_code:
        current_event = get_event_by_code(current_event_code)
        if current_event:
            event_teams = filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).count()
            event_matches = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).count()
        else:
            event_teams = 0
            event_matches = 0
    else:
        event_teams = 0
        event_matches = 0
    
    # Get recent sync activity (last 10 minutes)
    from datetime import datetime, timedelta
    recent_time = datetime.utcnow() - timedelta(minutes=10)
    recent_teams = filter_teams_by_scouting_team().filter(Team.created_at >= recent_time).count() if hasattr(Team, 'created_at') else 0
    recent_matches = filter_matches_by_scouting_team().filter(Match.created_at >= recent_time).count() if hasattr(Match, 'created_at') else 0
    
    status = {
        'current_event_code': current_event_code,
        'current_event_name': current_event.name if current_event else None,
        'api_sync_enabled': True,  # Auto-sync is always enabled now
        'statistics': {
            'total_teams': total_teams,
            'total_matches': total_matches,
            'total_events': total_events,
            'current_event_teams': event_teams,
            'current_event_matches': event_matches,
            'recent_teams_added': recent_teams,
            'recent_matches_added': recent_matches
        },
        'sync_info': {
            'alliance_sync_interval': '30 seconds',
            'api_sync_interval': '3 minutes',
            'last_check': datetime.utcnow().isoformat()
        }
    }
    
    return jsonify(status)


@bp.route('/api/sync-event', methods=['POST'])
@login_required
def api_sync_event():
    """Trigger a combined teams + matches sync for the configured event.

    This endpoint calls the existing blueprint handlers for team and match
    syncs. It returns JSON with per-step results. Only authenticated users
    with admin or analytics roles should trigger this.
    """
    # Require admin or analytics role to prevent misuse
    if not (current_user.has_role('admin') or current_user.has_role('analytics')):
        return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403

    results = {
        'teams_sync': {'success': False, 'message': '', 'flashes': []},
        'matches_sync': {'success': False, 'message': '', 'flashes': []}
    }

    try:
        # Import inside function to avoid circular imports at module level
        from app.routes import teams as teams_bp
        # Call the teams sync view function directly. It will perform DB work
        # and flash messages; we ignore the redirect response but catch exceptions.
        try:
            # Drain any existing flashed messages so we only capture messages produced here
            try:
                _ = get_flashed_messages(with_categories=True)
            except Exception:
                pass

            teams_resp = teams_bp.sync_from_config()
            # Capture flashed messages (category, message) produced by the sync
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []

            results['teams_sync']['success'] = True
            results['teams_sync']['message'] = 'Teams sync attempted.'
            results['teams_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]
        except Exception as e:
            current_app.logger.exception('Teams sync failed')
            results['teams_sync']['success'] = False
            results['teams_sync']['message'] = str(e)
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []
            results['teams_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]

        # Matches
        from app.routes import matches as matches_bp
        try:
            # Drain any leftover flashed messages
            try:
                _ = get_flashed_messages(with_categories=True)
            except Exception:
                pass

            matches_resp = matches_bp.sync_from_config()
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []

            results['matches_sync']['success'] = True
            results['matches_sync']['message'] = 'Matches sync attempted.'
            results['matches_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]
        except Exception as e:
            current_app.logger.exception('Matches sync failed')
            results['matches_sync']['success'] = False
            results['matches_sync']['message'] = str(e)
            try:
                flashes = get_flashed_messages(with_categories=True)
            except Exception:
                flashes = []
            results['matches_sync']['flashes'] = [{'category': c, 'message': m} for c, m in flashes]

        # Determine overall success
        overall_success = results['teams_sync']['success'] or results['matches_sync']['success']

        return jsonify({'success': overall_success, 'results': results})

    except Exception as e:
        current_app.logger.exception('Combined sync endpoint failed')
        return jsonify({'success': False, 'error': str(e)}), 500

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

def parse_default_value(value, element_type):
    """Parse default value based on element type"""
    if element_type == 'boolean':
        return value.lower() in ('true', '1', 'yes', 'on') if isinstance(value, str) else bool(value)
    elif element_type == 'counter' or element_type == 'rating':
        try:
            return int(value) if value else 0
        except ValueError:
            return 0
    else:
        return value if value else ""

# Integrity routes have been moved to auth blueprint