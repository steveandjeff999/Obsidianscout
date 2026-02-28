"""
Database initialization utilities for the FRC Scouting Platform.
Handles automatic database setup and seeding with default data.
"""

import os
import json
from datetime import datetime, timezone, date
from app import db
from app.models import User, Role, Team, Event, Match

def initialize_database():
    """Initialize database with all required tables and default data"""
    print("Initializing database...")
    # Run schema migrations early so ORM queries don't fail on missing columns
    try:
        from app.utils.database_migrations import run_all_migrations
        print("Running automatic schema migrations before initialization...")
        run_all_migrations(db)
    except Exception as e:
        print(f"Warning: automatic migrations failed to run early: {e}")
    # Create users bind tables first (if configured), then create other tables
    from flask import current_app
    try:
        app = current_app._get_current_object()
        # If a separate users bind is configured, create those tables first using the users engine.
        if 'SQLALCHEMY_BINDS' in app.config and 'users' in app.config['SQLALCHEMY_BINDS']:
            try:
                users_engine = db.get_engine(app, bind='users')
                from app.models import Role, User, user_roles
                Role.__table__.create(users_engine, checkfirst=True)
                User.__table__.create(users_engine, checkfirst=True)
                user_roles.create(users_engine, checkfirst=True)
            except Exception as e:
                print(f"Could not create users bind tables explicitly: {e}")

        # Create remaining tables on the default bind individually to avoid
        # SQLAlchemy attempting to sort cross-bind dependencies.
        default_engine = db.get_engine(app)
        users_table_names = set(['role', 'user', 'user_roles'])
        for table in db.metadata.sorted_tables:
            if table.name in users_table_names:
                continue
            try:
                table.create(default_engine, checkfirst=True)
            except Exception as e:
                print(f"Warning: could not create table {table.name}: {e}")
        # Ensure any missing tables (or binds) get created as a safety net
        try:
            db.create_all()
        except Exception as e:
            print(f"Warning: db.create_all fallback failed: {e}")
    except Exception as e:
        # Fallback to a single create_all if something unexpected occurs
        try:
            db.create_all()
        except Exception as e2:
            print(f"Database initialization error during fallback create_all: {e2}")
    
    # Initialize authentication system
    init_auth_system()
    # After auth is initialized, ensure any legacy preferences are migrated if the users-only column exists
    try:
        from app.utils.database_migrations import column_exists_for_bind
        from app.utils.database_migrations import migrate_user_notification_prefs
        if column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
            try:
                migrated = migrate_user_notification_prefs(db, remove_after=True)
                if migrated and migrated > 0:
                    print(f"Migrated {migrated} user notification preference(s) to DB during initialization")
            except Exception as mp_e:
                print(f"Warning: migrate_user_notification_prefs failed during init: {mp_e}")
    except Exception:
        # Not critical - continuing
        pass
    
    # Initialize default configuration files
    init_default_configs()
    
    # Optionally seed with sample data
    if should_seed_sample_data():
        seed_sample_data()

    # Safety net: ensure any runtime-critical UI columns exist before returning
    # Some routes query ScoutingTeamSettings.liquid_glass_buttons directly at runtime.
    try:
        from app.utils.database_migrations import column_exists_for_bind, run_all_migrations
        # ensure each new UI column exists so routes that query them won't error
        if not column_exists_for_bind(db, None, 'scouting_team_settings', 'liquid_glass_buttons'):
            print("Detected missing scouting_team_settings.liquid_glass_buttons column - applying migrations...")
            try:
                run_all_migrations(db)
            except Exception as mm_e:
                print(f"Warning: run_all_migrations failed while adding liquid_glass_buttons: {mm_e}")
        if not column_exists_for_bind(db, None, 'scouting_team_settings', 'predictions_enabled'):
            print("Detected missing scouting_team_settings.predictions_enabled column - applying migrations...")
            try:
                run_all_migrations(db)
            except Exception as mm_e:
                print(f"Warning: run_all_migrations failed while adding predictions_enabled: {mm_e}")
        if not column_exists_for_bind(db, None, 'scouting_team_settings', 'leaderboard_accuracy_visible'):
            print("Detected missing scouting_team_settings.leaderboard_accuracy_visible column - applying migrations...")
            try:
                run_all_migrations(db)
            except Exception as mm_e:
                print(f"Warning: run_all_migrations failed while adding leaderboard_accuracy_visible: {mm_e}")
    except Exception:
        # Not critical - continue
        pass
    
    print("Database initialization complete!")

def _heal_user_roles_sqlite():
    """Directly open users.db with sqlite3 and remove orphaned user_roles rows.

    Flask-SQLAlchemy's session.execute() does NOT reliably route core-level
    DML (Table.delete()) to the correct bind engine.  By-passing the ORM
    entirely guarantees the cleanup runs against the right file.
    """
    import sqlite3 as _sqlite3
    from flask import current_app
    _users_db = os.path.join(current_app.instance_path, 'users.db')
    if not os.path.exists(_users_db):
        return  # nothing to heal
    try:
        conn = _sqlite3.connect(_users_db)
        cur = conn.cursor()
        # Make sure the table exists before touching it
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_roles'")
        if not cur.fetchone():
            conn.close()
            return
        cur.execute("DELETE FROM user_roles WHERE user_id NOT IN (SELECT id FROM user)")
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"Auto-healed {deleted} orphaned user_roles row(s) in users.db")
    except Exception as e:
        print(f"Warning: raw user_roles heal failed ({e})")


def init_auth_system():
    """Initialize the authentication system with roles and admin user"""
    # Always start with a clean session so a previous failed transaction
    # (e.g. a duplicate user_roles insert from an earlier startup attempt)
    # doesn't leave us in PendingRollbackError state.
    try:
        db.session.rollback()
    except Exception:
        pass

    # --- Auto-heal: remove orphaned user_roles rows ---
    _heal_user_roles_sqlite()

    print("Setting up authentication system...")

    # Create roles
    roles_data = [
        {
            'name': 'superadmin',
            'description': 'System-wide user management across all teams'
        },
        {
            'name': 'admin',
            'description': 'Full system access including user management and configuration'
        },
        {
            'name': 'analytics', 
            'description': 'Access to data analysis, visualizations, and reporting features'
        },
        {
            'name': 'scout',
            'description': 'Limited access for scouting data entry only'
        }
    ]
    
    created_roles = {}
    for role_data in roles_data:
        role = Role.query.filter_by(name=role_data['name']).first()
        if not role:
            role = Role(name=role_data['name'], description=role_data['description'])
            db.session.add(role)
            print(f"Created role: {role_data['name']}")
        else:
            print(f"Role already exists: {role_data['name']}")
        
        created_roles[role_data['name']] = role
    
    # Commit roles first
    try:
        db.session.commit()
    except Exception as role_commit_err:
        print(f"Warning: role commit failed ({role_commit_err}), rolling back and continuing")
        try:
            db.session.rollback()
        except Exception:
            pass
    
    # Create admin user: admin with password password
    admin_username = 'admin'
    admin_password = 'password'
    
    # Query for admin user, but if ORM access fails due to missing columns, try running migrations then re-query
    try:
        admin_user = User.query.filter_by(username=admin_username).first()
    except Exception as e:
        print(f"Auth init query failed (likely missing column): {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            from app.utils.database_migrations import run_all_migrations
            print("Attempting to run migrations to repair auth schema...")
            run_all_migrations(db)
        except Exception as me:
            print(f"Failed to run migrations: {me}")
        try:
            admin_user = User.query.filter_by(username=admin_username).first()
        except Exception as e2:
            try:
                db.session.rollback()
            except Exception:
                pass
            print(f"Auth init query still failing after migrations: {e2}")
            admin_user = None
    if not admin_user:
        admin_user = User(username=admin_username)
        admin_user.set_password(admin_password)
        admin_role = Role.query.filter_by(name='admin').first()
        if admin_role:
            admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        try:
            db.session.commit()
        except Exception as commit_err:
            db.session.rollback()
            # If the failure is a user_roles duplicate, heal and retry once
            if 'user_roles' in str(commit_err):
                print("Detected stale user_roles, healing and retrying...")
                _heal_user_roles_sqlite()
                admin_user = User(username=admin_username)
                admin_user.set_password(admin_password)
                admin_role = Role.query.filter_by(name='admin').first()
                if admin_role:
                    admin_user.roles.append(admin_role)
                db.session.add(admin_user)
                try:
                    db.session.commit()
                except Exception as retry_err:
                    print(f"Warning: admin user retry failed ({retry_err})")
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
            else:
                print(f"Warning: admin user commit failed ({commit_err})")
        
        print(f"Created admin user: {admin_username}")
        print(f"Admin password: {admin_password}")
        print("=" * 50)
        print("IMPORTANT: Change the admin password after first login!")
        print("=" * 50)
    else:
        print(f"Admin user already exists: {admin_username}")
    
    # Check for super admin (created by separate script for security)
    superadmin_user = User.query.filter_by(username='superadmin').first()
    if superadmin_user:
        print("Super admin user exists")
    else:
        print("Super admin not found - run init_superadmin.py to create")

def init_default_configs():
    """Initialize default configuration files if they don't exist"""
    print("Checking configuration files...")
    
    # Check if pit_config.json exists
    pit_config_path = os.path.join(os.getcwd(), 'config', 'pit_config.json')
    if not os.path.exists(pit_config_path):
        print("Creating default pit scouting configuration...")
        create_default_pit_config(pit_config_path)
    
    # Check if game_config.json exists
    game_config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
    if not os.path.exists(game_config_path):
        print("Creating default game configuration...")
        create_default_game_config(game_config_path)

def create_default_pit_config(config_path):
    """Create default pit scouting configuration"""
    default_config = {
        "pit_scouting": {
            "title": "Pit Scouting",
            "description": "Collect detailed information about teams and their robots",
            "sections": [
                {
                    "id": "team_info",
                    "name": "Team Information",
                    "elements": [
                        {
                            "id": "team_number",
                            "perm_id": "team_number",
                            "name": "Team Number",
                            "type": "number",
                            "required": True,
                            "validation": {
                                "min": 1,
                                "max": 99999
                            }
                        },
                        {
                            "id": "team_name",
                            "perm_id": "team_name",
                            "name": "Team Name",
                            "type": "text",
                            "required": False
                        },
                        {
                            "id": "drive_team_experience",
                            "perm_id": "drive_team_experience",
                            "name": "Drive Team Experience",
                            "type": "select",
                            "options": [
                                {"value": "rookie", "label": "Rookie (0-1 years)"},
                                {"value": "experienced", "label": "Experienced (2-4 years)"},
                                {"value": "veteran", "label": "Veteran (5+ years)"}
                            ]
                        }
                    ]
                },
                {
                    "id": "robot_design",
                    "name": "Robot Design",
                    "elements": [
                        {
                            "id": "drivetrain_type",
                            "perm_id": "drivetrain_type",
                            "name": "Drivetrain Type",
                            "type": "select",
                            "options": [
                                {"value": "tank", "label": "Tank Drive"},
                                {"value": "mecanum", "label": "Mecanum Drive"},
                                {"value": "swerve", "label": "Swerve Drive"},
                                {"value": "other", "label": "Other"}
                            ]
                        },
                        {
                            "id": "autonomous_capability",
                            "perm_id": "autonomous_capability",
                            "name": "Autonomous Capability",
                            "type": "boolean"
                        },
                        {
                            "id": "notes",
                            "perm_id": "notes",
                            "name": "Additional Notes",
                            "type": "textarea"
                        }
                    ]
                }
            ]
        }
    }
    
    # Create config directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    print(f"Created default pit scouting configuration at {config_path}")

def create_default_game_config(config_path):
    """Create default game configuration"""
    current_year = datetime.now(timezone.utc).year
    default_config = {
        "season": current_year,
        "game_name": f"FRC {current_year} Game",
        "alliance_size": 3,
        "match_types": ["Practice", "Qualification", "Playoff"],
        "scouting_stations": 6,
        "preferred_api_source": "first",
        "api_settings": {
            "username": "",
            "auth_token": "",
            "base_url": "https://frc-api.firstinspires.org"
        },
        "tba_api_settings": {
            "auth_key": "",
            "base_url": "https://www.thebluealliance.com/api/v3"
        },
        "scoring_elements": [
            {
                "id": "auto_mobility",
                "perm_id": "auto_mobility",
                "name": "Auto Mobility",
                "type": "boolean",
                "phase": "autonomous",
                "points": 3
            },
            {
                "id": "teleop_speaker",
                "perm_id": "teleop_speaker",
                "name": "Teleop Speaker",
                "type": "number",
                "phase": "teleop",
                "points": 2
            },
            {
                "id": "endgame_climb",
                "perm_id": "endgame_climb",
                "name": "Endgame Climb",
                "type": "boolean",
                "phase": "endgame",
                "points": 4
            }
        ]
    }
    
    # Create config directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    print(f"Created default game configuration at {config_path}")

def should_seed_sample_data():
    """Check if we should seed with sample data (only if no teams exist)"""
    return Team.query.count() == 0


def ensure_default_tables(app):
    """Ensure that all non-user (default-bind) tables exist.
    This is safe to call at runtime when the default SQLite DB file
    has been deleted or is missing tables. It creates tables per-table
    to avoid SQLAlchemy sorting issues across multiple binds.
    """
    try:
        db.init_app(app)
        default_engine = db.get_engine(app)
        users_table_names = set(['role', 'user', 'user_roles'])
        for table in db.metadata.sorted_tables:
            if table.name in users_table_names:
                continue
            try:
                table.create(default_engine, checkfirst=True)
            except Exception as te:
                app.logger.debug(f"Could not create table {table.name}: {te}")
        return True
    except Exception as e:
        try:
            # Last resort: attempt db.create_all()
            db.create_all()
            return True
        except Exception as e2:
            print(f"ensure_default_tables failed: {e2}")
            return False

def seed_sample_data():
    """Add sample data to the database for testing"""
    print("Skipping sample data seeding - no sample data will be added")
    print("Sample data seeding complete!")

def check_database_health():
    """Check if database is properly initialized"""
    try:
        # Check if basic tables exist and have expected data
        user_count = User.query.count()
        role_count = Role.query.count()
        
        if user_count == 0:
            print("Warning: No users found in database")
            return False
        
        if role_count == 0:
            print("Warning: No roles found in database")
            return False
        
        # Check if admin user exists
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            print("Warning: Admin user not found")
            return False
        
        print(f"Database health check passed: {user_count} users, {role_count} roles")
        return True
        
    except Exception as e:
        print(f"Database health check failed: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        # Attempt to automatically repair schema issues by running migrations
        try:
            from app.utils.database_migrations import run_all_migrations
            print("Attempting to run automatic migrations to repair DB...")
            added = run_all_migrations(db)
            if added > 0:
                print("Schema repaired by migrations; re-checking database health...")
                # Try a quick re-check (best-effort)
                try:
                    user_count = User.query.count()
                    role_count = Role.query.count()
                    if user_count == 0 or role_count == 0:
                        return False
                    return True
                except Exception as e2:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    print(f"Re-check after migration failed: {e2}")
                    return False
        except Exception as me:
            try:
                db.session.rollback()
            except Exception:
                pass
            print(f"Automatic migration attempt failed: {me}")
        return False

if __name__ == '__main__':
    # This allows the module to be run directly for testing
    from app import create_app
    app = create_app()
    with app.app_context():
        initialize_database()
