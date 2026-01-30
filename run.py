
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

# Print diagnostics for debugging directory/permission issues
print("=== Startup Diagnostics ===")
print(f"Current working directory: {os.getcwd()}")
print(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")
print(f"Python executable: {sys.executable}")

# Change to the script's directory to ensure consistent paths
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != script_dir:
    print(f"Changing directory to: {script_dir}")
    try:
        os.chdir(script_dir)
        print(f"Successfully changed to: {os.getcwd()}")
    except Exception as e:
        print(f"Warning: Could not change directory: {e}")

# Check if instance directory exists and is accessible
instance_path = os.path.join(script_dir, 'instance')
print(f"Instance path: {instance_path}")
print(f"Instance directory exists: {os.path.exists(instance_path)}")
if os.path.exists(instance_path):
    print(f"Instance directory is writable: {os.access(instance_path, os.W_OK)}")
else:
    parent_dir = os.path.dirname(instance_path)
    print(f"Parent directory writable: {os.access(parent_dir, os.W_OK)}")

print("===========================\n")

from app import create_app, socketio, db
from flask import redirect, url_for, request, flash
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import func
from app.models import User, Role
from app.utils.database_init import initialize_database, check_database_health
# ============================================================================
# SERVER CONFIGURATION FLAG
# Set to True to use Waitress WSGI server, False to use Flask dev server with SSL
# ============================================================================
USE_WAITRESS = False # Change this to False to use Flask development server with SSL

app = create_app()

# Setup auth redirect handler
@app.before_request
def check_first_run():
    # Log basic request info so we can debug API vs app origins of failures
    try:
        remote = request.remote_addr or request.environ.get('REMOTE_ADDR')
        auth = request.headers.get('Authorization')
        content_type = request.headers.get('Content-Type')
        q = request.query_string.decode('utf-8') if request.query_string else ''
        print(f"Incoming request from {remote}: {request.method} {request.path}?{q} Authorization={'present' if auth else 'none'} Content-Type={content_type}")
        # For methods that often carry payloads, show a small preview (avoid huge dumps)
        if request.method in ('POST', 'PUT', 'PATCH'):
            try:
                body = request.get_data(as_text=True)
                if body:
                    preview = body[:1000]
                    print(f"  Body preview: {preview}")
            except Exception:
                pass
    except Exception as e:
        print(f"  Failed to log incoming request: {e}")

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


@app.after_request
def log_response(response):
    # Log response status to terminal for debugging origin of 401/other errors
    try:
        remote = request.remote_addr or request.environ.get('REMOTE_ADDR')
        # Use response.status for human readable status
        print(f"Outgoing response to {remote}: {request.method} {request.path} -> {response.status}")
    except Exception:
        pass
    return response

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
        
        # Auto-create missing tables for all databases
        try:
            print("Checking for missing database tables...")
            
            # Create all tables for main database
            db.create_all()
            print("Main database tables verified/created")
            
            # Create tables for misc database (notifications)
            try:
                from app.models_misc import NotificationSubscription, DeviceToken, NotificationLog, NotificationQueue
                db.create_all(bind_key='misc')
                print("Misc database (notifications) tables verified/created")
            except Exception as misc_error:
                print(f"Warning: Could not create misc database tables: {misc_error}")
            
            # Create tables for users database if using separate bind
            try:
                db.create_all(bind_key='users')
                print("Users database tables verified/created")
            except Exception as users_error:
                print(f"Warning: Could not create users database tables: {users_error}")
            
            # Create tables for pages database if using separate bind
            try:
                db.create_all(bind_key='pages')
                print("Pages database tables verified/created")
            except Exception as pages_error:
                print(f"Warning: Could not create pages database tables: {pages_error}")
            
            # Create tables for APIs database if using separate bind
            try:
                db.create_all(bind_key='apis')
                print("APIs database tables verified/created")
            except Exception as apis_error:
                print(f"Warning: Could not create APIs database tables: {apis_error}")
            
            print("Database table verification complete!")

            # Fix matches with missing event_id (may exist from older imports/bugs).
            try:
                from app.models import Match
                from app.routes.data import get_or_create_event

                null_matches = Match.query.filter(Match.event_id == None).count()
                if null_matches and null_matches > 0:
                    placeholder = get_or_create_event(
                        name='Imported (Missing Event) - Startup Fix',
                        code=f'IMPORT-NULL-{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}',
                        year=datetime.utcnow().year
                    )
                    Match.query.filter(Match.event_id == None).update({Match.event_id: placeholder.id})
                    db.session.commit()
                    print(f"Startup fix: Assigned {null_matches} matches to placeholder event id {placeholder.id}")
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                print(f"Warning: Failed to fix matches with missing event_id on startup: {e}")
            
            # Run comprehensive database schema migrations
            try:
                from app.utils.database_migrations import run_all_migrations
                run_all_migrations(db)
                # Migrate the legacy JSON-only "only_password_reset_emails" into the users DB column
                try:
                    from app.utils.database_migrations import migrate_user_notification_prefs
                    migrated = migrate_user_notification_prefs(db, remove_after=True)
                    if migrated and migrated > 0:
                        print(f"Migrated {migrated} user notification preference(s) to DB")
                except Exception as mig_err:
                    print(f"Warning: Failed to auto-migrate user notification preferences: {mig_err}")
            except Exception as migration_err:
                print(f"Warning: Database migration check failed: {migration_err}")
            
        except Exception as table_error:
            print(f"Warning: Error during table verification: {table_error}")
        
        # Clear old failed login attempts on startup (especially important after updates)
        try:
            from app.models import LoginAttempt, db
            
            # Clear failed login attempts older than 5 minutes on startup
            startup_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
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
                
                print("SuperAdmin account created successfully!")
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
        """Background thread for periodic API data synchronization with per-team throttling.

        Behavior:
        - If event start date is not known -> autosync every 20 minutes
        - If event start date is > 1.5 weeks away -> autosync daily
        - If event start date is within 1.5 weeks -> autosync at the existing (recent) interval
        - This applies only to the automated periodic sync worker. Manual syncs are unaffected.
        """
        # Intervals (seconds)
        RECENT_INTERVAL = 180           # keep existing frequent autosync (3 minutes)
        UNKNOWN_DATE_INTERVAL = 20 * 60 # 20 minutes for N/A dates
        DAILY_INTERVAL = 24 * 60 * 60   # daily for far-out events
        # How often to re-check the configured event_code in game_config (seconds)
        CHECK_EVENT_INTERVAL = 5 * 60  # 5 minutes

        # Use shared sync status storage so routes can report sync times
        from app.utils.sync_status import (
            update_last_sync,
            get_last_sync,
            set_event_cache,
            get_event_cache,
        )

        while True:
            try:
                # Main loop ticks every minute to evaluate per-team schedules
                time.sleep(60)
                print("Starting periodic API data sync (evaluating per-team intervals)...")

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
                        from app.utils.team_utils import team_sort_key
                        for scouting_team_number in sorted(team_numbers, key=team_sort_key):
                            try:
                                if scouting_team_number is None:
                                    print("Running API sync for unassigned/default scope")
                                else:
                                    print(f"Running API sync for scouting team: {scouting_team_number}")

                                # Always load the latest game_config for the team (so changes like auto_sync_enabled
                                # take effect promptly). We will only refresh the cached event_code/start_date
                                # value every CHECK_EVENT_INTERVAL to reduce frequent event date checks.
                                game_config = load_game_config(team_number=scouting_team_number)
                                try:
                                    app.config['GAME_CONFIG'] = game_config
                                except Exception:
                                    pass

                                # Check team's auto-sync setting (default True)
                                api_settings = game_config.get('api_settings') or {}
                                auto_sync_enabled = api_settings.get('auto_sync_enabled', True)
                                if not auto_sync_enabled:
                                    print(f"  Auto-sync disabled for team {scouting_team_number}, skipping")
                                    continue

                                # Use cached event info when recently checked; otherwise compute fresh values
                                cached = get_event_cache(scouting_team_number)
                                now_utc = datetime.now(timezone.utc)
                                raw_event_code = game_config.get('current_event_code')
                                # Prepend year to event code so each year is treated as a different event (e.g., 2026ARLI)
                                event_year = game_config.get('season') or game_config.get('year') or now_utc.year
                                event_code = f"{event_year}{raw_event_code}" if raw_event_code else None
                                use_cached_event = cached and (now_utc - cached.get('checked_at')).total_seconds() < CHECK_EVENT_INTERVAL and cached.get('event_code') == event_code

                                # If we have a recent cached event decision, ensure the cached desired_interval
                                # follows the symmetric ±1.5 week rule: keep RECENT when within 1.5 weeks of
                                # the event start (past or future), otherwise use DAILY. Update cache if needed.
                                try:
                                    if use_cached_event and cached:
                                        cached_start = cached.get('start_date')
                                        if cached_start:
                                            try:
                                                # cached_start may be a date or datetime
                                                if hasattr(cached_start, 'year') and not getattr(cached_start, 'tzinfo', None):
                                                    cached_start_dt = datetime.combine(cached_start, datetime.min.time()).replace(tzinfo=timezone.utc)
                                                else:
                                                    cached_start_dt = cached_start if getattr(cached_start, 'tzinfo', None) else cached_start.replace(tzinfo=timezone.utc)

                                                # Determine whether the event is within ±1.5 weeks
                                                delta_seconds_cached = (cached_start_dt - now_utc).total_seconds()
                                                threshold_seconds = 1.5 * 7 * 24 * 60 * 60
                                                if abs(delta_seconds_cached) <= threshold_seconds:
                                                    # Within ±1.5 weeks -> recent
                                                    try:
                                                        set_event_cache(scouting_team_number, event_code, cached_start, RECENT_INTERVAL)
                                                    except Exception:
                                                        pass
                                                    print(f"  Cached event {event_code} within ±1.5 weeks -> enforcing recent autosync")
                                                else:
                                                    # Outside ±1.5 weeks -> daily
                                                    try:
                                                        set_event_cache(scouting_team_number, event_code, cached_start, DAILY_INTERVAL)
                                                    except Exception:
                                                        pass
                                                    print(f"  Cached event {event_code} outside ±1.5 weeks -> enforcing daily autosync")
                                            except Exception:
                                                # If cached start_date parsing fails, ignore and continue using cache
                                                pass
                                except Exception:
                                    pass

                                if not event_code:
                                    # No event code configured for this team. Populate the cache
                                    # so the /synctimes endpoint can report a desired interval
                                    # (treat as unknown date -> use UNKNOWN_DATE_INTERVAL).
                                    try:
                                        set_event_cache(scouting_team_number, None, None, UNKNOWN_DATE_INTERVAL)
                                    except Exception:
                                        pass
                                    print(f"  No event code configured for team {scouting_team_number}, skipping")
                                    continue

                                # Get or create event for this team and event code (so we can read start_date)
                                # Use case-insensitive lookup to handle legacy lowercase event codes
                                event = Event.query.filter(
                                    func.upper(Event.code) == event_code.upper(),
                                    Event.scouting_team_number == scouting_team_number
                                ).first()
                                if not event:
                                    print(f"  Event {event_code} not found for team {scouting_team_number}, fetching from API...")
                                    try:
                                        # Try to get full event details from API including timezone
                                        # Use raw_event_code for API calls since external APIs don't use year-prefixed codes
                                        from app.utils.api_utils import get_event_details_dual_api
                                        from app.routes.data import get_or_create_event
                                        event_details = get_event_details_dual_api(raw_event_code)

                                        if event_details:
                                            # Use get_or_create_event to properly handle race conditions
                                            # Store with year-prefixed event_code to differentiate years
                                            event = get_or_create_event(
                                                name=event_details.get('name', raw_event_code),
                                                code=event_code,
                                                year=event_details.get('year', game_config.get('season', None) or game_config.get('year', 0)),
                                                location=event_details.get('location'),
                                                start_date=event_details.get('start_date'),
                                                end_date=event_details.get('end_date'),
                                                scouting_team_number=scouting_team_number
                                            )
                                            # Set timezone separately if available (not in get_or_create_event params)
                                            if event_details.get('timezone') and not getattr(event, 'timezone', None):
                                                event.timezone = event_details.get('timezone')
                                                db.session.add(event)
                                            if event.timezone:
                                                print(f"  Event timezone: {event.timezone}")
                                        else:
                                            # Use get_or_create_event for fallback as well
                                            # Store with year-prefixed event_code to differentiate years
                                            event = get_or_create_event(
                                                name=raw_event_code,
                                                code=event_code,
                                                year=game_config.get('season', None) or game_config.get('year', 0),
                                                scouting_team_number=scouting_team_number
                                            )

                                        db.session.commit()
                                    except Exception as e:
                                        db.session.rollback()
                                        print(f"  Failed to create event {event_code} for team {scouting_team_number}: {e}")
                                        continue

                                # Decide per-team desired autosync interval
                                try:
                                    # If we have a recently cached event decision, reuse it to avoid
                                    # repeated API/event-date computations.
                                    if 'use_cached_event' in locals() and use_cached_event and cached:
                                        desired_interval = cached.get('desired_interval', RECENT_INTERVAL)
                                        print(f"  Using cached desired interval for {event_code}: {desired_interval}s")
                                        # Ensure event object is available in DB for associations
                                        # Use case-insensitive lookup to handle legacy lowercase event codes
                                        event = Event.query.filter(
                                            func.upper(Event.code) == event_code.upper(),
                                            Event.scouting_team_number == scouting_team_number
                                        ).first()
                                    else:
                                        desired_interval = RECENT_INTERVAL
                                        now_utc = datetime.now(timezone.utc)

                                        if not getattr(event, 'start_date', None):
                                            # Unknown / N/A event date -> autosync every 20 minutes
                                            desired_interval = UNKNOWN_DATE_INTERVAL
                                            print(f"  Event date unknown for {event_code} -> using {int(UNKNOWN_DATE_INTERVAL/60)} minute autosync")
                                        else:
                                            # Convert event.start_date (date) to a datetime at midnight UTC
                                            try:
                                                event_start_dt = datetime.combine(event.start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                                            except Exception:
                                                # If it's already a datetime, coerce tzinfo
                                                event_start_dt = event.start_date if event.start_date.tzinfo else event.start_date.replace(tzinfo=timezone.utc)

                                            delta_seconds = (event_start_dt - now_utc).total_seconds()
                                            # 1.5 weeks = 1.5 * 7 days
                                            threshold_seconds = 1.5 * 7 * 24 * 60 * 60
                                            # If the event is within ±1.5 weeks -> recent interval
                                            if abs(delta_seconds) <= threshold_seconds:
                                                desired_interval = RECENT_INTERVAL
                                                print(f"  Event {event_code} within ±1.5 weeks -> using recent autosync interval")
                                            else:
                                                # Outside ±1.5 weeks -> daily
                                                desired_interval = DAILY_INTERVAL
                                                print(f"  Event {event_code} outside ±1.5 weeks -> using daily autosync")
                                except Exception as e:
                                    print(f"  Warning determining desired interval for team {scouting_team_number}: {e}")
                                    desired_interval = RECENT_INTERVAL

                                # Update cache with new event info and desired interval so other parts of app can read it
                                try:
                                    set_event_cache(scouting_team_number, event_code, getattr(event, 'start_date', None), desired_interval)
                                except Exception:
                                    pass

                                # If the event currently has no teams or no matches for this scouting team,
                                # force an immediate API sync so we populate missing data promptly.
                                try:
                                    if scouting_team_number is None:
                                        teams_count = Team.query.filter(Team.events.any(id=event.id), Team.scouting_team_number.is_(None)).count()
                                        matches_count = Match.query.filter_by(event_id=event.id, scouting_team_number=None).count()
                                    else:
                                        teams_count = Team.query.filter(Team.events.any(id=event.id), Team.scouting_team_number==scouting_team_number).count()
                                        matches_count = Match.query.filter_by(event_id=event.id, scouting_team_number=scouting_team_number).count()

                                    if (teams_count == 0) or (matches_count == 0):
                                        print(f"  Event {event_code} has no teams or matches for team {scouting_team_number} (teams={teams_count}, matches={matches_count}) -> forcing immediate API sync")
                                        # Reset last sync so we won't skip due to interval checks
                                        last = None
                                except Exception as e:
                                    print(f"  Warning checking event team/match counts for immediate sync: {e}")

                                # Check last sync time for this team and skip if within desired interval
                                last = get_last_sync(scouting_team_number)
                                if last:
                                    seconds_since = (datetime.now(timezone.utc) - last).total_seconds()
                                    if seconds_since < desired_interval:
                                        next_in = int(desired_interval - seconds_since)
                                        print(f"  Skipping autosync for team {scouting_team_number} (next in {next_in}s)")
                                        continue

                                # --- Perform the actual sync for this team ---
                                try:
                                    # Use raw_event_code for API calls (external APIs don't use year-prefixed codes)
                                    team_data_list = get_teams_dual_api(raw_event_code)
                                    teams_added = 0
                                    teams_updated = 0

                                    for team_data in team_data_list:
                                        if not team_data or not team_data.get('team_number'):
                                            continue

                                        team_number = team_data.get('team_number')
                                        team = Team.query.filter_by(team_number=team_number, scouting_team_number=scouting_team_number).first()

                                        if team:
                                            team.team_name = team_data.get('team_name', team.team_name)
                                            team.location = team_data.get('location', team.location)
                                            teams_updated += 1
                                        else:
                                            team = Team(team_number=team_number,
                                                        team_name=team_data.get('team_name'),
                                                        location=team_data.get('location'),
                                                        scouting_team_number=scouting_team_number)
                                            db.session.add(team)
                                            teams_added += 1

                                        if event not in team.events:
                                            try:
                                                team.events.append(event)
                                            except Exception:
                                                pass

                                    print(f"  Teams sync for {scouting_team_number}: {teams_added} added, {teams_updated} updated")
                                except Exception as e:
                                    print(f"  Error syncing teams for {scouting_team_number}: {str(e)}")

                                try:
                                    # Use raw_event_code for API calls (external APIs don't use year-prefixed codes)
                                    match_data_list = get_matches_dual_api(raw_event_code)
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
                                            match.red_alliance = match_data.get('red_alliance', match.red_alliance)
                                            match.blue_alliance = match_data.get('blue_alliance', match.blue_alliance)
                                            match.winner = match_data.get('winner', match.winner)
                                            match.red_score = match_data.get('red_score', match.red_score)
                                            match.blue_score = match_data.get('blue_score', match.blue_score)
                                            matches_updated += 1
                                        else:
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
                                    # Merge any duplicate events that may have been created
                                    try:
                                        from app.routes.data import merge_duplicate_events, merge_duplicate_matches
                                        merge_duplicate_events(scouting_team_number)
                                        # Also ensure duplicate matches (from prior runs) are merged
                                        try:
                                            merge_duplicate_matches(scouting_team_number=scouting_team_number)
                                        except Exception as mm_err:
                                            print(f"  Warning: Could not merge duplicate matches: {mm_err}")
                                    except Exception as merge_err:
                                        print(f"  Warning: Could not merge duplicate events: {merge_err}")
                                    # Update last sync timestamp on success (shared)
                                    try:
                                        update_last_sync(scouting_team_number)
                                    except Exception:
                                        pass
                                except Exception as e:
                                    db.session.rollback()
                                    print(f"  Failed to commit changes for team {scouting_team_number}: {e}")

                            except Exception as e:
                                print(f"  Error processing scouting team {scouting_team_number}: {e}")

                        print("API data sync evaluation completed for all teams")

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

    # Start alliance API sync worker (syncs teams/matches for alliances)
    def api_alliance_sync_worker():
        while True:
            try:
                time.sleep(60)
                with app.app_context():
                    from app.routes.scouting_alliances import perform_periodic_alliance_api_sync
                    perform_periodic_alliance_api_sync()
            except Exception as e:
                print(f"Error in alliance API data sync worker: {str(e)}")
                time.sleep(60)

    api_alliance_sync_thread = threading.Thread(target=api_alliance_sync_worker, daemon=True)
    api_alliance_sync_thread.start()
    print("Started alliance API auto-sync thread (1-minute evaluation)")
    
    security_maintenance_thread = threading.Thread(target=security_maintenance_worker, daemon=True)
    security_maintenance_thread.start()
    print("Started security maintenance thread (1-hour intervals)")
    
    # Start notification worker thread
    try:
        from app.utils.notification_worker import start_notification_worker
        notification_worker_thread = start_notification_worker(app)
        print("Started notification worker thread (processes every minute, updates every 5-10 min)")
    except Exception as e:
        print(f"Warning: Could not start notification worker: {e}")
    
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
            print(f"Starting server with Waitress WSGI server on port {port}...")
            print("   Production-ready server")
            print("   SocketIO polling mode for compatibility")
            
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
                print(f" Starting Flask development server with SSL on port {port}...")
                print("   HTTPS support enabled")
                print("   Full SocketIO WebSocket support")
                print(f"   Server URL: https://localhost:{port}")
                
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
                print(f" Starting Flask development server (HTTP) on port {port}...")
                print("   Warning: No SSL - some features may be limited")
                print("   Full SocketIO WebSocket support")
                print(f"   Server URL: http://localhost:{port}")
                
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