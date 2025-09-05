
import os
import sys
import threading
import time
from app import create_app, socketio, db
from flask import redirect, url_for, request, flash
from sqlalchemy.exc import IntegrityError, OperationalError
from app.models import User, Role
from app.utils.database_init import initialize_database, check_database_health
# ============================================================================
# SERVER CONFIGURATION FLAG
# Set to True to use Waitress WSGI server, False to use Flask dev server with SSL
# ============================================================================
USE_WAITRESS = False  # Change this to False to use Flask development server with SSL

app = create_app()

# Setup auth redirect handler
@app.before_request
def check_first_run():
    # Check for restart trigger file (Flask reload mechanism)
    restart_trigger = os.path.join(os.path.dirname(__file__), '.flask_restart_trigger')
    if os.path.exists(restart_trigger):
        print("Flask restart trigger detected - server will reload")
        try:
            os.remove(restart_trigger)
        except:
            pass
    
    # Check for restart flag (fallback method)
    restart_flag = os.path.join(os.path.dirname(__file__), '.restart_flag')
    if os.path.exists(restart_flag):
        print("Restart flag detected - server was restarted after update")
        try:
            os.remove(restart_flag)
        except:
            pass
    
    # Check if database needs initialization
    if not User.query.first() and request.path != '/auth/login':
        # No users exist, database needs initialization
        flash('Database is being initialized. Please wait...', 'info')
        return redirect(url_for('auth.login'))

# Custom error handler for database issues
@app.errorhandler(IntegrityError)
def handle_integrity_error(error):
    if "UNIQUE constraint failed: user.email" in str(error):
        flash("Error: Email address must be unique. If you're trying to create a user without an email, " 
              "run 'python fix_emails.py' to fix database issues.", 'error')
    else:
        flash(f"Database integrity error: {str(error)}", 'error')
    return redirect(url_for('auth.manage_users'))

@app.errorhandler(OperationalError)
def handle_operational_error(error):
    flash(f"Database error: {str(error)}", 'error')
    return redirect(url_for('main.index'))

if __name__ == '__main__':
    # Determine if running in a production environment (like Render)
    # Render sets the 'RENDER' environment variable
    IS_PRODUCTION = 'RENDER' in os.environ

    # Get port from environment variables, fallback to 5000 for local dev
    port = int(os.environ.get('PORT', 8080))

    # Initialize database first
    print("Starting FRC Scouting Platform...")
    with app.app_context():
        try:
            # Check if database needs initialization
            if not check_database_health():
                print("Database needs initialization...")
                initialize_database()
            else:
                print("Database is healthy and ready.")
        except Exception as e:
            print(f"Database initialization error: {e}")
            print("Attempting to initialize database...")
            initialize_database()
        
        # Clear old failed login attempts on startup (especially important after updates)
        try:
            from app.models import LoginAttempt, db
            from datetime import datetime, timedelta
            
            # Clear failed login attempts older than 5 minutes on startup
            startup_cutoff = datetime.utcnow() - timedelta(minutes=5)
            startup_deleted = LoginAttempt.query.filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time < startup_cutoff
            ).delete()
            
            if startup_deleted > 0:
                db.session.commit()
                print(f"Startup cleanup: Cleared {startup_deleted} old failed login attempts")
            
        except Exception as e:
            print(f"Warning: Could not perform startup failed login cleanup: {e}")
        
        # Clear old failed login attempts on startup (especially important after updates)
        try:
            from app.models import LoginAttempt, db
            from datetime import datetime, timedelta
            
            # Clear failed login attempts older than 5 minutes on startup
            startup_cutoff = datetime.utcnow() - timedelta(minutes=5)
            startup_deleted = LoginAttempt.query.filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time < startup_cutoff
            ).delete()
            
            if startup_deleted > 0:
                db.session.commit()
                print(f"Startup cleanup: Cleared {startup_deleted} old failed login attempts")
            
        except Exception as e:
            print(f"Warning: Could not perform startup failed login cleanup: {e}")
        
        # Auto-create superadmin if it doesn't exist
        try:
            superadmin_user = User.query.filter_by(username='superadmin').first()
            if not superadmin_user:
                print("Creating superadmin account...")
                
                # Get or create superadmin role
                superadmin_role = Role.query.filter_by(name='superadmin').first()
                if not superadmin_role:
                    superadmin_role = Role(name='superadmin', description='Super Administrator with database access')
                    db.session.add(superadmin_role)
                
                # Create superadmin user
                superadmin_user = User(
                    username='superadmin',
                    scouting_team_number=0,
                    must_change_password=False,
                    is_active=True
                )
                superadmin_user.set_password('password') 
                superadmin_user.roles.append(superadmin_role)
                db.session.add(superadmin_user)
                db.session.commit()
                
                print("✅ SuperAdmin account created successfully!")
                print("   Username: superadmin")
                print("   Password: password")
                print("   Team Number: 0")
                print("   Must Change Password: True")
            else:
                print("SuperAdmin account already exists.")
        except Exception as e:
            print(f"Error creating superadmin account: {e}")
            db.session.rollback()
    
    # Start periodic alliance sync thread
    def periodic_sync_worker():
        """Background thread for periodic alliance synchronization"""
        while True:
            try:
                time.sleep(30)  # Wait 30 seconds
                # Import here to avoid circular imports
                with app.app_context():
                    from app.routes.scouting_alliances import perform_periodic_alliance_sync
                    perform_periodic_alliance_sync()
            except Exception as e:
                print(f"Error in periodic sync worker: {str(e)}")
                time.sleep(30)  # Continue after error

    # Start periodic API data sync thread
    def api_data_sync_worker():
        """Background thread for periodic API data synchronization"""
        while True:
            try:
                time.sleep(180)  # Wait 3 minutes (180 seconds)
                print("Starting periodic API data sync...")
                
                # Import here to avoid circular imports
                from app.utils.config_manager import get_effective_game_config
                from app.utils.api_utils import get_teams_dual_api, get_matches_dual_api
                from app.models import Team, Match, Event, db
                from app.utils.team_isolation import get_event_by_code, assign_scouting_team_to_model, filter_teams_by_scouting_team, filter_matches_by_scouting_team
                
                with app.app_context():
                    try:
                        # Get current event from config
                        game_config = get_effective_game_config()
                        event_code = game_config.get('current_event_code')
                        
                        if not event_code:
                            print("No event code configured, skipping API sync")
                            continue
                        
                        # Get or create event
                        event = get_event_by_code(event_code)
                        if not event:
                            print(f"Event {event_code} not found in database, skipping API sync")
                            continue
                        
                        # Sync teams
                        try:
                            team_data_list = get_teams_dual_api(event_code)
                            teams_added = 0
                            teams_updated = 0
                            
                            for team_data in team_data_list:
                                if not team_data or not team_data.get('team_number'):
                                    continue
                                
                                team_number = team_data.get('team_number')
                                team = filter_teams_by_scouting_team().filter(Team.team_number == team_number).first()
                                
                                if team:
                                    # Update existing team
                                    team.team_name = team_data.get('team_name', team.team_name)
                                    team.location = team_data.get('location', team.location)
                                    teams_updated += 1
                                else:
                                    # Add new team
                                    team = Team(**team_data)
                                    assign_scouting_team_to_model(team)
                                    db.session.add(team)
                                    teams_added += 1
                                
                                # Associate with event if not already associated
                                if event not in team.events:
                                    team.events.append(event)
                            
                            print(f"Teams sync: {teams_added} added, {teams_updated} updated")
                        except Exception as e:
                            print(f"Error syncing teams: {str(e)}")
                        
                        # Sync matches
                        try:
                            match_data_list = get_matches_dual_api(event_code)
                            matches_added = 0
                            matches_updated = 0
                            
                            for match_data in match_data_list:
                                if not match_data:
                                    continue
                                
                                match_data['event_id'] = event.id
                                match_number = match_data.get('match_number')
                                match_type = match_data.get('match_type')
                                
                                if not match_number or not match_type:
                                    continue
                                
                                match = filter_matches_by_scouting_team().filter(
                                    Match.event_id == event.id,
                                    Match.match_number == match_number,
                                    Match.match_type == match_type
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
                                    assign_scouting_team_to_model(match)
                                    db.session.add(match)
                                    matches_added += 1
                            
                            print(f"Matches sync: {matches_added} added, {matches_updated} updated")
                        except Exception as e:
                            print(f"Error syncing matches: {str(e)}")
                        
                        # Commit all changes
                        db.session.commit()
                        print("API data sync completed successfully")
                        
                    except Exception as e:
                        print(f"Error in API sync: {str(e)}")
                        db.session.rollback()
                        
            except Exception as e:
                print(f"Error in API data sync worker: {str(e)}")
                time.sleep(180)  # Continue after error
    
    # Start security maintenance worker
    def security_maintenance_worker():
        """Background thread for security maintenance tasks"""
        while True:
            try:
                time.sleep(3600)  # Wait 1 hour (3600 seconds)
                print("Starting security maintenance...")
                
                with app.app_context():
                    try:
                        # Security maintenance tasks can be added here if needed
                        print("Security maintenance completed")
                        
                    except Exception as e:
                        print(f"Error in security maintenance: {str(e)}")
                        
            except Exception as e:
                print(f"Error in security maintenance worker: {str(e)}")
                time.sleep(3600)  # Continue after error
    
    # Start the periodic sync threads as daemon threads
    alliance_sync_thread = threading.Thread(target=periodic_sync_worker, daemon=True)
    alliance_sync_thread.start()
    print("Started periodic alliance sync thread (30-second intervals)")
    
    api_sync_thread = threading.Thread(target=api_data_sync_worker, daemon=True)
    api_sync_thread.start()
    print("Started periodic API data sync thread (3-minute intervals)")
    
    security_maintenance_thread = threading.Thread(target=security_maintenance_worker, daemon=True)
    security_maintenance_thread.start()
    print("Started security maintenance thread (1-hour intervals)")
    
    # Start multi-server sync services
    try:
        from app.utils.multi_server_sync import sync_manager
        sync_manager.start_sync_services()
        print("Started multi-server sync services")
    except Exception as e:
        print(f"Warning: Could not start sync services: {e}")
    
    # Start real-time file sync
    try:
        from app.utils.real_time_file_sync import setup_real_time_file_sync
        with app.app_context():
            setup_real_time_file_sync(app)
        print("Started real-time file synchronization")
    except Exception as e:
        print(f"Warning: Could not start real-time file sync: {e}")
    
    # Configure SocketIO based on server choice
    if USE_WAITRESS:
        # Configure SocketIO for Waitress compatibility
        socketio.init_app(app, 
                         cors_allowed_origins="*",
                         transports=['polling'],
                         logger=False,
                         engineio_logger=False)
        print("Note: For SSL/HTTPS support, configure a reverse proxy (nginx, Apache, etc.)")
        print("      Waitress serves HTTP only, which is recommended for production behind a proxy")
    else:
        # Configure SocketIO for Flask development server (supports WebSockets)
        socketio.init_app(app,
                         cors_allowed_origins="*",
                         transports=['websocket', 'polling'])

    try:
        if USE_WAITRESS:
            print(f"🚀 Starting server with Waitress WSGI server on port {port}...")
            print("   ✅ Production-ready server")
            print("   ✅ SocketIO polling mode for compatibility")
            
            # Always use Waitress for serving
            from waitress import serve
            serve(
                app,
                host='0.0.0.0',
                port=port,
                threads=8,  # Increased threads for better performance
                connection_limit=1000,
                cleanup_interval=30,
                channel_timeout=120,
                expose_tracebacks=not IS_PRODUCTION,
                ident='FRC-Scouting-Platform',
                asyncore_use_poll=True,  # Better I/O handling
                send_bytes=65536  # Larger send buffer
            )
        else:
            # Use Flask development server with SSL support
            use_ssl = not IS_PRODUCTION
            ssl_context = None

            if use_ssl:
                cert_file = os.path.join(os.path.dirname(__file__), 'ssl', 'cert.pem')
                key_file = os.path.join(os.path.dirname(__file__), 'ssl', 'key.pem')

                if os.path.exists(cert_file) and os.path.exists(key_file):
                    ssl_context = (cert_file, key_file)
                else:
                    # Create directory for SSL certificates if it doesn't exist
                    ssl_dir = os.path.join(os.path.dirname(__file__), 'ssl')
                    if not os.path.exists(ssl_dir):
                        os.makedirs(ssl_dir)
                        
                    print("SSL certificates not found. Generating self-signed certificates for local development...")
                    try:
                        from OpenSSL import crypto
                        
                        k = crypto.PKey()
                        k.generate_key(crypto.TYPE_RSA, 2048)
                        
                        cert = crypto.X509()
                        cert.get_subject().C = "US"
                        cert.get_subject().ST = "State"
                        cert.get_subject().L = "City"
                        cert.get_subject().O = "Team 5454"
                        cert.get_subject().OU = "Scouting App"
                        cert.get_subject().CN = "localhost"
                        cert.set_serial_number(1000)
                        cert.gmtime_adj_notBefore(0)
                        cert.gmtime_adj_notAfter(10*365*24*60*60)
                        cert.set_issuer(cert.get_subject())
                        cert.set_pubkey(k)
                        cert.sign(k, 'sha256')
                        
                        with open(cert_file, "wb") as cf:
                            cf.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
                        with open(key_file, "wb") as kf:
                            kf.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
                        
                        ssl_context = (cert_file, key_file)
                        print("Self-signed SSL certificates generated successfully.")
                    except ImportError:
                        print("Warning: pyOpenSSL not installed. Cannot generate SSL certs.")
                        use_ssl = False
                    except Exception as e:
                        print(f"Error generating SSL certificates: {e}")
                        use_ssl = False

            if use_ssl and ssl_context:
                print(f"🔒 Starting Flask development server with SSL on port {port}...")
                print("   ✅ HTTPS support enabled")
                print("   ✅ Full SocketIO WebSocket support")
                print(f"   ✅ Server URL: https://localhost:{port}")
                
                socketio.run(
                    app,
                    host='0.0.0.0',
                    port=port,
                    debug=not IS_PRODUCTION,
                    use_reloader=False,
                    ssl_context=ssl_context,
                    allow_unsafe_werkzeug=True
                )
            else:
                print(f"🌐 Starting Flask development server (HTTP) on port {port}...")
                print("   ⚠️  No SSL - some features may be limited")
                print("   ✅ Full SocketIO WebSocket support")
                print(f"   ✅ Server URL: http://localhost:{port}")
                
                socketio.run(
                    app,
                    host='0.0.0.0',
                    port=port,
                    debug=not IS_PRODUCTION,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True
                )
                
    except KeyboardInterrupt:
        print("\nShutting down server...")
        sys.exit(0)