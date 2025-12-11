from flask import Flask, render_template, flash, send_from_directory, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO, join_room
from flask_login import LoginManager
import os
import json
from datetime import datetime, timezone
from app.utils.config_manager import ConfigManager, get_current_game_config, load_game_config
import threading
import re

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
# SocketIO configuration - will be updated based on server choice in run.py
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
login_manager = LoginManager()
config_manager = ConfigManager()

# Initialize file integrity monitor
from app.utils.file_integrity import FileIntegrityMonitor
file_integrity_monitor = FileIntegrityMonitor()

# Initialize concurrent database manager
from app.utils.database_manager import concurrent_db_manager

# Chat storage configuration
CHAT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'chat')
CHAT_HISTORY_FILE = os.path.join(CHAT_FOLDER, 'assistant_chat_history.json')
CHAT_HISTORY_LOCK = threading.Lock()

def ensure_chat_folder():
    """Ensure the chat folder exists"""
    if not os.path.exists(CHAT_FOLDER):
        try:
            os.makedirs(CHAT_FOLDER, exist_ok=True)
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not create chat folder at {CHAT_FOLDER}: {e}")
            # Fall back to using the app's instance path if available
            try:
                from flask import current_app
                alt_chat = os.path.join(current_app.instance_path, 'chat')
                os.makedirs(alt_chat, exist_ok=True)
                globals()['CHAT_FOLDER'] = alt_chat
                globals()['CHAT_HISTORY_FILE'] = os.path.join(alt_chat, 'assistant_chat_history.json')
                print(f"Using alternative chat folder: {alt_chat}")
            except Exception:
                pass


def normalize_username(username):
    """Normalize a username for deterministic filenames and room names.

    Normalization rules:
    - strip leading/trailing whitespace
    - collapse internal whitespace to single spaces
    - lowercase
    Returns a safe string suitable for filenames/room names.
    """
    try:
        s = str(username or '').strip()
        # collapse multiple whitespace to single spaces
        s = re.sub(r'\s+', ' ', s)
        return s.lower()
    except Exception:
        return str(username or '').lower()

def load_chat_history():
    ensure_chat_folder()
    if not os.path.exists(CHAT_HISTORY_FILE):
        return []
    with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_chat_history(history):
    """Save chat history to the main chat file"""
    with CHAT_HISTORY_LOCK:
        ensure_chat_folder()
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

def get_user_chat_file_path(user1, user2, team_number):
    """Get the file path for chat between two users"""
    ensure_chat_folder()
    
    # Create team directory if it doesn't exist
    team_dir = os.path.join(CHAT_FOLDER, 'users', str(team_number))
    os.makedirs(team_dir, exist_ok=True)
    
    # Normalize usernames to lowercase and create consistent filename regardless of message direction
    u1 = normalize_username(user1)
    u2 = normalize_username(user2)
    users = sorted([u1, u2])
    filename = f"{users[0]}_{users[1]}_chat_history.json"
    return os.path.join(team_dir, filename)

def load_user_chat_history(user1, user2, team_number):
    """Load chat history between two specific users"""
    file_path = get_user_chat_file_path(user1, user2, team_number)
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_user_chat_history(user1, user2, team_number, history):
    """Save chat history between two specific users"""
    # Ensure usernames normalized for path and write atomically to avoid partial writes
    file_path = get_user_chat_file_path(user1, user2, team_number)
    tmp_path = file_path + '.tmp'
    try:
        # Write to a temp file first then atomically replace
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        # Replace the target atomically
        os.replace(tmp_path, file_path)
    except Exception:
        # Fallback: try direct write
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

def get_assistant_chat_file_path(username, team_number):
    """Get the file path for assistant chat for a specific user"""
    ensure_chat_folder()
    
    # Create team directory if it doesn't exist
    team_dir = os.path.join(CHAT_FOLDER, 'users', str(team_number))
    os.makedirs(team_dir, exist_ok=True)
    # normalize username in filename to avoid case-sensitivity mismatches
    safe = normalize_username(username)
    filename = f"{safe}_assistant_chat_history.json"
    return os.path.join(team_dir, filename)

def get_group_chat_file_path(team_number, group_name='main'):
    """Get the file path for a group's chat history for a specific scouting team.

    By default groups are stored per-team under `instance/chat/groups/<team_number>/`.
    The default group name is 'main' for a general team-wide group chat.
    """
    ensure_chat_folder()
    team_dir = os.path.join(CHAT_FOLDER, 'groups', str(team_number))
    os.makedirs(team_dir, exist_ok=True)
    # normalize group name to lowercase and replace path separators
    safe_group = str(group_name).replace('/', '_').lower()
    filename = f"{safe_group}_group_chat_history.json"
    return os.path.join(team_dir, filename)

def load_group_chat_history(team_number, group_name='main'):
    file_path = get_group_chat_file_path(team_number, group_name)
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_group_chat_history(team_number, group_name, history):
    file_path = get_group_chat_file_path(team_number, group_name)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_assistant_chat_history(username, team_number):
    """Load assistant chat history for a specific user"""
    file_path = get_assistant_chat_file_path(username, team_number)
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_assistant_chat_history(username, team_number, history):
    """Save assistant chat history for a specific user"""
    file_path = get_assistant_chat_file_path(username, team_number)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def find_message_in_user_files(message_id, username, team_number):
    """Find a message across all user files where it might be stored"""
    import os
    import glob
    
    # Check the user's assistant file first
    # normalize username when checking assistant file path
    assistant_history = load_assistant_chat_history(username, team_number)
    for i, msg in enumerate(assistant_history):
        if msg.get('id') == message_id:
            return {
                'message': msg,
                'index': i,
                'history': assistant_history,
                'file_type': 'assistant',
                'file_path': get_assistant_chat_file_path(username, team_number),
                'save_func': lambda hist: save_assistant_chat_history(username, team_number, hist)
            }
    
    # Check all DM files involving this user
    team_dir = os.path.join(CHAT_FOLDER, 'users', str(team_number))
    if os.path.exists(team_dir):
        # Find all chat history files that include this username
        pattern = os.path.join(team_dir, f'*{str(username).lower()}*_chat_history.json')
        dm_files = glob.glob(pattern)
        
        for file_path in dm_files:
            if '_assistant_' not in file_path:  # Skip assistant files
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        dm_history = json.load(f)
                    
                    for i, msg in enumerate(dm_history):
                        if msg.get('id') == message_id:
                            # Extract users from filename to create save function
                            filename = os.path.basename(file_path).replace('_chat_history.json', '')
                            users = filename.split('_')
                            if len(users) >= 2:
                                # filenames are stored lowercased; map back to extracted lowercase names
                                user1, user2 = users[0], users[1]
                                return {
                                    'message': msg,
                                    'index': i,
                                    'history': dm_history,
                                    'file_type': 'dm',
                                    'file_path': file_path,
                                    'save_func': lambda hist, u1=user1, u2=user2: save_user_chat_history(u1, u2, team_number, hist)
                                }
                except Exception:
                    continue
    
    # Check main group chat file
    # Check per-team group chat files first
    try:
        team_dir = os.path.join(CHAT_FOLDER, 'groups', str(team_number))
        if os.path.exists(team_dir):
            import glob
            pattern = os.path.join(team_dir, '*_group_chat_history.json')
            for file_path in glob.glob(pattern):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        grp_history = json.load(f)
                    for i, msg in enumerate(grp_history):
                        if msg.get('id') == message_id:
                            group_name = os.path.basename(file_path).replace('_group_chat_history.json', '')
                            return {
                                'message': msg,
                                'index': i,
                                'history': grp_history,
                                'file_type': 'group',
                                'file_path': file_path,
                                'save_func': lambda hist, tn=team_number, gn=group_name: save_group_chat_history(tn, gn, hist)
                            }
                except Exception:
                    continue
    except Exception:
        pass

    # Fallback to legacy single assistant/main chat file
    history = load_chat_history()
    for i, msg in enumerate(history):
        if msg.get('id') == message_id:
            return {
                'message': msg,
                'index': i,
                'history': history,
                'file_type': 'group',
                'file_path': CHAT_HISTORY_FILE,
                'save_func': lambda hist: save_chat_history(hist)
            }
    
    return None

def save_chat_message(message):
    import uuid
    from flask_login import current_user
    
    with CHAT_HISTORY_LOCK:
        ensure_chat_folder()
        
        # Add unique ID to message if not present
        if 'id' not in message:
            message['id'] = str(uuid.uuid4())
        
        # Determine message type and save to appropriate file
        if message.get('recipient') == 'assistant' or message.get('sender') == 'assistant':
            # Assistant message - save to user-specific assistant file
            if current_user and current_user.is_authenticated:
                username = message.get('owner', current_user.username)
                team_number = getattr(current_user, 'scouting_team_number', 'no_team')
                
                history = load_assistant_chat_history(username, team_number)
                history.append(message)
                save_assistant_chat_history(username, team_number, history)
            else:
                # Fallback to main file if no user context
                history = load_chat_history()
                history.append(message)
                save_chat_history(history)
                
        elif message.get('recipient') and message.get('sender'):
            # DM message - save to user-specific DM file
            if current_user and current_user.is_authenticated:
                team_number = getattr(current_user, 'scouting_team_number', 'no_team')
                user1 = message['sender']
                user2 = message['recipient']
                
                history = load_user_chat_history(user1, user2, team_number)
                history.append(message)
                save_user_chat_history(user1, user2, team_number, history)
            else:
                # Fallback to main file
                history = load_chat_history()
                history.append(message)
                save_chat_history(history)
        else:
            # Group message or other - prefer per-team group storage if group specified
            # Group messages should include a 'group' key and ideally a team context
            group_name = message.get('group')
            team_number = message.get('team') if message.get('team') is not None else getattr(current_user, 'scouting_team_number', 'no_team')

            if group_name:
                # Save to per-team group chat file
                history = load_group_chat_history(team_number, group_name)
                history.append(message)
                save_group_chat_history(team_number, group_name, history)
            else:
                # Fallback to legacy main chat file
                history = load_chat_history()
                history.append(message)
                save_chat_history(history)

# Socket.IO event handlers for assistant chat
@socketio.on('assistant_chat_message')
def handle_assistant_chat_message(data):
    from app.utils.team_isolation import validate_user_in_same_team
    user = None
    try:
        from flask_login import current_user
        user = current_user
    except Exception:
        pass
    sender = data.get('sender') or (user.username if user and hasattr(user, 'username') else 'Anonymous')
    recipient = data.get('recipient', 'assistant')
    text = data.get('text', '')
    timestamp = datetime.now(timezone.utc).isoformat()
    # If chatting with assistant, make it private per user
    if recipient == 'assistant':
        message = {'sender': sender, 'recipient': 'assistant', 'text': text, 'timestamp': timestamp, 'owner': sender}
        save_chat_message(message)
        socketio.emit('assistant_chat_message', message, room=sender)
        # Simple auto-reply from assistant
        reply = {'sender': 'assistant', 'recipient': sender, 'text': f"Hello {sender}, how can I help you?", 'timestamp': datetime.now(timezone.utc).isoformat(), 'owner': sender}
        save_chat_message(reply)
        socketio.emit('assistant_chat_message', reply, room=sender)
    else:
        # Validate that recipient is in the same scouting team for user-to-user messages
        if validate_user_in_same_team(recipient):
            message = {'sender': sender, 'recipient': recipient, 'text': text, 'timestamp': timestamp}
            save_chat_message(message)
            socketio.emit('assistant_chat_message', message, room=sender)
            socketio.emit('assistant_chat_message', message, room=recipient)
        # If not in same team, silently ignore the message

@socketio.on('assistant_chat_history_request')
def handle_assistant_chat_history_request():
    user = None
    try:
        from flask_login import current_user
        user = current_user
    except Exception:
        pass
    username = user.username if user and hasattr(user, 'username') else None
    history = load_chat_history()
    # Only show assistant messages owned by this user
    filtered = []
    for msg in history:
        if msg.get('recipient') == 'assistant' and msg.get('owner') and msg.get('owner') != username:
            continue
        if msg.get('recipient') == username or msg.get('sender') == username or (msg.get('recipient') == 'assistant' and msg.get('owner') == username):
            filtered.append(msg)
    socketio.emit('assistant_chat_history', filtered)

# In-memory group membership (for demo; use DB for production)
# Structure: { team_number: { group_name: set([usernames]) } }
group_members = {}


def _ensure_group_set(team_number, group_name):
    team_key = str(team_number)
    if team_key not in group_members:
        group_members[team_key] = {}
    if group_name not in group_members[team_key]:
        group_members[team_key][group_name] = set()


def get_group_members_file_path(team_number, group_name='main'):
    """Return the path to the group's members JSON file for a team."""
    ensure_chat_folder()
    team_dir = os.path.join(CHAT_FOLDER, 'groups', str(team_number))
    os.makedirs(team_dir, exist_ok=True)
    safe_group = str(group_name).replace('/', '_')
    filename = f"{safe_group}_members.json"
    return os.path.join(team_dir, filename)


def load_group_members(team_number, group_name='main'):
    path = get_group_members_file_path(team_number, group_name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            # If stored as dict with keys, return list of usernames
            if isinstance(data, dict):
                return list(data.get('members', []))
    except Exception:
        pass
    return []


def save_group_members(team_number, group_name, members_list):
    path = get_group_members_file_path(team_number, group_name)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(list(members_list), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@socketio.on('add_user_to_group')
def add_user_to_group(data):
    """Add a user to an existing group (server-side tracking). Expects `group` and `username`."""
    try:
        group = data.get('group')
        username = data.get('username')
        from flask_login import current_user
        # Only allow adding users within the same scouting team
        if not group or not username:
            return
        if not hasattr(current_user, 'scouting_team_number'):
            return
        # Persisted members: load, modify, save
        team_number = getattr(current_user, 'scouting_team_number', 'no_team')
        members = set(load_group_members(team_number, group) or [])
        members.add(username)
        save_group_members(team_number, group, sorted(members))
        # Keep in-memory map in sync
        _ensure_group_set(team_number, group)
        group_members[str(team_number)][group] = set(members)
    except Exception:
        pass


@socketio.on('remove_user_from_group')
def remove_user_from_group(data):
    """Remove a user from a group (server-side tracking). Expects `group` and `username`."""
    try:
        group = data.get('group')
        username = data.get('username')
        from flask_login import current_user
        if not group or not username or not hasattr(current_user, 'scouting_team_number'):
            return
        team_number = getattr(current_user, 'scouting_team_number', 'no_team')
        members = set(load_group_members(team_number, group) or [])
        members.discard(username)
        save_group_members(team_number, group, sorted(members))
        _ensure_group_set(team_number, group)
        group_members[str(team_number)][group] = set(members)
    except Exception:
        pass


@socketio.on('join_group')
def join_group_room(data):
    """User joins a group room for real-time messaging. Expects `group`."""
    try:
        from flask_login import current_user
        group = data.get('group') or 'main'
        if not current_user or not getattr(current_user, 'is_authenticated', False):
            return
        # Only allow joining groups within the user's scouting team
        team_number = getattr(current_user, 'scouting_team_number', 'no_team')
        # Ensure member persisted and in-memory
        members = set(load_group_members(team_number, group) or [])
        members.add(current_user.username)
        save_group_members(team_number, group, sorted(members))
        _ensure_group_set(team_number, group)
        group_members[str(team_number)][group] = set(members)
        # Join a room unique to team+group
        room_name = f"group_{team_number}_{group}"
        join_room(room_name)
    except Exception:
        pass


@socketio.on('leave_group')
def leave_group_room(data):
    """User leaves a group room. Expects `group`."""
    try:
        from flask_login import current_user
        group = data.get('group') or 'main'
        if not current_user or not getattr(current_user, 'is_authenticated', False):
            return
        team_number = getattr(current_user, 'scouting_team_number', 'no_team')
        members = set(load_group_members(team_number, group) or [])
        members.discard(current_user.username)
        save_group_members(team_number, group, sorted(members))
        _ensure_group_set(team_number, group)
        group_members[str(team_number)][group] = set(members)
        # No explicit leave_room call here; SocketIO removes socket on disconnect.
    except Exception:
        pass


@socketio.on('group_chat_message')
def handle_group_chat_message(data):
    """Handle an incoming group message: validate team, persist to per-team group JSON, and emit to the group room."""
    try:
        from flask_login import current_user
        if not current_user or not getattr(current_user, 'is_authenticated', False):
            return
        group = data.get('group') or 'main'
        text = data.get('text')
        if text is None:
            return
        team_number = getattr(current_user, 'scouting_team_number', 'no_team')

        # Build message object
        import uuid
        message = {
            'id': str(uuid.uuid4()),
            'sender': current_user.username,
            'group': group,
            'team': team_number,
            'text': text,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'reactions': []
        }

        # Persist to per-team group history
        try:
            history = load_group_chat_history(team_number, group)
            history.append(message)
            save_group_chat_history(team_number, group, history)
        except Exception:
            # Fallback to global history
            try:
                hist = load_chat_history()
                hist.append(message)
                from app import save_chat_history
                save_chat_history(hist)
            except Exception:
                pass

        # Emit to the team+group room
        room_name = f"group_{team_number}_{group}"
        socketio.emit('group_message', message, room=room_name)
    except Exception:
        pass

@socketio.on('connect')
def on_connect():
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            # Join user-specific room
            join_room(current_user.username)
            
            # Join team-specific room for config updates
            if hasattr(current_user, 'scouting_team_number') and current_user.scouting_team_number:
                team_room = f'team_{current_user.scouting_team_number}'
                join_room(team_room)
                
                # Also join alliance room if user is in an alliance
                from app.models import ScoutingAllianceMember, TeamAllianceStatus
                alliance_member = ScoutingAllianceMember.query.filter_by(
                    team_number=current_user.scouting_team_number,
                    status='accepted'
                ).first()
                
                if alliance_member:
                    alliance_room = f'alliance_{alliance_member.alliance_id}'
                    join_room(alliance_room)
                    
    except Exception as e:
        print(f"Error in socket connect: {e}")
        pass

# Flask route to delete chat history (admin only)
def register_chat_history_routes(app):
    @app.route('/assistant/delete-chat-history', methods=['POST'])
    def delete_chat_history():
        from flask_login import current_user
        if not current_user.is_authenticated or not current_user.has_role('admin'):
            return jsonify({'success': False, 'message': 'Admin only'}), 403
        
        # Delete the chat history file
        if os.path.exists(CHAT_HISTORY_FILE):
            os.remove(CHAT_HISTORY_FILE)
        
        # Optionally, clean up other chat files if they exist
        if os.path.exists(CHAT_FOLDER):
            try:
                # Remove any other chat-related files in the folder
                for file in os.listdir(CHAT_FOLDER):
                    if file.endswith('.json') and 'chat' in file.lower():
                        file_path = os.path.join(CHAT_FOLDER, file)
                        os.remove(file_path)
            except Exception as e:
                print(f"Error cleaning chat folder: {e}")
        
        return jsonify({'success': True, 'message': 'Chat history deleted'})

def create_app(test_config=None):
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    # Record application start time for uptime diagnostics
    try:
        app.start_time = datetime.now(timezone.utc)
    except Exception:
        app.start_time = None
    
    # Set default configuration
    app.config.from_mapping(
        SECRET_KEY='dev',
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'scouting.db'),
        # Additional database bind for user accounts (stored separately)
        SQLALCHEMY_BINDS={
            'users': 'sqlite:///' + os.path.join(app.instance_path, 'users.db'),
            # Dedicated database for user-created pages/widgets
            'pages': 'sqlite:///' + os.path.join(app.instance_path, 'pages.db'),
            # Dedicated database for notifications and misc features
            'misc': 'sqlite:///' + os.path.join(app.instance_path, 'misc.db')
        },
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={
            'pool_pre_ping': True,
            'pool_recycle': 1800,        # Reduced to 30 minutes
            'pool_size': 5,              # Increased for sync workers (SQLite WAL mode supports multiple readers)
            'pool_timeout': 60,          # Increased timeout
            'max_overflow': 10,          # Allow overflow connections for background processes
            'connect_args': {
                'check_same_thread': False,
                'timeout': 60,           # SQLite connection timeout
                'isolation_level': None  # Autocommit mode for better performance
            }
        },
        UPLOAD_FOLDER=os.path.join(app.instance_path, 'uploads'),
        # Browser AI settings (defaults to None to use fallback)
        BROWSER_AI_API_KEY=None,
        BROWSER_AI_ENDPOINT="https://api.browserai.co/v1/chat/completions"
    )
    
    if test_config is None:
        # Load instance config if it exists
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load test config
        app.config.from_mapping(test_config)
    
    # Ensure instance and upload folders exist
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except (OSError, PermissionError) as e:
        # If directory creation fails, log the error but don't crash
        print(f"Warning: Could not create instance directory at {app.instance_path}: {e}")
        print("The application will attempt to continue, but some features may not work.")
        # Try to use an alternative path in the user's temp directory
        import tempfile
        try:
            alt_instance = os.path.join(tempfile.gettempdir(), 'obsidian_scout_instance')
            os.makedirs(alt_instance, exist_ok=True)
            app.instance_path = alt_instance
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(alt_instance, 'scouting.db')
            app.config['SQLALCHEMY_BINDS'] = {
                'users': 'sqlite:///' + os.path.join(alt_instance, 'users.db'),
                'pages': 'sqlite:///' + os.path.join(alt_instance, 'pages.db'),
                'misc': 'sqlite:///' + os.path.join(alt_instance, 'misc.db')
            }
            app.config['UPLOAD_FOLDER'] = os.path.join(alt_instance, 'uploads')
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            print(f"Using alternative instance path: {alt_instance}")
        except Exception as temp_error:
            print(f"Critical: Could not create alternative instance directory: {temp_error}")
            print("Application may not function correctly.")
    
    # Load game configuration from JSON file
    try:
        app.config['GAME_CONFIG'] = load_game_config()
            
        # Set API configuration based on game config
        if 'api_settings' in app.config['GAME_CONFIG']:
            api_settings = app.config['GAME_CONFIG']['api_settings']
            app.config['API_KEY'] = api_settings.get('auth_token', '')
            app.config['API_BASE_URL'] = api_settings.get('base_url', 'https://frc-api.firstinspires.org')

        # Set TBA API configuration
        if 'tba_api_settings' in app.config['GAME_CONFIG']:
            tba_settings = app.config['GAME_CONFIG']['tba_api_settings']
            app.config['TBA_API_KEY'] = tba_settings.get('auth_key', '')
            app.config['TBA_BASE_URL'] = tba_settings.get('base_url', 'https://www.thebluealliance.com/api/v3')
    except Exception as e:
        print(f"Error loading game configuration: {e}")
        app.config['GAME_CONFIG'] = {
            "season": datetime.now().year,
            "game_name": "Default Game",
            "alliance_size": 3,
            "match_types": ["Practice", "Qualification", "Playoff"],
            "scouting_stations": 6,
            "preferred_api_source": "first"
        }
    
    # Load top-level application config (app_config.json) and support auto-generation
    try:
        base = os.getcwd()
        cfg_path = os.path.join(base, 'app_config.json')
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    top_cfg = json.load(f) or {}
            except Exception:
                top_cfg = {}
        else:
            top_cfg = {}

        # If the JWT secret is present in top-level config, import it into app.config
        if top_cfg.get('JWT_SECRET_KEY'):
            app.config['JWT_SECRET_KEY'] = top_cfg.get('JWT_SECRET_KEY')

        # Support auto-generation flag: if true, generate a secure random secret,
        # write it into app_config.json and flip the flag to false so it only runs once.
        gen_flag = top_cfg.get('JWT_GENERATE_NEW')
        if gen_flag:
            import secrets as _secrets
            new_secret = _secrets.token_urlsafe(48)
            top_cfg['JWT_SECRET_KEY'] = new_secret
            top_cfg['JWT_GENERATE_NEW'] = False
            try:
                with open(cfg_path, 'w', encoding='utf-8') as wf:
                    json.dump(top_cfg, wf, ensure_ascii=False, indent=2)
                app.config['JWT_SECRET_KEY'] = new_secret
                try:
                    app.logger.info('Generated new JWT secret and updated app_config.json')
                except Exception:
                    pass
            except Exception as e:
                try:
                    app.logger.error(f'Failed to persist generated JWT secret to {cfg_path}: {e}')
                except Exception:
                    pass

        # If config didn't provide JWT_SECRET_KEY, warn so operator notices they should set it for production.
        if not app.config.get('JWT_SECRET_KEY'):
            try:
                app.logger.warning('JWT secret not set in app config. Using default placeholder; change for production')
            except Exception:
                pass
        # Import VAPID keys from top-level config if present
        if top_cfg.get('VAPID_PRIVATE_KEY') or top_cfg.get('VAPID_PUBLIC_KEY'):
            app.config['VAPID_PRIVATE_KEY'] = top_cfg.get('VAPID_PRIVATE_KEY')
            app.config['VAPID_PUBLIC_KEY'] = top_cfg.get('VAPID_PUBLIC_KEY')

        # Support auto-generation flag for VAPID keys: if true, always generate
        # fresh keys (replace existing) and persist them into app_config.json so
        # the flag can be cleared. This ensures operators can trigger rotation
        # by setting VAPID_GENERATE_NEW = true.
        vapid_gen = top_cfg.get('VAPID_GENERATE_NEW')
        if vapid_gen:
            try:
                from app.utils.push_notifications import get_vapid_keys

                # Force generation even if app.config contains keys
                try:
                    with app.app_context():
                        keys = get_vapid_keys(force_generate=True)
                except Exception as ctx_e:
                    try:
                        app.logger.error(f'Error invoking get_vapid_keys() inside app context: {ctx_e}')
                    except Exception:
                        pass
                    raise

                priv = keys.get('private_key') if isinstance(keys, dict) else None
                pub = keys.get('public_key') if isinstance(keys, dict) else None

                # Consider keys valid when non-empty and not redacted placeholders
                def _is_real_key(v):
                    return isinstance(v, str) and v and not v.strip().startswith('[REDACTED')

                if _is_real_key(priv) and _is_real_key(pub):
                    top_cfg['VAPID_PRIVATE_KEY'] = priv
                    top_cfg['VAPID_PUBLIC_KEY'] = pub
                    top_cfg['VAPID_GENERATE_NEW'] = False
                    try:
                        with open(cfg_path, 'w', encoding='utf-8') as wf:
                            json.dump(top_cfg, wf, ensure_ascii=False, indent=2)
                        app.config['VAPID_PRIVATE_KEY'] = priv
                        app.config['VAPID_PUBLIC_KEY'] = pub
                        try:
                            app.logger.info('Generated new VAPID keys and updated app_config.json')
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            app.logger.error(f'Failed to persist generated VAPID keys to {cfg_path}: {e}')
                        except Exception:
                            pass
                else:
                    try:
                        app.logger.warning('VAPID key generation returned empty keys; leaving VAPID_GENERATE_NEW = true')
                    except Exception:
                        pass
            except Exception as inner_e:
                try:
                    app.logger.error(f'Failed to auto-generate VAPID keys via helper: {inner_e}')
                except Exception:
                    pass

        # Warn if no VAPID keys configured
        if not app.config.get('VAPID_PRIVATE_KEY') or not app.config.get('VAPID_PUBLIC_KEY'):
            try:
                app.logger.info('VAPID keys not fully set in app config; runtime will fallback to instance/vapid_keys.json or generate keys when needed')
            except Exception:
                pass
    except Exception as e:
        try:
            app.logger.error(f'Error loading top-level app_config.json: {e}')
        except Exception:
            pass
    
    # Initialize database
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Apply SQLite performance optimizations
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        """Apply SQLite performance optimizations"""
        if 'sqlite' in str(dbapi_connection):
            cursor = dbapi_connection.cursor()
            # Performance optimizations for SQLite
            cursor.execute("PRAGMA journal_mode = WAL")      # Write-Ahead Logging
            cursor.execute("PRAGMA synchronous = NORMAL")    # Balance performance/safety
            cursor.execute("PRAGMA cache_size = -64000")     # 64MB cache
            cursor.execute("PRAGMA busy_timeout = 30000")    # 30 second timeout
            cursor.execute("PRAGMA temp_store = MEMORY")     # Memory for temp data
            cursor.execute("PRAGMA foreign_keys = ON")       # Enable FK constraints
            cursor.close()
    
    # Load AI configuration from file if it exists
    try:
        ai_config_path = os.path.join(app.instance_path, 'ai_config.json')
        if os.path.exists(ai_config_path):
            with open(ai_config_path, 'r') as f:
                ai_config = json.load(f)
                if 'endpoint' in ai_config:
                    app.config['BROWSER_AI_ENDPOINT'] = ai_config['endpoint']
                if 'api_key' in ai_config and ai_config['api_key']:
                    app.config['BROWSER_AI_API_KEY'] = ai_config['api_key']
    except Exception as e:
        print(f"Error loading AI configuration: {e}")
    
    # Initialize Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))
    
    # Initialize SocketIO
    socketio.init_app(app)
    
    # Initialize file integrity monitor
    file_integrity_monitor.init_app(app)
    
    # Initialize concurrent database manager
    concurrent_db_manager.init_app(app)

    # Initialize lightweight in-process firewall
    try:
        from app.security.firewall import Firewall
        fw = Firewall(app, socketio=socketio)
        app.logger.info(' Firewall initialized')
    except Exception as e:
        app.logger.error(f' Failed to initialize firewall: {e}')
    
    # Initialize ConfigManager
    config_manager.init_app(app)
    
    # Initialize multi-server sync manager - DISABLED to prevent database locking
    # from app.utils.multi_server_sync import sync_manager
    # sync_manager.init_app(app)
    
    # Universal sync system removed - keeping only normal user features

    # Import and register blueprints
    from app.routes import main, teams, matches, scouting, data, graphs, events, alliances, auth, assistant, integrity, pit_scouting, scouting_alliances, setup, search, db_admin, sync_api, update_monitor, notifications, mobile_api, simulations
    # Register new team trends route (lightweight analytics + prediction)
    try:
        from app.routes import team_trends
    except Exception:
        team_trends = None
    
    # Register template filters
    from app.utils import template_filters
    template_filters.init_app(app)
    
    app.register_blueprint(main.bp)
    app.register_blueprint(teams.bp)
    app.register_blueprint(matches.bp)
    app.register_blueprint(scouting.bp)
    app.register_blueprint(pit_scouting.bp)
    app.register_blueprint(data.bp)
    app.register_blueprint(graphs.bp)
    app.register_blueprint(simulations.bp)
    app.register_blueprint(events.bp)
    app.register_blueprint(alliances.bp)
    app.register_blueprint(scouting_alliances.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(assistant.bp)
    app.register_blueprint(integrity.integrity_bp)
    app.register_blueprint(setup.bp)
    app.register_blueprint(search.bp)
    app.register_blueprint(db_admin.db_admin_bp)
    app.register_blueprint(notifications.bp)
    app.register_blueprint(mobile_api.mobile_api)
    # Register team_trends blueprint if available
    if team_trends:
        try:
            app.register_blueprint(team_trends.bp)
        except Exception:
            pass
    
    # Register sync API (keeping normal sync API, removing superadmin management)
    app.register_blueprint(sync_api.sync_api)
    app.register_blueprint(update_monitor.update_monitor_bp)
    
    # Register real-time API (keeping normal realtime functionality, removing superadmin management)
    from app.routes import realtime_api
    app.register_blueprint(realtime_api.realtime_api)
    
    # Register API test blueprint (admin only)
    from app.routes import api_test
    app.register_blueprint(api_test.bp)
    
    # Note: themes blueprint removed - theme selection is handled via client-side dark/light toggle

    # Expose site notifications to templates (file-backed, no DB migrations)
    try:
        from app.utils.notifications import load_notifications
        @app.context_processor
        def inject_site_notifications():
            try:
                return {'site_notifications': load_notifications()}
            except Exception:
                return {'site_notifications': []}
    except Exception:
        pass

    # Register chat history routes
    register_chat_history_routes(app)

    # Inject combined all_events that includes both local and alliance entries
    @app.context_processor
    def inject_combined_all_events():
        try:
            from app.utils.team_isolation import get_combined_dropdown_events
            events = get_combined_dropdown_events()
            return {'all_events': events, 'events': events}
        except Exception:
            return {'all_events': []}

    # Serve service worker at root path so tools (and PWABuilder) can fetch it at /sw.js
    @app.route('/sw.js')
    def service_worker():
        # Prefer a root-level sw.js (project root) so service worker can be placed at repo root.
        # Fall back to static folder if root-level sw.js is not present.
        import os.path
        root_path = os.path.abspath(os.path.join(app.root_path, '..'))
        possible_root = os.path.join(root_path, 'sw.js')
        
        if os.path.exists(possible_root):
            response = send_from_directory(root_path, 'sw.js')
        else:
            # Check in static folder
            static_sw = os.path.join(app.static_folder, 'sw.js')
            if os.path.exists(static_sw):
                response = send_from_directory(app.static_folder, 'sw.js')
            else:
                # Last resort - return error
                from flask import abort
                abort(404)
        
        # Set proper MIME type for JavaScript
        response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        # Prevent caching of service worker to ensure updates are loaded
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # Minimal realtime status endpoint (client-side expects '/realtime/status')
    @app.route('/realtime/status')
    def realtime_status():
        try:
            # Import here to avoid circular imports during initialization
            from app.utils.real_time_replication import real_time_replicator
            return jsonify({
                'queue_size': real_time_replicator.get_queue_size(),
                'worker_running': real_time_replicator.is_worker_running()
            })
        except Exception:
            return jsonify({'queue_size': 0, 'worker_running': False})

    # Public PWA install page so browsers can fetch a login-free start URL.
    @app.route('/pwa')
    def pwa_install():
        # Serve a minimal static install page that links the manifest and registers the SW.
        return send_from_directory(app.static_folder, 'pwa.html')

    # Serve an easy preview for the offline fallback at /offline
    @app.route('/offline')
    def offline_preview():
        """Serve the offline fallback HTML so it can be previewed at /offline."""
        try:
            return send_from_directory(app.static_folder, 'offline.html')
        except Exception:
            from flask import abort
            abort(404)
    
    # Add global context processor for alliance status
    @app.context_processor
    def inject_alliance_status():
        """Make alliance status available to all templates"""
        try:
            from app.utils.config_manager import is_alliance_mode_active, get_active_alliance_info
            return {
                'is_alliance_mode_active': is_alliance_mode_active(),
                'active_alliance_info': get_active_alliance_info()
            }
        except Exception:
            # If there's any error (like during database init), return defaults
            return {
                'is_alliance_mode_active': False,
                'active_alliance_info': None
            }

    # Inject shared alliance event codes into all templates so UI can label alliance events
    @app.context_processor
    def inject_alliance_shared_event_codes():
        try:
            from app.utils.team_isolation import get_alliance_shared_event_codes
            shared = get_alliance_shared_event_codes() or []
            # Use uppercase codes for simple comparisons in templates
            upper_shared = [c.upper() for c in shared if isinstance(c, str)]
            return {'shared_event_codes': upper_shared}
        except Exception:
            return {'shared_event_codes': []}
    
    @app.context_processor
    def inject_csrf_token():
        """Make csrf_token function available to all templates"""
        import secrets
        def csrf_token():
            # Simple token generation for basic CSRF protection
            # In production, you might want to use Flask-WTF for proper CSRF protection
            return secrets.token_urlsafe(32)
        
        return {
            'csrf_token': csrf_token
        }
    
    # Create database tables (only if they don't exist)
    with app.app_context():
        try:
            # If a separate users bind is configured, create those tables first using the users engine.
            # Create user-related tables explicitly to avoid cross-bind foreign key ordering issues.
            if 'SQLALCHEMY_BINDS' in app.config and 'users' in app.config['SQLALCHEMY_BINDS']:
                try:
                    users_engine = db.get_engine(app, bind='users')
                    # Create user-related tables explicitly using their Table objects to
                    # ensure the referenced tables exist before creating association tables.
                    try:
                        from app.models import Role, User, user_roles
                        # Create tables in order: Role, User, association
                        Role.__table__.create(users_engine, checkfirst=True)
                        User.__table__.create(users_engine, checkfirst=True)
                        user_roles.create(users_engine, checkfirst=True)
                    except Exception as e:
                        # Fall back to metadata-based create_all if something unexpected occurs
                        users_table_names = ['role', 'user', 'user_roles']
                        users_tables = [t for name, t in db.metadata.tables.items() if name in users_table_names]
                        if users_tables:
                            db.metadata.create_all(bind=users_engine, tables=users_tables)
                except Exception as e:
                    app.logger.info('Could not create users bind tables via metadata.create_all; will attempt full create_all: %s', e)

            # If a separate pages bind is configured, create its tables explicitly.
            if 'SQLALCHEMY_BINDS' in app.config and 'pages' in app.config['SQLALCHEMY_BINDS']:
                try:
                    pages_engine = db.get_engine(app, bind='pages')
                    try:
                        from app.models import CustomPage
                        CustomPage.__table__.create(pages_engine, checkfirst=True)
                    except Exception as e:
                        # Fall back to metadata create_all for pages bind
                        pages_tables = [t for name, t in db.metadata.tables.items() if getattr(t, 'name', None) == 'custom_page']
                        if pages_tables:
                            db.metadata.create_all(bind=pages_engine, tables=pages_tables)
                except Exception as e:
                    app.logger.info('Could not create pages bind tables via metadata.create_all; continuing: %s', e)

            # Finally create all remaining tables on the default bind.
            # Creating per-table avoids SQLAlchemy attempting to sort cross-bind
            # dependencies which can raise NoReferencedTableError when tables
            # are split across multiple SQLite files.
            try:
                default_engine = db.get_engine(app)
                # Names of tables that belong to the users bind and were already created
                users_table_names = set(['role', 'user', 'user_roles'])

                # Create each table individually for the default bind, skipping user tables
                for table in db.metadata.sorted_tables:
                    if table.name in users_table_names:
                        continue
                    try:
                        table.create(default_engine, checkfirst=True)
                    except Exception as te:
                        # Log but continue creating other tables
                        app.logger.debug(f"Could not create table {table.name}: {te}")
            except Exception as e:
                print(f"Warning: Database tables may already exist or per-table create failed: {e}")
        except Exception as e:
            print(f"Warning: Database initialization encountered an error: {e}")
        # Ensure automatic migrations are attempted at app creation time so runtime code
        # that references newer columns won't fail when the app is started by a WSGI server.
        try:
            from app.utils.database_migrations import run_all_migrations
            run_all_migrations(db)
        except Exception as e:
            app.logger.warning(f"Failed to run automatic migrations during app init: {e}")
    
    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/500.html'), 500
    
    # Add a context processor to make integrity status available in templates
    @app.context_processor
    def inject_integrity_status():
        status = {}
        if hasattr(app, 'file_integrity_monitor'):
            monitor = app.file_integrity_monitor
            status = {
                'integrity_compromised': monitor.integrity_compromised,
                'warning_only_mode': monitor.warning_only_mode
            }
        return dict(integrity_status=status)
    
    # Add a context processor to make game_config available in all templates
    @app.context_processor
    def inject_game_config():
        # Also provide a helper to get a display label for a team number that
        # respects the current user's team display preference (99xx vs letter-suffix).
        def display_team_label(team_number, event_key=None):
            # Preference is now per-user and stored in browser localStorage. Server-side
            # code should not attempt to read or persist this preference. Always return
            # the canonical numeric team identifier for server-side rendering.
            try:
                return str(int(team_number))
            except Exception:
                return str(team_number)

        try:
            from app.utils.config_manager import get_effective_game_config
            effective_cfg = get_effective_game_config()
        except Exception:
            from app.utils.config_manager import get_current_game_config
            effective_cfg = get_current_game_config()
        return dict(game_config=effective_cfg, display_team_label=display_team_label)
    
    # Add a context processor to make theme data available in all templates
    @app.context_processor
    def inject_theme_data():
        # Keep minimal theme context needed for templates. We no longer provide full theme management server-side.
        try:
            # Provide basic values so templates that reference these keys won't error.
            return dict(current_theme={}, current_theme_id='light', theme_css_variables='', themes={})
        except Exception:
            return dict(current_theme={}, current_theme_id='light', theme_css_variables='', themes={})
    
    # Initialize real-time replication system
    try:
        from app.utils.real_time_replication import enable_real_time_replication, real_time_replicator
        # Provide the Flask app instance to the replicator so its worker can
        # use the existing app context instead of creating a new app.
        try:
            real_time_replicator.app = app
        except Exception:
            pass
        enable_real_time_replication()
        app.logger.info(" Real-time database replication enabled")
    except Exception as e:
        app.logger.error(f" Failed to initialize real-time replication: {e}")
    
    # Initialize real-time file synchronization
    try:
        from app.utils.real_time_file_sync import setup_real_time_file_sync
        setup_real_time_file_sync(app)
        app.logger.info(" Real-time file synchronization enabled")
    except Exception as e:
        app.logger.error(f" Failed to initialize real-time file sync: {e}")
    
    # Initialize catch-up synchronization system
    try:
        from app.utils.catchup_sync import catchup_sync_manager
        catchup_sync_manager.init_app(app)
        app.logger.info(" Catch-up synchronization system enabled")
        
        # Start catch-up scheduler
        from app.utils.catchup_scheduler import start_catchup_scheduler
        start_catchup_scheduler(app)
        app.logger.info(" Catch-up scheduler started")
    except Exception as e:
        app.logger.error(f" Failed to initialize catch-up sync: {e}")
    
    # Initialize API key system
    try:
        from app.utils.api_init import init_api_system
        init_api_system(app)
        app.logger.info(" API key system initialized")
    except Exception as e:
        app.logger.error(f" Failed to initialize API key system: {e}")

    # Protect direct access to avatar files under the static path.
    # Only the owner (signed in as that user) may fetch their avatar file.
    # The shared default.png remains publicly accessible to avoid broken UI.
    @app.before_request
    def protect_avatar_static_files():
        try:
            from flask_login import current_user
            import re
            path = request.path or ''
            if path.startswith('/static/img/avatars/'):
                filename = os.path.basename(path)
                if filename == 'default.png':
                    return None
                m = re.match(r'user_(\d+)\.[a-zA-Z0-9]+$', filename)
                if not m:
                    return jsonify({'success': False, 'error': 'Forbidden'}), 403
                try:
                    requested_id = int(m.group(1))
                except Exception:
                    return jsonify({'success': False, 'error': 'Forbidden'}), 403
                if not getattr(current_user, 'is_authenticated', False):
                    return jsonify({'success': False, 'error': 'Authentication required'}), 401
                if getattr(current_user, 'id', None) != requested_id:
                    return jsonify({'success': False, 'error': 'Forbidden'}), 403
        except Exception:
            try:
                return jsonify({'success': False, 'error': 'Forbidden'}), 403
            except Exception:
                pass

    return app