from flask import Flask, render_template, flash, send_from_directory, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO, join_room
from flask_login import LoginManager
import os
import json
from datetime import datetime
from app.utils.config_manager import ConfigManager, get_current_game_config, load_game_config
import threading

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
        os.makedirs(CHAT_FOLDER, exist_ok=True)

def load_chat_history():
    ensure_chat_folder()
    if not os.path.exists(CHAT_HISTORY_FILE):
        return []
    with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_chat_message(message):
    with CHAT_HISTORY_LOCK:
        ensure_chat_folder()
        history = load_chat_history()
        history.append(message)
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

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
group_members = {}  # {group_name: set([usernames])}

@socketio.on('add_user_to_group')
def add_user_to_group(data):
    from app.utils.team_isolation import validate_user_in_same_team
    group = data.get('group')
    user = data.get('user')
    if group and user and validate_user_in_same_team(user):
        group_members.setdefault(group, set()).add(user)
        socketio.emit('group_members_updated', {'group': group, 'members': list(group_members[group])}, room=group)

@socketio.on('remove_user_from_group')
def remove_user_from_group(data):
    from app.utils.team_isolation import validate_user_in_same_team
    group = data.get('group')
    user = data.get('user')
    if group and user and group in group_members and validate_user_in_same_team(user):
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
    from app.utils.team_isolation import validate_user_in_same_team
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
    
    # Only allow group members to send/receive and ensure sender is in same team
    if group and sender in group_members.get(group, set()):
        # Validate all group members are in the same scouting team
        valid_members = set()
        for member in group_members[group]:
            if validate_user_in_same_team(member):
                valid_members.add(member)
        
        # Update group members to only include valid team members
        group_members[group] = valid_members
        
        if sender in valid_members:
            message = {'sender': sender, 'group': group, 'text': text, 'timestamp': timestamp}
            save_chat_message(message)
            socketio.emit('group_chat_message', message, room=group)

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
    
    # Set default configuration
    app.config.from_mapping(
        SECRET_KEY='dev',
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'scouting.db'),
        # Additional database bind for user accounts (stored separately)
        SQLALCHEMY_BINDS={
            'users': 'sqlite:///' + os.path.join(app.instance_path, 'users.db')
        },
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={
            'pool_pre_ping': True,
            'pool_recycle': 3600,
            'connect_args': {
                'timeout': 30,
                'check_same_thread': False,
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
    except OSError:
        pass
    
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
    
    # Initialize concurrent database manager
    concurrent_db_manager.init_app(app)
    
    # Initialize ConfigManager
    config_manager.init_app(app)
    
    # Initialize multi-server sync manager
    from app.utils.multi_server_sync import sync_manager
    sync_manager.init_app(app)
    
    # Initialize database change tracking for sync
    from app.utils.change_tracking import setup_change_tracking
    with app.app_context():
        setup_change_tracking()

    # Import and register blueprints
    from app.routes import main, teams, matches, scouting, data, graphs, events, alliances, auth, assistant, integrity, pit_scouting, themes, scouting_alliances, setup, search, db_admin, sync_api, sync_management
    
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
    app.register_blueprint(scouting_alliances.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(assistant.bp)
    app.register_blueprint(integrity.integrity_bp)
    app.register_blueprint(setup.bp)
    app.register_blueprint(search.bp)
    app.register_blueprint(db_admin.db_admin_bp)
    
    # Register sync routes and API
    app.register_blueprint(sync_api.sync_api)
    app.register_blueprint(sync_management.sync_routes)
    
    # Register real-time replication API
    from app.routes import realtime_api
    app.register_blueprint(realtime_api.realtime_api)
    
    # Register real-time replication management routes
    from app.routes import realtime_management
    app.register_blueprint(realtime_management.realtime_routes)
    
    # Register API test blueprint (admin only)
    from app.routes import api_test
    app.register_blueprint(api_test.bp)
    
    # Register themes blueprint
    app.register_blueprint(themes.bp)

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

    # Serve service worker at root path so tools (and PWABuilder) can fetch it at /sw.js
    @app.route('/sw.js')
    def service_worker():
        # Send the sw.js file from the static folder (typically app/static/sw.js)
        return send_from_directory(app.static_folder, 'sw.js')
    
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
        return dict(game_config=get_current_game_config())
    
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
        app.logger.info("✅ Real-time database replication enabled")
    except Exception as e:
        app.logger.error(f"❌ Failed to initialize real-time replication: {e}")
    
    # Initialize real-time file synchronization
    try:
        from app.utils.real_time_file_sync import setup_real_time_file_sync
        setup_real_time_file_sync(app)
        app.logger.info("✅ Real-time file synchronization enabled")
    except Exception as e:
        app.logger.error(f"❌ Failed to initialize real-time file sync: {e}")
    
    # Initialize catch-up synchronization system
    try:
        from app.utils.catchup_sync import catchup_sync_manager
        catchup_sync_manager.init_app(app)
        app.logger.info("✅ Catch-up synchronization system enabled")
        
        # Start catch-up scheduler
        from app.utils.catchup_scheduler import start_catchup_scheduler
        start_catchup_scheduler(app)
        app.logger.info("✅ Catch-up scheduler started")
    except Exception as e:
        app.logger.error(f"❌ Failed to initialize catch-up sync: {e}")

    return app