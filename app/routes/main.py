from flask import Blueprint, render_template, current_app, redirect, url_for, request, flash, send_from_directory
from flask_login import login_required, current_user
import json
import os
import copy
from functools import wraps
from flask_socketio import emit, join_room
from app import socketio
import markdown2
from app.utils.theme_manager import ThemeManager
from flask import request, jsonify
from app import load_chat_history
from app.models import User

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

    # Get game configuration from app config
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
    
    # Get matches filtered by the current event if available
    if current_event:
        matches = Match.query.filter_by(event_id=current_event.id).order_by(Match.match_type, Match.match_number).all()
    else:
        matches = []  # No matches if no current event is set
    
    scout_entries = ScoutingData.query.order_by(ScoutingData.timestamp.desc()).limit(5).all()
    
    return render_template('index.html', 
                          game_config=game_config,
                          teams=teams,
                          matches=matches,
                          scout_entries=scout_entries,
                          **get_theme_context())

@bp.route('/about')
@login_required
def about():
    """About page with info about the scouting system"""
    return render_template('about.html', **get_theme_context())

@bp.route('/config')
@login_required
def config():
    """View the current game configuration"""
    game_config = current_app.config['GAME_CONFIG']
    return render_template('config.html', game_config=game_config, **get_theme_context())

@bp.route('/config/edit')
def edit_config():
    """Edit the game configuration"""
    game_config = copy.deepcopy(current_app.config['GAME_CONFIG'])
    return render_template('config_edit.html', game_config=game_config, **get_theme_context())

@bp.route('/config/simple-edit')
def simple_edit_config():
    """Simple form-based configuration editor"""
    game_config = copy.deepcopy(current_app.config['GAME_CONFIG'])
    return render_template('config_simple_edit.html', game_config=game_config, **get_theme_context())

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
        
        # Get the path to the game_config.json file
        config_path = os.path.join(current_app.instance_path, '..', 'config', 'game_config.json')
        
        # Create a backup of the existing configuration
        backup_path = os.path.join(current_app.instance_path, '..', 'config', 'game_config_backup.json')
        with open(config_path, 'r') as f:
            current_config = f.read()
            with open(backup_path, 'w') as backup_file:
                backup_file.write(current_config)
        
        # Write the updated configuration to the file
        with open(config_path, 'w') as f:
            json.dump(updated_config, f, indent=2)
            
        # Update the configuration in the app
        current_app.config['GAME_CONFIG'] = updated_config
        
        flash('Configuration updated successfully! A backup was created at config/game_config_backup.json', 'success')
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
        # Get current config as base
        updated_config = copy.deepcopy(current_app.config['GAME_CONFIG'])
        
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
            
            # Find all elements for this period
            element_indices = set()
            for key in request.form.keys():
                if key.startswith(f'{period}_element_id_'):
                    index = key.split('_')[-1]
                    element_indices.add(int(index))
            
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
                    
                    # Add points if provided (for non-select types)
                    points = request.form.get(f'{period}_element_points_{index}')
                    if points and element_type != 'select':
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
                        option_idx = 0
                        while True:
                            opt_val = request.form.get(f'{period}_element_option_value_{index}_{option_idx}')
                            opt_label = request.form.get(f'{period}_element_option_label_{index}_{option_idx}')
                            opt_points = request.form.get(f'{period}_element_option_points_{index}_{option_idx}')
                            if opt_val is None:
                                break
                            options.append(opt_val)
                            try:
                                points_dict[opt_val] = float(opt_points) if opt_points is not None else 0
                            except ValueError:
                                points_dict[opt_val] = 0
                            option_idx += 1
                        if options:
                            element['options'] = options
                            element['points'] = points_dict
                    
                    elements.append(element)
            
            updated_config[period_key]['scoring_elements'] = elements
        
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
        config_path = os.path.join(current_app.instance_path, '..', 'config', 'game_config.json')
        
        # Create backup
        backup_path = os.path.join(current_app.instance_path, '..', 'config', 'game_config_backup.json')
        with open(config_path, 'r') as f:
            current_config = f.read()
            with open(backup_path, 'w') as backup_file:
                backup_file.write(current_config)
        
        # Write updated config
        with open(config_path, 'w') as f:
            json.dump(updated_config, f, indent=2)
        
        # Update app config
        current_app.config['GAME_CONFIG'] = updated_config
        
        flash('Configuration updated successfully! A backup was created at config/game_config_backup.json', 'success')
        return redirect(url_for('main.config'))
        
    except Exception as e:
        flash(f'Error updating configuration: {str(e)}', 'danger')
        return redirect(url_for('main.simple_edit_config'))

@bp.route('/help')
@login_required
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
    username = current_user.username
    other_user = request.args.get('user')
    history = load_chat_history()
    filtered = []
    for msg in history:
        if (
            (msg.get('sender') == username and msg.get('recipient') == other_user) or
            (msg.get('sender') == other_user and msg.get('recipient') == username)
        ):
            filtered.append(msg)
    return jsonify({'history': filtered})

@bp.route('/chat/group-history')
@login_required
def group_history():
    group = request.args.get('group')
    history = load_chat_history()
    filtered = [msg for msg in history if msg.get('group') == group]
    return jsonify({'history': filtered})

@bp.route('/chat/dm', methods=['POST'])
@login_required
def send_dm():
    from flask_login import current_user
    data = request.get_json()
    sender = current_user.username
    recipient = data.get('recipient')
    text = data.get('message')
    from app import save_chat_message
    import datetime
    message = {
        'sender': sender,
        'recipient': recipient,
        'text': text,
        'timestamp': datetime.datetime.utcnow().isoformat()
    }
    save_chat_message(message)
    # Emit real-time DM event to both sender and recipient
    from app import socketio
    socketio.emit('dm_message', message, room=sender)
    socketio.emit('dm_message', message, room=recipient)
    return {'success': True, 'message': 'Message sent.'}

@bp.route('/chat/state', methods=['GET', 'POST'])
@login_required
def chat_state():
    import os, json
    from flask_login import current_user
    state_file = os.path.join(current_app.instance_path, f'chat_state_{current_user.username}.json')
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
    state_file = os.path.join(current_app.instance_path, f'chat_state_{current_user.username}.json')
    state = {'joinedGroups': [], 'currentGroup': '', 'lastDmUser': '', 'unreadCount': 0}
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
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
    state_file = os.path.join(current_app.instance_path, f'chat_state_{current_user.username}.json')
    state = {'joinedGroups': [], 'currentGroup': '', 'lastDmUser': '', 'unreadCount': 0}
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    state['unreadCount'] = 0
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return {'success': True}

@bp.route('/users', methods=['GET'])
@login_required
def users_page():
    users = User.query.all()
    return render_template('users/index.html', users=users)

@bp.route('/users/<int:user_id>')
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('users/profile.html', user=user)

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