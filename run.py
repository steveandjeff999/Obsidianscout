
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
                print("   Must Change Password: False")
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

    # Multi-server sync functionality removed - keeping only normal user features

    # Start periodic API data sync thread
    def api_data_sync_worker():
        """Background thread for periodic API data synchronization"""
        while True:
            try:
                time.sleep(180)  # Wait 3 minutes (180 seconds)
                print("Starting periodic API data sync...")
                
                # Import here to avoid circular imports
                from app.utils.config_manager import load_game_config
                from app.utils.api_utils import get_teams_dual_api, get_matches_dual_api
                from app.models import Team, Match, Event, User, ScoutingTeamSettings, db
                
                with app.app_context():
                    try:
                        # Build a set of scouting team numbers to run sync for
                        team_numbers = set()

                        try:
                            # Collect from ScoutingTeamSettings
                            for rec in ScoutingTeamSettings.query.with_entities(ScoutingTeamSettings.scouting_team_number).all():
                                if rec[0] is not None:
                                    team_numbers.add(rec[0])
                        except Exception:
                            pass

                        try:
                            # Collect from Users
                            for rec in User.query.with_entities(User.scouting_team_number).filter(User.scouting_team_number.isnot(None)).distinct().all():
                                if rec[0] is not None:
                                    team_numbers.add(rec[0])
                        except Exception:
                            pass

                        try:
                            # As a fallback, collect any team.scouting_team_number values
                            for rec in Team.query.with_entities(Team.scouting_team_number).filter(Team.scouting_team_number.isnot(None)).distinct().all():
                                if rec[0] is not None:
                                    team_numbers.add(rec[0])
                        except Exception:
                            pass

                        # If no team numbers discovered, still attempt a single run with None (legacy behavior)
                        if not team_numbers:
                            team_numbers.add(None)

                        # Iterate each scouting team and run sync scoped to that team
                        for scouting_team_number in sorted(team_numbers, key=lambda x: (x is None, x)):
                            try:
                                if scouting_team_number is None:
                                    print("Running API sync for unassigned/default scope")
                                else:
                                    print(f"Running API sync for scouting team: {scouting_team_number}")

                                # Load game config for this team and make it available to helpers
                                # so background threads behave like UI requests (which set GAME_CONFIG)
                                game_config = load_game_config(team_number=scouting_team_number)
                                try:
                                    # Ensure helper functions that call get_current_game_config()
                                    # will see the team-scoped config when running in a background thread.
                                    app.config['GAME_CONFIG'] = game_config
                                except Exception:
                                    pass
                                # Check team's auto-sync setting (default True)
                                api_settings = game_config.get('api_settings') or {}
                                auto_sync_enabled = api_settings.get('auto_sync_enabled', True)
                                if not auto_sync_enabled:
                                    print(f"  Auto-sync disabled for team {scouting_team_number}, skipping")
                                    continue

                                event_code = game_config.get('current_event_code')

                                if not event_code:
                                    print(f"  No event code configured for team {scouting_team_number}, skipping")
                                    continue

                                # Get or create event for this team and event code
                                event = Event.query.filter_by(code=event_code, scouting_team_number=scouting_team_number).first()
                                if not event:
                                    print(f"  Event {event_code} not found for team {scouting_team_number}, creating placeholder event")
                                    try:
                                        event = Event(name=event_code, code=event_code, year=game_config.get('season', None) or game_config.get('year', 0), scouting_team_number=scouting_team_number)
                                        db.session.add(event)
                                        db.session.commit()
                                    except Exception as e:
                                        db.session.rollback()
                                        print(f"  Failed to create event {event_code} for team {scouting_team_number}: {e}")
                                        continue

                                # Sync teams for this scouting team + event
                                try:
                                    team_data_list = get_teams_dual_api(event_code)
                                    teams_added = 0
                                    teams_updated = 0

                                    for team_data in team_data_list:
                                        if not team_data or not team_data.get('team_number'):
                                            continue

                                        team_number = team_data.get('team_number')
                                        team = Team.query.filter_by(team_number=team_number, scouting_team_number=scouting_team_number).first()

                                        if team:
                                            # Update existing team
                                            team.team_name = team_data.get('team_name', team.team_name)
                                            team.location = team_data.get('location', team.location)
                                            teams_updated += 1
                                        else:
                                            # Add new team and assign scouting team
                                            team = Team(team_number=team_number,
                                                        team_name=team_data.get('team_name'),
                                                        location=team_data.get('location'),
                                                        scouting_team_number=scouting_team_number)
                                            db.session.add(team)
                                            teams_added += 1

                                        # Associate with event if not already associated
                                        if event not in team.events:
                                            try:
                                                team.events.append(event)
                                            except Exception:
                                                pass

                                    print(f"  Teams sync for {scouting_team_number}: {teams_added} added, {teams_updated} updated")
                                except Exception as e:
                                    print(f"  Error syncing teams for {scouting_team_number}: {str(e)}")

                                # Sync matches for this scouting team + event
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

                                        match = Match.query.filter_by(event_id=event.id, match_number=match_number, match_type=match_type, scouting_team_number=scouting_team_number).first()

                                        if match:
                                            # Update existing match
                                            match.red_alliance = match_data.get('red_alliance', match.red_alliance)
                                            match.blue_alliance = match_data.get('blue_alliance', match.blue_alliance)
                                            match.winner = match_data.get('winner', match.winner)
                                            match.red_score = match_data.get('red_score', match.red_score)
                                            match.blue_score = match_data.get('blue_score', match.blue_score)
                                            matches_updated += 1
                                        else:
                                            # Add new match and assign scouting team
                                            match = Match(match_number=match_number,
                                                          match_type=match_type,
                                                          event_id=event.id,
                                                          red_alliance=match_data.get('red_alliance'),
                                                          blue_alliance=match_data.get('blue_alliance'),
                                                          red_score=match_data.get('red_score'),
                                                          blue_score=match_data.get('blue_score'),
                                                          winner=match_data.get('winner'),
                                                          scouting_team_number=scouting_team_number)
                                            db.session.add(match)
                                            matches_added += 1

                                    print(f"  Matches sync for {scouting_team_number}: {matches_added} added, {matches_updated} updated")
                                except Exception as e:
                                    print(f"  Error syncing matches for {scouting_team_number}: {str(e)}")

                                # Commit changes for this team scope
                                try:
                                    db.session.commit()
                                except Exception as e:
                                    db.session.rollback()
                                    print(f"  Failed to commit changes for team {scouting_team_number}: {e}")

                            except Exception as e:
                                print(f"  Error processing scouting team {scouting_team_number}: {e}")

                        print("API data sync completed for all teams")

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
    
    # Multi-server sync services removed - keeping only normal user functionality
    
    # Real-time file synchronization removed - keeping only normal user features
    
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

                        # Add Subject Alternative Names so the cert is valid for both localhost and 127.0.0.1
                        try:
                            san = b"DNS:localhost,IP:127.0.0.1"
                            cert.add_extensions([crypto.X509Extension(b"subjectAltName", False, san)])
                        except Exception:
                            # Some pyOpenSSL/OpenSSL builds may reject adding SAN this way; continue without it
                            pass

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