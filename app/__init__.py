from flask import Flask, render_template, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_login import LoginManager
import os
import json
from datetime import datetime
from app.utils.config_manager import ConfigManager

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
login_manager = LoginManager()
config_manager = ConfigManager()

# Initialize file integrity monitor
from app.utils.file_integrity import FileIntegrityMonitor
file_integrity_monitor = FileIntegrityMonitor()

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
    from app.routes import main, teams, matches, scouting, data, visualization, graphs, events, alliances, auth, activity, assistant, integrity, pit_scouting, admin
    
    # Register template filters
    from app.utils import template_filters
    template_filters.init_app(app)
    
    app.register_blueprint(main.bp)
    app.register_blueprint(teams.bp)
    app.register_blueprint(matches.bp)
    app.register_blueprint(scouting.bp)
    app.register_blueprint(pit_scouting.bp)
    app.register_blueprint(data.bp)
    app.register_blueprint(visualization.bp)
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
    
    return app