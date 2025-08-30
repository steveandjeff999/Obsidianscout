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
from datetime import datetime
import json
import os
import logging
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
        
        return render_template('admin/database_status.html',
                             db_info=db_info,
                             pool_stats=pool_stats)
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
        pool_stats = concurrent_db_manager.get_connection_stats()
        
        return jsonify({
            'success': True,
            'database_info': db_info,
            'pool_stats': pool_stats
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
    """Test concurrent database operations"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        # Test concurrent reads
        @with_concurrent_db(readonly=True)
        def test_read():
            from app.models import User
            return User.concurrent_count()
        
        # Execute tests
        user_count = test_read()
        
        return jsonify({
            'success': True,
            'message': 'Concurrent read test completed',
            'results': {
                'user_count': user_count
            }
        })
        
    except Exception as e:
        logger.error(f"Error testing concurrent operations: {e}")
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
        from app.models import (
            User, Role, ScoutingTeamSettings, Team, Event, Match, 
            ScoutingData, TeamListEntry, DoNotPickEntry, AvoidEntry,
            AllianceSelection, PitScoutingData, StrategyDrawing,
            ScoutingAlliance, ScoutingAllianceMember, ScoutingAllianceInvitation,
            ScoutingAllianceEvent, ScoutingAllianceSync, ScoutingAllianceChat,
            TeamAllianceStatus, SharedGraph
        )
        
        # Collect all data from all tables
        export_data = {
            'export_timestamp': datetime.utcnow().isoformat(),
            'version': '1.0',
            'tables': {}
        }
        
        # Define all models to export
        models_to_export = [
            (User, 'users'),
            (Role, 'roles'),
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
        
        # Define all models to export
        models_to_export = [
            (User, 'users'),
            (Role, 'roles'),
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
        
        for model_class, table_name in models_to_export:
            try:
                records = model_class.query.all()
                export_data['tables'][table_name] = [
                    {column.name: getattr(record, column.name) 
                     for column in record.__table__.columns}
                    for record in records
                ]
            except Exception as e:
                logger.warning(f"Error exporting table {table_name}: {e}")
                export_data['tables'][table_name] = []
        
        # Export user_roles association table
        try:
            result = db.session.execute(db.text('SELECT user_id, role_id FROM user_roles'))
            export_data['tables']['user_roles'] = [
                {'user_id': row[0], 'role_id': row[1]} for row in result
            ]
        except Exception as e:
            logger.warning(f"Error exporting user_roles: {e}")
            export_data['tables']['user_roles'] = []
        
        # Export team_event association table
        try:
            result = db.session.execute(db.text('SELECT team_id, event_id FROM team_event'))
            export_data['tables']['team_event'] = [
                {'team_id': row[0], 'event_id': row[1]} for row in result
            ]
        except Exception as e:
            logger.warning(f"Error exporting team_event: {e}")
            export_data['tables']['team_event'] = []
        
        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
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
        logger.error(f"Error exporting database: {e}")
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
        
        if 'tables' not in import_data:
            return jsonify({'error': 'Invalid export file format'}), 400
        
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
                    engine = db.get_engine(flask_current_app._get_current_object(), bind=bind_key)
                else:
                    engine = db.get_engine(flask_current_app._get_current_object())

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
            scouting_engine = db.get_engine(flask_current_app._get_current_object())
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
            engines = [db.get_engine(flask_current_app._get_current_object())]
            # Add configured binds (e.g., 'users') if present
            binds = flask_current_app.config.get('SQLALCHEMY_BINDS', {}) or {}
            for bind_key in binds.keys():
                try:
                    engines.append(db.get_engine(flask_current_app._get_current_object(), bind=bind_key))
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
                                                value = datetime.utcnow()
                                        except (ValueError, TypeError):
                                            # If parsing fails, set to current time
                                            value = datetime.utcnow()
                                
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
                users_engine = db.get_engine(current_app._get_current_object(), bind='users')
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
                default_engine = db.get_engine(current_app._get_current_object())
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
        
        # Clear tables from default bind (scouting.db) using raw SQL for consistency
        for model_class in models_to_clear:
            try:
                table_name = model_class.__tablename__
                bind_key = getattr(model_class, '__bind_key__', None)
                if bind_key:
                    engine = db.get_engine(flask_current_app._get_current_object(), bind=bind_key)
                else:
                    engine = db.get_engine(flask_current_app._get_current_object())

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
            default_engine = db.get_engine(flask_current_app._get_current_object())
            with default_engine.begin() as conn:
                conn.execute(db.text('DELETE FROM team_event'))
            logger.info("Cleared team_event association table")
        except Exception as e:
            logger.warning(f"Error clearing team_event table: {e}")
        
        # Explicitly clear scouting_team_settings to ensure complete clearing
        try:
            scouting_engine = db.get_engine(flask_current_app._get_current_object())
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
@db_admin_bp.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@db_admin_bp.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500
