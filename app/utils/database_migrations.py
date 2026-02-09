"""
Database auto-migration utilities for automatic schema upgrades.

This module handles automatic addition of missing columns to existing database tables
to support seamless upgrades from older versions of the database schema.

Each migration is defined with:
- table_name: Name of the table to modify
- column_name: Name of the column to add
- column_sql: SQLite ALTER TABLE statement fragment (e.g., "VARCHAR(50) DEFAULT 'value'")
- bind_key: Database bind key (None for default, 'users', 'misc', 'pages', 'apis')
"""

from sqlalchemy import text, inspect

# ==============================================================================
# MIGRATION DEFINITIONS
# ==============================================================================
# Each entry is (table_name, column_name, sql_type_and_default, bind_key)
# bind_key can be: None (default db), 'users', 'misc', 'pages', 'apis'
# 
# When adding new columns to models, add the migration here to support
# automatic upgrade of existing databases.
# ==============================================================================

MIGRATIONS = [
    # -------------------------------------------------------------------------
    # User table migrations (users bind)
    # -------------------------------------------------------------------------
    ('user', 'must_change_password', 'BOOLEAN DEFAULT 0', 'users'),
    ('user', 'profile_picture', "VARCHAR(256) DEFAULT 'img/avatars/default.png'", 'users'),
    ('user', 'only_password_reset_emails', 'BOOLEAN DEFAULT 0', 'users'),
    ('user', 'scouting_team_number', 'INTEGER', 'users'),
    ('user', 'last_login', 'DATETIME', 'users'),
    ('user', 'created_at', 'DATETIME', 'users'),
    ('user', 'updated_at', 'DATETIME', 'users'),
    
    # -------------------------------------------------------------------------
    # Event table migrations (default bind)
    # -------------------------------------------------------------------------
    ('event', 'timezone', 'VARCHAR(50)', None),
    ('event', 'schedule_offset', 'INTEGER', None),
    ('event', 'code', 'VARCHAR(20)', None),
    ('event', 'scouting_team_number', 'INTEGER', None),
    
    # -------------------------------------------------------------------------
    # Match table migrations (default bind)
    # -------------------------------------------------------------------------
    ('match', 'scheduled_time', 'DATETIME', None),
    ('match', 'predicted_time', 'DATETIME', None),
    ('match', 'actual_time', 'DATETIME', None),
    ('match', 'winner', 'VARCHAR(10)', None),
    ('match', 'scouting_team_number', 'INTEGER', None),
    
    # -------------------------------------------------------------------------
    # Team table migrations (default bind)
    # -------------------------------------------------------------------------
    ('team', 'scouting_team_number', 'INTEGER', None),
    
    # -------------------------------------------------------------------------
    # Match table migrations (default bind)
    # -------------------------------------------------------------------------
    ('match', 'display_match_number', 'VARCHAR(20)', None),  # Human-friendly playoff match display like '1-1'
    
    # -------------------------------------------------------------------------
    # ScoutingData table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_data', 'scouting_team_number', 'INTEGER', None),
    ('scouting_data', 'scout_id', 'INTEGER', None),
    
    # -------------------------------------------------------------------------
    # PitScoutingData table migrations (default bind)
    # -------------------------------------------------------------------------
    ('pit_scouting_data', 'scouting_team_number', 'INTEGER', None),
    ('pit_scouting_data', 'scout_id', 'INTEGER', None),
    ('pit_scouting_data', 'local_id', 'VARCHAR(36)', None),
    ('pit_scouting_data', 'is_uploaded', 'BOOLEAN DEFAULT 0', None),
    ('pit_scouting_data', 'upload_timestamp', 'DATETIME', None),
    ('pit_scouting_data', 'device_id', 'VARCHAR(100)', None),
    
    # -------------------------------------------------------------------------
    # ScoutingTeamSettings table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_team_settings', 'account_creation_locked', 'BOOLEAN DEFAULT 0', None),
    # UI preference for modern 'liquid glass' button styling. Added as a safe migration
    # so older databases can be upgraded automatically on startup if needed.
    ('scouting_team_settings', 'liquid_glass_buttons', 'BOOLEAN DEFAULT 0', None),
    ('scouting_team_settings', 'spinning_counters_enabled', 'BOOLEAN DEFAULT 0', None),
    ('scouting_team_settings', 'locked_by_user_id', 'INTEGER', None),
    ('scouting_team_settings', 'locked_at', 'DATETIME', None),
    ('scouting_team_settings', 'created_at', 'DATETIME', None),
    ('scouting_team_settings', 'updated_at', 'DATETIME', None),
    
    # -------------------------------------------------------------------------
    # StrategyDrawing table migrations (default bind)
    # -------------------------------------------------------------------------
    ('strategy_drawing', 'scouting_team_number', 'INTEGER', None),
    ('strategy_drawing', 'background_image', 'VARCHAR(256)', None),
    
    # -------------------------------------------------------------------------
    # TeamListEntry table migrations (default bind)
    # -------------------------------------------------------------------------
    ('team_list_entry', 'scouting_team_number', 'INTEGER', None),
    ('team_list_entry', 'rank', 'INTEGER DEFAULT 999', None),  # For WantListEntry priority ranking
    
    # -------------------------------------------------------------------------
    # AllianceSelection table migrations (default bind)
    # -------------------------------------------------------------------------
    ('alliance_selection', 'scouting_team_number', 'INTEGER', None),
    ('alliance_selection', 'third_pick', 'INTEGER', None),
    
    # -------------------------------------------------------------------------
    # ScoutingAlliance table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_alliance', 'game_config_team', 'INTEGER', None),
    ('scouting_alliance', 'pit_config_team', 'INTEGER', None),
    ('scouting_alliance', 'config_status', "VARCHAR(50) DEFAULT 'pending'", None),
    ('scouting_alliance', 'shared_game_config', 'TEXT', None),
    ('scouting_alliance', 'shared_pit_config', 'TEXT', None),
    
    # -------------------------------------------------------------------------
    # ScoutingAllianceMember table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_alliance_member', 'is_data_sharing_active', 'BOOLEAN DEFAULT 1', None),
    ('scouting_alliance_member', 'data_sharing_deactivated_at', 'DATETIME', None),
    ('scouting_alliance_member', 'team_name', 'VARCHAR(100)', None),
    
    # -------------------------------------------------------------------------
    # ScoutingAllianceEvent table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_alliance_event', 'added_by', 'INTEGER', None),
    
    # -------------------------------------------------------------------------
    # ScoutingAllianceChat table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_alliance_chat', 'is_read', 'BOOLEAN DEFAULT 0', None),
    
    # -------------------------------------------------------------------------
    # AllianceSharedScoutingData table migrations (default bind)
    # -------------------------------------------------------------------------
    ('alliance_shared_scouting_data', 'scout_id', 'INTEGER', None),
    ('alliance_shared_scouting_data', 'last_edited_by_team', 'INTEGER', None),
    ('alliance_shared_scouting_data', 'last_edited_at', 'DATETIME', None),
    
    # -------------------------------------------------------------------------
    # AllianceSharedPitData table migrations (default bind)
    # -------------------------------------------------------------------------
    ('alliance_shared_pit_data', 'scout_id', 'INTEGER', None),
    ('alliance_shared_pit_data', 'last_edited_by_team', 'INTEGER', None),
    ('alliance_shared_pit_data', 'last_edited_at', 'DATETIME', None),
    
    # -------------------------------------------------------------------------
    # TeamAllianceStatus table migrations (default bind)
    # -------------------------------------------------------------------------
    ('team_alliance_status', 'activated_at', 'DATETIME', None),
    ('team_alliance_status', 'deactivated_at', 'DATETIME', None),
    
    # -------------------------------------------------------------------------
    # Team table per-team starting points
    # -------------------------------------------------------------------------
    ('team', 'starting_points', 'FLOAT DEFAULT 0', None),
    ('team', 'starting_points_threshold', 'INTEGER DEFAULT 2', None),
    ('team', 'starting_points_enabled', 'BOOLEAN DEFAULT 0', None),
    # -------------------------------------------------------------------------

    # SharedGraph table migrations (default bind)
    # -------------------------------------------------------------------------
    ('shared_graph', 'allow_comments', 'BOOLEAN DEFAULT 0', None),
    
    # -------------------------------------------------------------------------
    # StrategyShare table migrations (default bind)
    # -------------------------------------------------------------------------
    ('strategy_share', 'created_by', 'INTEGER', None),
    ('strategy_share', 'revoked', 'BOOLEAN DEFAULT 0', None),
    
    # -------------------------------------------------------------------------
    # SyncServer table migrations (default bind)
    # -------------------------------------------------------------------------
    ('sync_servers', 'server_version', 'VARCHAR(50)', None),
    ('sync_servers', 'server_id', 'VARCHAR(100)', None),
    ('sync_servers', 'sync_enabled', 'BOOLEAN DEFAULT 1', None),
    ('sync_servers', 'sync_database', 'BOOLEAN DEFAULT 1', None),
    ('sync_servers', 'sync_instance_files', 'BOOLEAN DEFAULT 1', None),
    ('sync_servers', 'sync_config_files', 'BOOLEAN DEFAULT 1', None),
    ('sync_servers', 'sync_uploads', 'BOOLEAN DEFAULT 1', None),
    ('sync_servers', 'connection_timeout', 'INTEGER DEFAULT 30', None),
    ('sync_servers', 'retry_attempts', 'INTEGER DEFAULT 3', None),
    ('sync_servers', 'last_error', 'TEXT', None),
    ('sync_servers', 'error_count', 'INTEGER DEFAULT 0', None),
    
    # -------------------------------------------------------------------------
    # SyncLog table migrations (default bind)
    # -------------------------------------------------------------------------
    ('sync_logs', 'sync_details', 'TEXT', None),
    ('sync_logs', 'bytes_transferred', 'BIGINT DEFAULT 0', None),
    
    # -------------------------------------------------------------------------
    # LoginAttempt table migrations (default bind)
    # -------------------------------------------------------------------------
    ('login_attempts', 'team_number', 'INTEGER', None),
    ('login_attempts', 'user_agent', 'VARCHAR(500)', None),
    
    # -------------------------------------------------------------------------
    # ScoutingDirectMessage table migrations (default bind)
    # -------------------------------------------------------------------------
    ('scouting_direct_message', 'offline_id', 'VARCHAR(36)', None),
    
    # -------------------------------------------------------------------------
    # CustomPage table migrations (pages bind)
    # -------------------------------------------------------------------------
    ('custom_page', 'updated_at', 'DATETIME', 'pages'),
    ('custom_page', 'is_active', 'BOOLEAN DEFAULT 1', 'pages'),
    
    # -------------------------------------------------------------------------
    # DatabaseChange table migrations (default bind)
    # -------------------------------------------------------------------------
    ('database_changes', 'old_data', 'TEXT', None),
    ('database_changes', 'created_by_server', 'VARCHAR(100)', None),
    
    # -------------------------------------------------------------------------
    # FileChecksum table migrations (default bind)
    # -------------------------------------------------------------------------
    ('file_checksums', 'sync_status', "VARCHAR(20) DEFAULT 'synced'", None),
    
    # -------------------------------------------------------------------------
    # SharedTeamRanks table migrations (default bind)
    # -------------------------------------------------------------------------
    ('shared_team_ranks', 'allow_comments', 'BOOLEAN DEFAULT 0', None),
    
    # -------------------------------------------------------------------------
    # Notification models (misc bind)
    # -------------------------------------------------------------------------
    ('notification_subscription', 'updated_at', 'DATETIME', 'misc'),
    ('device_token', 'updated_at', 'DATETIME', 'misc'),
    ('notification_queue', 'updated_at', 'DATETIME', 'misc'),
]


def get_engine_for_bind(db, bind_key):
    """Get the appropriate engine for the given bind key."""
    from flask import current_app
    try:
        if bind_key is None:
            return db.engine
        else:
            return db.get_engine(current_app._get_current_object(), bind=bind_key)
    except Exception:
        return db.engine


def get_table_columns(engine, table_name):
    """Get list of column names for a table."""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if table_name not in tables:
            return None  # Table doesn't exist
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return columns
    except Exception as e:
        print(f"  Warning: Could not inspect table {table_name}: {e}")
        return None


def add_column(engine, table_name, column_name, column_sql):
    """Add a column to a table if it doesn't exist."""
    try:
        with engine.connect() as conn:
            # Use proper SQLite syntax for ALTER TABLE
            sql = f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}'
            conn.execute(text(sql))
            conn.commit()
        return True
    except Exception as e:
        # Column might already exist or other error
        error_msg = str(e).lower()
        if 'duplicate column' in error_msg or 'already exists' in error_msg:
            return True  # Column exists, that's fine
        print(f"  Warning: Could not add column {column_name} to {table_name}: {e}")
        return False


def run_migrations_for_bind(db, bind_key, migrations):
    """Run all migrations for a specific database bind."""
    engine = get_engine_for_bind(db, bind_key)
    bind_name = bind_key or 'default'
    
    # Group migrations by table
    table_migrations = {}
    for table_name, column_name, column_sql, m_bind in migrations:
        if m_bind == bind_key:
            if table_name not in table_migrations:
                table_migrations[table_name] = []
            table_migrations[table_name].append((column_name, column_sql))
    
    if not table_migrations:
        return 0
    
    columns_added = 0
    
    for table_name, column_list in table_migrations.items():
        # Get existing columns
        existing_columns = get_table_columns(engine, table_name)
        
        if existing_columns is None:
            # Table doesn't exist - skip migrations (table will be created by db.create_all())
            continue
        
        for column_name, column_sql in column_list:
            if column_name not in existing_columns:
                print(f"  Adding column {table_name}.{column_name}...")
                if add_column(engine, table_name, column_name, column_sql):
                    columns_added += 1
    
    return columns_added


def run_all_migrations(db):
    """Run all database migrations across all binds."""
    print("Checking for database schema migrations...")
    
    total_columns_added = 0
    
    # Get unique bind keys from migrations
    bind_keys = set(m[3] for m in MIGRATIONS)
    
    for bind_key in bind_keys:
        bind_name = bind_key or 'default'
        try:
            columns_added = run_migrations_for_bind(db, bind_key, MIGRATIONS)
            if columns_added > 0:
                print(f"  Added {columns_added} columns to {bind_name} database")
            total_columns_added += columns_added
        except Exception as e:
            print(f"  Warning: Migration check for {bind_name} database failed: {e}")
    
    if total_columns_added > 0:
        print(f"Database migration complete: {total_columns_added} columns added")
    else:
        print("Database schema is up to date")
    
    return total_columns_added


def check_missing_columns(db):
    """Check for missing columns without making changes. Returns a list of missing columns."""
    missing = []
    
    # Get unique bind keys from migrations
    bind_keys = set(m[3] for m in MIGRATIONS)
    
    for bind_key in bind_keys:
        engine = get_engine_for_bind(db, bind_key)
        
        for table_name, column_name, column_sql, m_bind in MIGRATIONS:
            if m_bind != bind_key:
                continue
            
            existing_columns = get_table_columns(engine, table_name)
            if existing_columns is None:
                continue  # Table doesn't exist
            
            if column_name not in existing_columns:
                missing.append({
                    'table': table_name,
                    'column': column_name,
                    'sql': column_sql,
                    'bind': bind_key or 'default'
                })
    
    return missing


def column_exists_for_bind(db, bind_key, table_name, column_name):
    """Return True if the given column is present in the specified table for a bind."""
    engine = get_engine_for_bind(db, bind_key)
    cols = get_table_columns(engine, table_name)
    return bool(cols and column_name in cols)


def migrate_user_notification_prefs(db, remove_after=True):
    """Migrate legacy JSON user preference 'only_password_reset_emails' into DB users table.

    Returns the count of successfully migrated users.
    """
    try:
        from app.utils import user_prefs as user_prefs_util
        from app.models import User
    except Exception:
        return 0

    # Ensure the DB column exists before attempting migration
    try:
        if not column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
            return 0
    except Exception:
        return 0

    prefs = user_prefs_util.load_prefs() or {}
    changes = 0
    for uname, up in list(prefs.items()):
        if not isinstance(up, dict):
            continue
        if 'only_password_reset_emails' not in up:
            continue
        try:
            u = User.query.filter_by(username=uname).first()
        except Exception:
            u = None
        if not u:
            continue
        val = bool(up.get('only_password_reset_emails', False))
        try:
            if getattr(u, 'only_password_reset_emails', None) != val:
                u.only_password_reset_emails = val
                db.session.add(u)
                db.session.commit()
                changes += 1
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            continue
        # Optionally remove migrated key from JSON to keep file clean
        if remove_after:
            try:
                if 'only_password_reset_emails' in up:
                    del up['only_password_reset_emails']
                    prefs[uname] = up
            except Exception:
                pass

    if remove_after and changes > 0:
        try:
            user_prefs_util.save_prefs(prefs)
        except Exception:
            pass

    return changes
