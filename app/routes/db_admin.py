"""
Database Administration Routes for Concurrent SQLite Operations

This module provides admin routes to monitor and manage the concurrent
database operations, including CR-SQLite status and connection pool statistics.
"""

from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app import db
from app.utils.database_manager import concurrent_db_manager
from app.utils.concurrent_models import with_concurrent_db
# Instance DB helpers for multiple .db file management
from app.utils.instance_db import list_instance_db_files, backup_db_file, set_journal_mode
from datetime import datetime, timezone
import json
import os
import logging
from sqlalchemy import inspect
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Create blueprint
db_admin_bp = Blueprint('db_admin', __name__, url_prefix='/admin/database')

@db_admin_bp.route('/')
@login_required
def database_status():
    """Display database status and concurrent operations info"""
    if not current_user.has_role('superadmin'):
        flash('Super Admin access required', 'error')
        return redirect(url_for('main.index'))
    
    try:
        # Get database information
        db_info = concurrent_db_manager.get_database_info()
        
        # Get connection pool stats
        pool_stats = concurrent_db_manager.get_connection_stats()
        
        # Enumerate instance .db files for the admin interface
        try:
            db_files = list_instance_db_files()
        except Exception:
            db_files = []

        return render_template('admin/database_status.html',
                             db_info=db_info,
                             pool_stats=pool_stats,
                             db_files=db_files)
    except Exception as e:
        logger.error(f"Error getting database status: {e}")
        flash(f'Error retrieving database status: {str(e)}', 'error')
        return redirect(url_for('main.index'))

@db_admin_bp.route('/api/status')
@login_required
def api_database_status():
    """API endpoint for database status (for AJAX updates)"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        db_info = concurrent_db_manager.get_database_info()
        try:
            db_files = list_instance_db_files()
        except Exception:
            db_files = []

        # Map files to binds and enrich with crsqlite info when possible
        from flask import current_app as flask_current_app
        binds = flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {}
        default_uri = flask_current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        bind_map = {}
        # Build mapping from filename -> bind_key (or 'default')
        def _basename_of_uri(uri):
            try:
                if uri.startswith('sqlite:///'):
                    return os.path.basename(uri[10:])
            except Exception:
                pass
            return None

        default_basename = _basename_of_uri(default_uri)
        for k,v in binds.items():
            bname = _basename_of_uri(v)
            if bname:
                bind_map[bname] = k
        # Attach crsqlite info and pool stats per file/bind
        pool_stats_map = {}
        # Always include default engine stats
        pool_stats_map['default'] = concurrent_db_manager.get_connection_stats()

        for f in db_files:
            name = f.get('name')
            bind_key = bind_map.get(name)
            if not bind_key and name == default_basename:
                bind_key = 'default'
            if bind_key:
                try:
                    info = concurrent_db_manager.get_database_info(bind_key if bind_key != 'default' else None)
                    f['crsqlite_version'] = info.get('crsqlite_version')
                    f['concurrent_writes'] = info.get('concurrent_writes')
                except Exception:
                    f['crsqlite_version'] = None
                    f['concurrent_writes'] = None

                # Add pool stats for this bind key
                try:
                    key = bind_key if bind_key != 'default' else 'default'
                    pool_stats_map[key] = concurrent_db_manager.get_connection_stats(None if key=='default' else key)
                except Exception:
                    pool_stats_map[bind_key] = {
                        'pool_size': 'N/A', 'checked_in': 'N/A', 'checked_out': 'N/A', 'overflow': 'N/A'
                    }
            else:
                f['crsqlite_version'] = None
                f['concurrent_writes'] = None
        
        return jsonify({
            'success': True,
            'database_info': db_info,
            'pool_stats': pool_stats_map,
            'db_files': db_files
        })
    except Exception as e:
        logger.error(f"Error getting database status via API: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@db_admin_bp.route('/optimize', methods=['POST'])
@login_required
def optimize_database():
    """Optimize the database for better concurrent performance"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        concurrent_db_manager.optimize_database()
        flash('Database optimization completed successfully', 'success')
        return jsonify({'success': True, 'message': 'Database optimized'})
    except Exception as e:
        logger.error(f"Error optimizing database: {e}")
        return jsonify({
            'success': False,
            'error': f'Optimization failed: {str(e)}'
        }), 500

@db_admin_bp.route('/enable-wal', methods=['POST'])
@login_required
def enable_wal_mode():
    """Enable WAL mode for better concurrency"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        concurrent_db_manager.enable_wal_mode()
        flash('WAL mode enabled successfully', 'success')
        return jsonify({'success': True, 'message': 'WAL mode enabled'})
    except Exception as e:
        logger.error(f"Error enabling WAL mode: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to enable WAL mode: {str(e)}'
        }), 500

@db_admin_bp.route('/test-concurrent', methods=['POST'])
@login_required
def test_concurrent_operations():
    """Test concurrent database operations across all configured databases"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    results = {}
    try:
        from flask import current_app as flask_current_app
        # Build list of binds including default
        binds = {'default': flask_current_app.config.get('SQLALCHEMY_DATABASE_URI')}
        binds.update(flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {})

        for bind_key, uri in binds.items():
            bind_label = bind_key or 'default'
            try:
                # Try to obtain engine
                try:
                    engine = db.get_engine(flask_current_app._get_current_object(), bind=(None if bind_key == 'default' else bind_key))
                except Exception:
                    engine = db.engine

                # Simple read test
                read_ok = False
                try:
                    with engine.connect() as conn:
                        _ = conn.execute(db.text('SELECT 1')).scalar()
                        read_ok = True
                except Exception as e:
                    read_ok = False

                # Simple write test using TEMP table (connection-local)
                write_ok = False
                try:
                    with engine.connect() as conn:
                        conn.execute(db.text('CREATE TEMP TABLE IF NOT EXISTS temp_concurrent_test (id INTEGER)'))
                        conn.execute(db.text('INSERT INTO temp_concurrent_test (id) VALUES (1)'))
                        # No commit required for temp table in this connection; it will be cleaned up
                        write_ok = True
                except Exception as e:
                    write_ok = False

                # Check crsqlite status for this bind
                try:
                    db_info = concurrent_db_manager.get_database_info(bind_key if bind_key != 'default' else None)
                    crs = db_info.get('concurrent_writes')
                except Exception:
                    crs = None

                results[bind_label] = {
                    'read_ok': read_ok,
                    'write_ok': write_ok,
                    'concurrent_writes': crs
                }
            except Exception as e:
                results[bind_label] = {'error': str(e)}

        return jsonify({
            'success': True,
            'message': 'Concurrent tests completed',
            'results': results
        })
    except Exception as e:
        logger.error(f"Error testing concurrent operations across binds: {e}")
        return jsonify({
            'success': False,
            'error': f'Concurrent test failed: {str(e)}'
        }), 500

@db_admin_bp.route('/export', methods=['GET', 'POST'])
@login_required
def export_database():
    """Export entire database to JSON format (includes both users.db and scouting.db)"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        # Generic export across all configured SQLite engines (default + binds)
        export_data = {
            'export_timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '2.0',
            # Legacy 'tables' mapping is kept for backwards compatibility (merged view)
            'tables': {},
            # New 'databases' mapping contains per-bind tables and data
            'databases': {}
        }

        from flask import current_app as flask_current_app

        # Helper that tries a few ways to get an engine for a bind key. Some
        # Flask-SQLAlchemy versions interpret positional args differently so
        # prefer keyword calls and fallbacks to session.get_bind or db.engine.
        def _get_engine(bind_key=None):
            app_obj = flask_current_app._get_current_object()
            try:
                return db.get_engine(app_obj, bind=bind_key)
            except Exception:
                try:
                    # SQLAlchemy session-level bind
                    return db.session.get_bind(bind=bind_key)
                except Exception:
                    try:
                        return db.engine
                    except Exception:
                        raise

        # Build list of engines: default + each configured bind
        engines = {'default': _get_engine(None)}
        binds = flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {}
        for bind_key in binds.keys():
            try:
                engines[bind_key] = _get_engine(bind_key)
            except Exception:
                logger.warning(f"Could not get engine for bind '{bind_key}'")

        # For each engine, enumerate tables and dump rows
        for bind_key, engine in engines.items():
            try:
                with engine.connect() as conn:
                    tables = []
                    try:
                        result = conn.execute(db.text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
                        tables = [row[0] for row in result]
                    except Exception as e:
                        logger.warning(f"Could not list tables for bind {bind_key}: {e}")

                    export_data['databases'][bind_key] = {}
                    for table in tables:
                        try:
                            rows = []
                            sel = conn.execute(db.text(f'SELECT * FROM "{table}"'))

                            # Determine column keys robustly
                            keys = None
                            try:
                                if hasattr(sel, 'keys'):
                                    keys = list(sel.keys())
                            except Exception:
                                keys = None

                            for r in sel:
                                try:
                                    # Prefer Row._mapping when available (SQLAlchemy Row)
                                    if hasattr(r, '_mapping'):
                                        rowdict = dict(r._mapping)
                                    elif keys:
                                        rowdict = {k: r[idx] for idx, k in enumerate(keys)}
                                    else:
                                        rowdict = dict(enumerate(r))
                                except Exception as e_row:
                                    # Best-effort fallback
                                    logger.warning(f"Failed to convert row for table {table} on bind {bind_key}: {e_row}")
                                    try:
                                        rowdict = dict(enumerate(r))
                                    except Exception:
                                        rowdict = {}

                                rows.append(rowdict)

                            export_data['databases'][bind_key][table] = rows

                            # Also merge into legacy top-level 'tables' (append/extend)
                            if table not in export_data['tables']:
                                export_data['tables'][table] = rows
                            else:
                                export_data['tables'][table].extend(rows)
                        except Exception as e:
                            logger.exception(f"Error exporting table {table} on bind {bind_key}")
                            export_data['databases'][bind_key][table] = []
            except Exception as e:
                logger.exception(f"Error processing engine for bind {bind_key}")
        
        # Generate filename with timestamp
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f'database_export_{timestamp}.json'
        
        # Create JSON string
        json_data = json.dumps(export_data, ensure_ascii=False, indent=2, default=str)
        
        # Create response with download headers
        from flask import Response
        response = Response(
            json_data,
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': len(json_data.encode('utf-8'))
            }
        )
        
        logger.info(f'Database exported successfully as downloadable file: {filename}')
        return response
        
    except Exception as e:
        logger.exception("Error exporting database")
        return jsonify({
            'success': False,
            'error': f'Export failed: {str(e)}'
        }), 500

@db_admin_bp.route('/import', methods=['POST'])
@login_required
def import_database():
    """Import database from JSON file (handles both users.db and scouting.db)"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        if 'import_file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['import_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Read and parse JSON
        import_data = json.load(file)
        
        # Support both legacy export format ('tables') and new bind-aware format ('databases')
        if 'tables' not in import_data and 'databases' not in import_data:
            return jsonify({'error': 'Invalid export file format'}), 400
        
        # If the import file has a per-database export (new format), handle that generically
        from flask import current_app as flask_current_app

        # Local helper to obtain engines robustly (same approach as export)
        def _get_engine(bind_key=None):
            app_obj = flask_current_app._get_current_object()
            try:
                return db.get_engine(app_obj, bind=bind_key)
            except Exception:
                try:
                    return db.session.get_bind(bind=bind_key)
                except Exception:
                    try:
                        return db.engine
                    except Exception:
                        raise

        if 'databases' in import_data and isinstance(import_data['databases'], dict):
            try:
                binds = flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {}
                # Build engine map (key -> engine). Use key 'default' for main DB.
                engines = {'default': _get_engine(None)}
                for bind_key in binds.keys():
                    try:
                        engines[bind_key] = _get_engine(bind_key)
                    except Exception:
                        logger.warning(f"Could not get engine for bind '{bind_key}' during import")

                # First, clear tables on each engine (disable foreign keys), then insert
                for bind_key, tables in import_data['databases'].items():
                    engine = engines.get(bind_key) or engines.get('default')
                    if not engine:
                        logger.warning(f"No engine found for bind {bind_key}, skipping")
                        continue

                    # Validate table names
                    try:
                        inspector = inspect(engine)
                        valid_tables = set(inspector.get_table_names())
                    except Exception as e:
                        logger.warning(f"Could not inspect tables for bind {bind_key}: {e}")
                        continue

                    with engine.begin() as conn:
                        try:
                            conn.execute(db.text('PRAGMA foreign_keys = OFF'))
                        except Exception:
                            pass

                        # Delete existing rows for the listed tables (order doesn't matter with FK off)
                        for table_name, rows in tables.items():
                            if table_name not in valid_tables:
                                logger.warning(f"Skipping invalid table {table_name} on bind {bind_key}")
                                continue
                            try:
                                conn.execute(db.text(f'DELETE FROM "{table_name}"'))
                            except Exception as e:
                                logger.warning(f"Could not clear table {table_name} on bind {bind_key}: {e}")

                        # Insert rows
                        for table_name, rows in tables.items():
                            if table_name not in valid_tables:
                                continue
                            if not rows:
                                continue
                            try:
                                # Determine columns from first row and validate against schema
                                try:
                                    valid_columns = {c['name'] for c in inspector.get_columns(table_name)}
                                except Exception:
                                    logger.warning(f"Could not inspect columns for table {table_name}")
                                    continue

                                cols = list(rows[0].keys())
                                safe_cols = [c for c in cols if c in valid_columns]
                                
                                if not safe_cols:
                                    continue

                                cols_quoted = ','.join([f'"{c}"' for c in safe_cols])
                                placeholders = ','.join([f':{c}' for c in safe_cols])
                                insert_sql = db.text(f'INSERT INTO "{table_name}" ({cols_quoted}) VALUES ({placeholders})')
                                for r in rows:
                                    try:
                                        # Convert any non-serializable types minimally (e.g., bytes)
                                        params = {}
                                        for k in safe_cols:
                                            v = r.get(k)
                                            if isinstance(v, bytes):
                                                params[k] = v.decode('utf-8', errors='ignore')
                                            else:
                                                params[k] = v
                                        conn.execute(insert_sql, params)
                                    except Exception as ie:
                                        logger.warning(f"Failed to insert row into {table_name} on bind {bind_key}: {ie}")
                            except Exception as e:
                                logger.warning(f"Failed to import table {table_name} on bind {bind_key}: {e}")

                        try:
                            # Reset sqlite_sequence for this engine to avoid PK collisions
                            conn.execute(db.text('DELETE FROM sqlite_sequence'))
                        except Exception:
                            pass

                        try:
                            conn.execute(db.text('PRAGMA foreign_keys = ON'))
                        except Exception:
                            pass

                db.session.commit()
                flash('Database imported successfully (databases format)', 'success')
                return jsonify({'success': True, 'message': 'Database imported successfully (databases format)'}), 200
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error importing databases format: {e}")
                return jsonify({'success': False, 'error': f'Import failed: {str(e)}'}), 500

        # Fallback to legacy ORM-based import handling for 'tables' export
        from app.models import (
            User, Role, ScoutingTeamSettings, Team, Event, Match, 
            ScoutingData, TeamListEntry, DoNotPickEntry, AvoidEntry,
            AllianceSelection, PitScoutingData, StrategyDrawing,
            ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceInvitation,
            ScoutingAllianceEvent, ScoutingAllianceSync, ScoutingAllianceChat,
            TeamAllianceStatus, SharedGraph
        )
        
        # Clear existing data (in reverse order to handle foreign keys)
        models_to_clear = [
            ScoutingAllianceChat, ScoutingAllianceSync, ScoutingAllianceEvent,
            ScoutingAllianceInvitation, ScoutingAllianceMember, ScoutingAlliance,
            StrategyDrawing, PitScoutingData, AllianceSelection,
            AvoidEntry, DoNotPickEntry, TeamListEntry, ScoutingData,
            Match, Event, Team, ScoutingTeamSettings,
            TeamAllianceStatus, SharedGraph,
            User,  # Clear users (will recreate superadmin)
            Role   # Clear roles last
        ]
        
        # Store superadmin info before clearing
        superadmin_info = None
        superadmin_user = User.query.filter_by(username='superadmin').first()
        if superadmin_user:
            superadmin_info = {
                'username': superadmin_user.username,
                'password_hash': superadmin_user.password_hash,
                'email': superadmin_user.email,
                'scouting_team_number': superadmin_user.scouting_team_number,
                'is_active': superadmin_user.is_active,
                'must_change_password': superadmin_user.must_change_password,
                'profile_picture': superadmin_user.profile_picture,
                'created_at': superadmin_user.created_at,
                'updated_at': superadmin_user.updated_at,
                'last_login': superadmin_user.last_login,
                'roles': [role.name for role in superadmin_user.roles]
            }
        
        # Clear existing data more thoroughly
        from flask import current_app as flask_current_app
        for model_class in models_to_clear:
            try:
                # Use the proper engine for the model's bind (handles separate users DB)
                table_name = model_class.__tablename__
                bind_key = getattr(model_class, '__bind_key__', None)
                if bind_key:
                    try:
                        engine = _get_engine(bind_key)
                    except Exception:
                        engine = _get_engine(None)
                else:
                    engine = _get_engine(None)

                # Execute delete using a connection from the appropriate engine
                try:
                    with engine.begin() as conn:
                        conn.execute(db.text(f'DELETE FROM {table_name}'))
                    logger.info(f"Cleared table {table_name} (bind={bind_key or 'default'})")
                except Exception as inner_e:
                    # Log and continue; some tables may not exist on that bind
                    logger.warning(f"Error executing DELETE on {table_name} (bind={bind_key}): {inner_e}")
            except Exception as e:
                logger.warning(f"Error clearing table {model_class.__name__}: {e}")

        # Additional explicit clearing for ScoutingTeamSettings to ensure it's completely cleared
        try:
            scouting_engine = _get_engine(None)
            with scouting_engine.begin() as conn:
                # Check how many records exist before clearing
                result = conn.execute(db.text('SELECT COUNT(*) FROM scouting_team_settings'))
                count_before = result.fetchone()[0]
                if count_before > 0:
                    logger.warning(f"Found {count_before} records in scouting_team_settings before explicit clearing")
                
                conn.execute(db.text('DELETE FROM scouting_team_settings'))
                
                # Verify clearing was successful
                result = conn.execute(db.text('SELECT COUNT(*) FROM scouting_team_settings'))
                count_after = result.fetchone()[0]
                if count_after > 0:
                    logger.error(f"Failed to clear scouting_team_settings table - {count_after} records remain")
                else:
                    logger.info("Successfully cleared scouting_team_settings table")
        except Exception as e:
            logger.warning(f"Error in explicit clearing of scouting_team_settings: {e}")

        # Reset auto-increment counters for each SQLite file/engine used
        try:
            engines = [_get_engine(None)]
            # Add configured binds (e.g., 'users') if present
            binds = flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {}
            for bind_key in binds.keys():
                try:
                    engines.append(_get_engine(bind_key))
                except Exception:
                    pass

            for engine in engines:
                try:
                    with engine.begin() as conn:
                        conn.execute(db.text('DELETE FROM sqlite_sequence'))
                    logger.info("Reset auto-increment counters on engine")
                except Exception as e:
                    logger.warning(f"Error resetting auto-increment on engine: {e}")
        except Exception as e:
            logger.warning(f"Error preparing auto-increment reset: {e}")

        db.session.commit()
        
        # Import data (in dependency order)
        import_order = [
            (Role, 'roles'),
            (User, 'users'),
            (ScoutingTeamSettings, 'scouting_team_settings'),
            (Team, 'teams'),
            (Event, 'events'),
            (Match, 'matches'),
            (ScoutingData, 'scouting_data'),
            (TeamListEntry, 'team_list_entries'),
            (DoNotPickEntry, 'do_not_pick_entries'),
            (AvoidEntry, 'avoid_entries'),
            (AllianceSelection, 'alliance_selections'),
            (PitScoutingData, 'pit_scouting_data'),
            (StrategyDrawing, 'strategy_drawings'),
            (ScoutingAlliance, 'scouting_alliances'),
            (ScoutingAllianceMember, 'scouting_alliance_members'),
            (ScoutingAllianceInvitation, 'scouting_alliance_invitations'),
            (ScoutingAllianceEvent, 'scouting_alliance_events'),
            (ScoutingAllianceSync, 'scouting_alliance_syncs'),
            (ScoutingAllianceChat, 'scouting_alliance_chats'),
            (TeamAllianceStatus, 'team_alliance_status'),
            (SharedGraph, 'shared_graphs')
        ]
        
        imported_counts = {}
        for model_class, table_name in import_order:
            if table_name in import_data['tables']:
                count = 0
                seen_scouting_team_numbers = set()  # Track scouting_team_numbers to prevent duplicates
                
                for record_data in import_data['tables'][table_name]:
                    try:
                        # Special handling for ScoutingTeamSettings to prevent duplicate scouting_team_number
                        if table_name == 'scouting_team_settings':
                            scouting_team_number = record_data.get('scouting_team_number')
                            if scouting_team_number in seen_scouting_team_numbers:
                                logger.warning(f"Skipping duplicate scouting_team_number {scouting_team_number} in import data")
                                continue
                            seen_scouting_team_numbers.add(scouting_team_number)
                        
                        # Create new record
                        record = model_class()
                        for key, value in record_data.items():
                            if hasattr(record, key):
                                # Handle datetime fields
                                datetime_field_names = [
                                    'created_at', 'updated_at', 'last_login', 'timestamp',
                                    'locked_at', 'upload_timestamp', 'last_updated', 
                                    'joined_at', 'responded_at', 'added_at', 'last_sync',
                                    'activated_at', 'deactivated_at', 'expires_at'
                                ]
                                if key in datetime_field_names and value:
                                    if isinstance(value, str):
                                        try:
                                            from datetime import datetime
                                            # Handle different datetime formats
                                            if 'T' in value:
                                                # ISO format: 2025-08-29T20:49:46.109124
                                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                            elif ' ' in value and len(value.split()) == 2:
                                                # Space-separated format: 2025-08-25 18:19:48.222682
                                                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
                                            else:
                                                # Fallback to current time if parsing fails
                                                value = datetime.now(timezone.utc)
                                        except (ValueError, TypeError):
                                            # If parsing fails, set to current time
                                            value = datetime.now(timezone.utc)
                                
                                # Skip ID field to avoid conflicts - let database auto-generate
                                if key != 'id':
                                    setattr(record, key, value)
                        
                        db.session.add(record)
                        count += 1
                    except Exception as e:
                        logger.warning(f"Error importing record for {table_name}: {e}")
                        logger.warning(f"Record data: {record_data}")
                        # Continue with next record instead of failing completely
                        continue
                imported_counts[table_name] = count
                logger.info(f"Imported {count} records for {table_name}")
        
        # Commit after importing all tables
        try:
            db.session.commit()
            logger.info("Database import committed successfully")
        except Exception as e:
            logger.error(f"Error committing import: {e}")
            db.session.rollback()
            raise
        
        # Handle user-role relationships after both are imported
        if 'users' in import_data['tables'] and 'user_roles' in import_data.get('tables', {}):
            try:
                # Clear existing user-role relationships (users bind)
                try:
                    users_engine = _get_engine('users')
                except Exception:
                    users_engine = _get_engine(None)
                try:
                    with users_engine.begin() as conn:
                        conn.execute(db.text('DELETE FROM user_roles'))
                except Exception:
                    # Fall back to session-level delete if the raw table isn't present
                    try:
                        db.session.execute(db.text('DELETE FROM user_roles'))
                    except Exception:
                        pass

                # Restore user-role relationships
                for user_role_data in import_data['tables']['user_roles']:
                    try:
                        user_id = user_role_data.get('user_id')
                        role_id = user_role_data.get('role_id')

                        # Find the user and role by their original IDs or by matching data
                        user = User.query.filter_by(id=user_id).first()
                        role = Role.query.filter_by(id=role_id).first()

                        if user and role and role not in user.roles:
                            user.roles.append(role)
                    except Exception as e:
                        logger.warning(f"Error restoring user-role relationship: {e}")

                db.session.commit()
                logger.info("User-role relationships restored")
            except Exception as e:
                logger.error(f"Error handling user-role relationships: {e}")
        
        # Handle team-event relationships after both are imported
        if 'teams' in import_data['tables'] and 'events' in import_data['tables'] and 'team_event' in import_data.get('tables', {}):
            try:
                # Clear existing team-event relationships (default bind)
                try:
                    default_engine = _get_engine(None)
                except Exception:
                    default_engine = db.engine
                try:
                    with default_engine.begin() as conn:
                        conn.execute(db.text('DELETE FROM team_event'))
                except Exception:
                    # Fall back to session-level delete if the raw table isn't present
                    try:
                        db.session.execute(db.text('DELETE FROM team_event'))
                    except Exception:
                        pass
                
                # Restore team-event relationships
                for team_event_data in import_data['tables']['team_event']:
                    try:
                        team_id = team_event_data.get('team_id')
                        event_id = team_event_data.get('event_id')
                        
                        # Find the team and event by their original IDs
                        team = Team.query.filter_by(id=team_id).first()
                        event = Event.query.filter_by(id=event_id).first()
                        
                        if team and event and event not in team.events:
                            team.events.append(event)
                    except Exception as e:
                        logger.warning(f"Error restoring team-event relationship: {e}")
                
                db.session.commit()
                logger.info("Team-event relationships restored")
            except Exception as e:
                logger.error(f"Error handling team-event relationships: {e}")
        
        # Recreate superadmin if it was stored and not in imported data
        if superadmin_info:
            try:
                # Check if superadmin already exists in imported data
                existing_superadmin = User.query.filter_by(username='superadmin').first()
                if not existing_superadmin:
                    # Recreate superadmin user
                    superadmin_user = User(
                        username=superadmin_info['username'],
                        password_hash=superadmin_info['password_hash'],
                        email=superadmin_info.get('email'),
                        scouting_team_number=superadmin_info.get('scouting_team_number'),
                        is_active=superadmin_info.get('is_active', True),
                        must_change_password=superadmin_info.get('must_change_password', False),
                        profile_picture=superadmin_info.get('profile_picture'),
                        created_at=superadmin_info.get('created_at'),
                        updated_at=superadmin_info.get('updated_at'),
                        last_login=superadmin_info.get('last_login')
                    )
                    
                    # Recreate superadmin roles
                    for role_name in superadmin_info.get('roles', ['superadmin']):
                        role = Role.query.filter_by(name=role_name).first()
                        if not role:
                            role = Role(name=role_name, description=f'Imported {role_name} role')
                            db.session.add(role)
                        superadmin_user.roles.append(role)
                    
                    db.session.add(superadmin_user)
                    db.session.commit()
                    logger.info("Superadmin user recreated after import")
            except Exception as e:
                logger.error(f"Error recreating superadmin: {e}")
        
        flash('Database imported successfully', 'success')
        return jsonify({
            'success': True,
            'message': 'Database imported successfully',
            'imported_counts': imported_counts
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error importing database: {e}")
        error_message = f'Import failed: {str(e)}'
        
        # Provide more specific error messages for common issues
        if 'UNIQUE constraint failed' in str(e):
            error_message += '\n\nThis usually means the database was not cleared properly. Try clearing the database first, then import again.'
        elif 'datetime' in str(e).lower():
            error_message += '\n\nThis appears to be a datetime parsing issue. The export file may be corrupted.'
        elif 'foreign key' in str(e).lower():
            error_message += '\n\nThis is a foreign key constraint error. Make sure all referenced data exists.'
        
        return jsonify({
            'success': False,
            'error': error_message
        }), 500

@db_admin_bp.route('/clear', methods=['POST'])
@login_required
def clear_database():
    """Clear all scouting data from database (preserves users and roles in users.db)"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        from app.models import (
            User, Role, ScoutingTeamSettings, Team, Event, Match, 
            ScoutingData, TeamListEntry, DoNotPickEntry, AvoidEntry,
            AllianceSelection, PitScoutingData, StrategyDrawing,
            ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceInvitation,
            ScoutingAllianceEvent, ScoutingAllianceSync, ScoutingAllianceChat,
            TeamAllianceStatus, SharedGraph
        )
        
        # Clear all tables except users and roles (keep superadmin)
        models_to_clear = [
            ScoutingAllianceChat, ScoutingAllianceSync, ScoutingAllianceEvent,
            ScoutingAllianceInvitation, ScoutingAllianceMember, ScoutingAlliance,
            StrategyDrawing, PitScoutingData, AllianceSelection, 
            AvoidEntry, DoNotPickEntry, TeamListEntry, ScoutingData,
            Match, Event, Team, ScoutingTeamSettings, 
            TeamAllianceStatus, SharedGraph
        ]
        
        cleared_counts = {}
        from flask import current_app as flask_current_app
        # Helper for clear_database to obtain engines robustly
        def _get_engine_clear(bind_key=None):
            app_obj = flask_current_app._get_current_object()
            try:
                return db.get_engine(app_obj, bind=bind_key)
            except Exception:
                try:
                    return db.session.get_bind(bind=bind_key)
                except Exception:
                    try:
                        return db.engine
                    except Exception:
                        raise
        
        # Clear tables from default bind (scouting.db) using raw SQL for consistency
        for model_class in models_to_clear:
            try:
                table_name = model_class.__tablename__
                bind_key = getattr(model_class, '__bind_key__', None)
                if bind_key:
                    try:
                        engine = _get_engine_clear(bind_key)
                    except Exception:
                        engine = _get_engine_clear(None)
                else:
                    engine = _get_engine_clear(None)

                # Get count before clearing
                try:
                    with engine.begin() as conn:
                        result = conn.execute(db.text(f'SELECT COUNT(*) FROM {table_name}'))
                        count = result.fetchone()[0]
                except Exception:
                    count = 0

                # Execute delete using raw SQL
                try:
                    with engine.begin() as conn:
                        conn.execute(db.text(f'DELETE FROM {table_name}'))
                    cleared_counts[model_class.__name__] = count
                    logger.info(f"Cleared {count} records from {table_name}")
                except Exception as inner_e:
                    logger.warning(f"Error executing DELETE on {table_name}: {inner_e}")
                    cleared_counts[model_class.__name__] = 0
            except Exception as e:
                logger.warning(f"Error clearing table {model_class.__name__}: {e}")
                cleared_counts[model_class.__name__] = 0
        
        # Also clear association tables that might not be covered by the models above
        try:
            # Clear team_event association table
            default_engine = _get_engine_clear(None)
            with default_engine.begin() as conn:
                conn.execute(db.text('DELETE FROM team_event'))
            logger.info("Cleared team_event association table")
        except Exception as e:
            logger.warning(f"Error clearing team_event table: {e}")
        
        # Explicitly clear scouting_team_settings to ensure complete clearing
        try:
            scouting_engine = _get_engine_clear(None)
            with scouting_engine.begin() as conn:
                # Check how many records exist before clearing
                result = conn.execute(db.text('SELECT COUNT(*) FROM scouting_team_settings'))
                count_before = result.fetchone()[0]
                if count_before > 0:
                    logger.info(f"Clearing {count_before} records from scouting_team_settings")
                
                conn.execute(db.text('DELETE FROM scouting_team_settings'))
                
                # Verify clearing was successful
                result = conn.execute(db.text('SELECT COUNT(*) FROM scouting_team_settings'))
                count_after = result.fetchone()[0]
                if count_after > 0:
                    logger.error(f"Failed to clear scouting_team_settings table - {count_after} records remain")
                    cleared_counts['ScoutingTeamSettings'] = count_before - count_after
                else:
                    logger.info("Successfully cleared scouting_team_settings table")
                    cleared_counts['ScoutingTeamSettings'] = count_before
        except Exception as e:
            logger.warning(f"Error clearing scouting_team_settings: {e}")
            cleared_counts['ScoutingTeamSettings'] = 0
        
        # Clear user-related tables from users bind if they exist and we want to clear them
        # Note: This preserves the superadmin user by not clearing User/Role tables
        # If you want to clear ALL data including users, uncomment the following:
        """
        try:
            users_engine = db.get_engine(flask_current_app._get_current_object(), bind='users')
            with users_engine.begin() as conn:
                # Clear user_roles association table
                conn.execute(db.text('DELETE FROM user_roles'))
                # Reset auto-increment for users bind
                conn.execute(db.text('DELETE FROM sqlite_sequence'))
            logger.info("Cleared user_roles association table from users bind")
        except Exception as e:
            logger.warning(f"Error clearing user_roles from users bind: {e}")
        """
        
        db.session.commit()
        
        flash('Database cleared successfully (superadmin preserved)', 'success')
        return jsonify({
            'success': True,
            'message': 'Database cleared successfully',
            'cleared_counts': cleared_counts
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing database: {e}")
        return jsonify({
            'success': False,
            'error': f'Clear failed: {str(e)}'
        }), 500

# Add error handlers
@db_admin_bp.route('/api/files')
@login_required
def api_database_files():
    """Return JSON list of .db files in instance folder"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    try:
        files = list_instance_db_files()
        return jsonify({'success': True, 'files': files})
    except Exception as e:
        logger.error(f"Error listing instance DB files: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@db_admin_bp.route('/files/backup', methods=['POST'])
@login_required
def backup_database_file():
    """Backup a selected .db file (creates timestamped copy in instance/backup)"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    data = request.get_json() or request.form
    filename = data.get('filename')
    if not filename:
        return jsonify({'success': False, 'error': 'No filename provided'}), 400
    try:
        backup_path = backup_db_file(filename)
        flash(f'Backup created: {backup_path}', 'success')
        return jsonify({'success': True, 'backup': backup_path})
    except Exception as e:
        logger.exception(f"Error creating backup for {filename}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@db_admin_bp.route('/files/set-journal', methods=['POST'])
@login_required
def set_journal():
    """Set PRAGMA journal_mode for a given DB file"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    data = request.get_json() or request.form
    filename = data.get('filename')
    mode = (data.get('mode') or 'wal').strip()
    if not filename:
        return jsonify({'success': False, 'error': 'No filename provided'}), 400
    try:
        result = set_journal_mode(filename, mode)
        flash(f'Journal mode set to {result} for {filename}', 'success')
        return jsonify({'success': True, 'mode': result})
    except Exception as e:
        logger.exception(f"Error setting journal mode for {filename}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@db_admin_bp.route('/files/enable-crsqlite', methods=['POST'])
@login_required
def enable_crsqlite():
    """Enable/load CR-SQLite extension for a given DB file or bind"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    data = request.get_json() or request.form
    filename = data.get('filename')
    bind_key = data.get('bind_key')

    # Map filename to bind if provided but bind_key not given
    if not bind_key and filename:
        from flask import current_app as flask_current_app
        binds = flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {}
        default_uri = flask_current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        def _basename_of_uri(uri):
            try:
                if uri.startswith('sqlite:///'):
                    return os.path.basename(uri[10:])
            except Exception:
                pass
            return None
        default_basename = _basename_of_uri(default_uri)
        for k,v in binds.items():
            bname = _basename_of_uri(v)
            if bname and bname == filename:
                bind_key = k
                break
        if not bind_key and filename == default_basename:
            bind_key = None

    # Now attempt to enable
    try:
        result = concurrent_db_manager.enable_crsqlite_on_bind(bind_key)
        # Return diagnostics (message, loaded flag, probe_value) so UI can show why it may still be unavailable
        msg = result.get('message', 'Unknown result')
        if result.get('success'):
            flash(f"CR-SQLite enabled on {filename or bind_key or 'default'}: {msg}", 'success')
            return jsonify({
                'success': True,
                'message': msg,
                'loaded': result.get('loaded'),
                'probe_value': result.get('probe_value')
            })
        else:
            logger.warning(f"CR-SQLite enable for {filename or bind_key or 'default'} - success=False: {msg}")
            return jsonify({
                'success': False,
                'error': msg,
                'loaded': result.get('loaded'),
                'probe_value': result.get('probe_value')
            }), 500
    except Exception as e:
        logger.exception(f"Error enabling CR-SQLite for {filename or bind_key}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@db_admin_bp.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@db_admin_bp.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500
