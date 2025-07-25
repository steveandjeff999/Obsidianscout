from flask import Flask, render_template, flash, send_from_directory, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO, join_room
from flask_login import LoginManager
import os
import json
from datetime import datetime
from app.utils.config_manager import ConfigManager
import threading

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
login_manager = LoginManager()
config_manager = ConfigManager()

# Initialize file integrity monitor
from app.utils.file_integrity import FileIntegrityMonitor
file_integrity_monitor = FileIntegrityMonitor()

CHAT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'assistant_chat_history.json')
CHAT_HISTORY_LOCK = threading.Lock()

def load_chat_history():
    if not os.path.exists(CHAT_HISTORY_FILE):
        return []
    with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_chat_message(message):
    with CHAT_HISTORY_LOCK:
        history = load_chat_history()
        history.append(message)
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

# Socket.IO event handlers for assistant chat
@socketio.on('assistant_chat_message')
def handle_assistant_chat_message(data):
    user = None
    try:
        from flask_login import current_user
        user = current_user
    except Exception:
        pass
    sender = data.get('sender') or (user.username if user and hasattr(user, 'username') else 'Anonymous')
    recipient = data.get('recipient', 'assistant')
    text = data.get('text', '')
    timestamp = datetime.utcnow().isoformat()
    # If chatting with assistant, make it private per user
    if recipient == 'assistant':
        message = {'sender': sender, 'recipient': 'assistant', 'text': text, 'timestamp': timestamp, 'owner': sender}
        save_chat_message(message)
        socketio.emit('assistant_chat_message', message, room=sender)
        # Simple auto-reply from assistant
        reply = {'sender': 'assistant', 'recipient': sender, 'text': f"Hello {sender}, how can I help you?", 'timestamp': datetime.utcnow().isoformat(), 'owner': sender}
        save_chat_message(reply)
        socketio.emit('assistant_chat_message', reply, room=sender)
    else:
        message = {'sender': sender, 'recipient': recipient, 'text': text, 'timestamp': timestamp}
        save_chat_message(message)
        socketio.emit('assistant_chat_message', message, room=sender)
        socketio.emit('assistant_chat_message', message, room=recipient)

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
group_members = {}  # {group_name: set([usernames])}

@socketio.on('add_user_to_group')
def add_user_to_group(data):
    group = data.get('group')
    user = data.get('user')
    if group and user:
        group_members.setdefault(group, set()).add(user)
        socketio.emit('group_members_updated', {'group': group, 'members': list(group_members[group])}, room=group)

@socketio.on('remove_user_from_group')
def remove_user_from_group(data):
    group = data.get('group')
    user = data.get('user')
    if group and user and group in group_members:
        group_members[group].discard(user)
        socketio.emit('group_members_updated', {'group': group, 'members': list(group_members[group])}, room=group)

@socketio.on('join_group')
def join_group_room(data):
    group = data.get('group')
    user = None
    try:
        from flask_login import current_user
        user = current_user
    except Exception:
        pass
    username = user.username if user and hasattr(user, 'username') else None
    if group and username:
        join_room(group)
        group_members.setdefault(group, set()).add(username)
        socketio.emit('group_members_updated', {'group': group, 'members': list(group_members[group])}, room=group)

@socketio.on('leave_group')
def leave_group_room(data):
    group = data.get('group')
    user = None
    try:
        from flask_login import current_user
        user = current_user
    except Exception:
        pass
    username = user.username if user and hasattr(user, 'username') else None
    if group and username and group in group_members:
        from flask_socketio import leave_room
        leave_room(group)
        group_members[group].discard(username)
        socketio.emit('group_members_updated', {'group': group, 'members': list(group_members[group])}, room=group)

@socketio.on('group_chat_message')
def handle_group_chat_message(data):
    user = None
    try:
        from flask_login import current_user
        user = current_user
    except Exception:
        pass
    sender = data.get('sender') or (user.username if user and hasattr(user, 'username') else 'Anonymous')
    group = data.get('group')
    text = data.get('text', '')
    timestamp = datetime.utcnow().isoformat()
    # Only allow group members to send/receive
    if group and sender in group_members.get(group, set()):
        message = {'sender': sender, 'group': group, 'text': text, 'timestamp': timestamp}
        save_chat_message(message)
        socketio.emit('group_chat_message', message, room=group)

@socketio.on('connect')
def on_connect():
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            join_room(current_user.username)
    except Exception:
        pass

# Flask route to delete chat history (admin only)
def register_chat_history_routes(app):
    @app.route('/assistant/delete-chat-history', methods=['POST'])
    def delete_chat_history():
        from flask_login import current_user
        if not current_user.is_authenticated or not current_user.has_role('admin'):
            return jsonify({'success': False, 'message': 'Admin only'}), 403
        if os.path.exists(CHAT_HISTORY_FILE):
            os.remove(CHAT_HISTORY_FILE)
        return jsonify({'success': True, 'message': 'Chat history deleted'})

def create_app(test_config=None):
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    
    # Set default configuration
    app.config.from_mapping(
        SECRET_KEY='dev',
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'scouting.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
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
    except OSError:
        pass
    
    # Load game configuration from JSON file
    try:
        config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
        with open(config_path, 'r') as f:
            app.config['GAME_CONFIG'] = json.load(f)
            
            # Set API configuration based on game config
            if 'api_settings' in app.config['GAME_CONFIG']:
                api_settings = app.config['GAME_CONFIG']['api_settings']
                app.config['API_KEY'] = api_settings.get('auth_token', '')
                app.config['API_BASE_URL'] = api_settings.get('base_url', 'https://frc-api.firstinspires.org')
            
            # Set TBA API configuration
            if 'tba_api_settings' in app.config['GAME_CONFIG']:
                tba_settings = app.config['GAME_CONFIG']['tba_api_settings']
                app.config['TBA_API_KEY'] = tba_settings.get('auth_key', '')
            
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
    
    # Initialize database
    db.init_app(app)
    migrate.init_app(app, db)
    
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
    
    # Initialize ConfigManager
    config_manager.init_app(app)

    # Import and register blueprints
    from app.routes import main, teams, matches, scouting, data, graphs, events, alliances, auth, activity, assistant, integrity, pit_scouting, admin, themes
    
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
    app.register_blueprint(events.bp)
    app.register_blueprint(alliances.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(activity.activity_bp)
    app.register_blueprint(assistant.bp)
    app.register_blueprint(integrity.integrity_bp)
    
    # Register API test blueprint (admin only)
    from app.routes import api_test
    app.register_blueprint(api_test.bp)
    
    # Register admin blueprint
    app.register_blueprint(admin.bp)
    
    # Register themes blueprint
    app.register_blueprint(themes.bp)

    # Register chat history routes
    register_chat_history_routes(app)
    
    # Create database tables (only if they don't exist)
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print(f"Warning: Database tables may already exist: {e}")
    
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
        return dict(game_config=app.config.get('GAME_CONFIG', {}))
    
    # Add a context processor to make theme data available in all templates
    @app.context_processor
    def inject_theme_data():
        try:
            from app.utils.theme_manager import ThemeManager
            theme_manager = ThemeManager()
            theme = theme_manager.get_current_theme()
            return dict(
                current_theme=theme,
                current_theme_id=theme_manager.current_theme,
                theme_css_variables=theme_manager.get_theme_css_variables(),
                themes=theme_manager.get_available_themes()  # Ensure 'themes' is always available
            )
        except Exception as e:
            app.logger.error(f"Error loading theme data: {e}")
            return dict(current_theme={}, current_theme_id='default', theme_css_variables='', themes={})
    
    return app