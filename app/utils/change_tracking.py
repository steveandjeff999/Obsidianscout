"""
Database change tracking for multi-server synchronization
"""
import json
import queue
import threading
from datetime import datetime
from sqlalchemy import event, text
from flask import current_app

# Global queue for change tracking operations
change_tracking_queue = queue.Queue()
change_tracking_worker = None
change_tracking_running = False
# Store a reference to the Flask application so background thread has context
_tracked_app = None

def start_change_tracking_worker():
    """Start the background worker for change tracking with proper app context"""
    global change_tracking_worker, change_tracking_running, _tracked_app

    if change_tracking_running:
        return

    # Capture current app object if inside an application context
    try:
        if _tracked_app is None and current_app:
            _tracked_app = current_app._get_current_object()
    except Exception:
        pass

    change_tracking_running = True

    def _worker():
        """Background worker that processes change tracking queue"""
        while change_tracking_running:
            try:
                operation = change_tracking_queue.get(timeout=1)

                # Ensure we have an application context for DB operations
                if _tracked_app is not None:
                    with _tracked_app.app_context():
                        _process_change_tracking(operation)
                else:
                    # Fallback: create a fresh app (heavier but keeps system functional)
                    try:
                        from app import create_app
                        app = create_app()
                        with app.app_context():
                            _process_change_tracking(operation)
                    except Exception as inner_e:
                        print(f"❌ Failed to create app context in worker: {inner_e}")

                change_tracking_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ Error in change tracking worker: {e}")
                try:
                    change_tracking_queue.task_done()
                except Exception:
                    pass
                continue

    change_tracking_worker = threading.Thread(target=_worker, daemon=True)
    change_tracking_worker.start()

def _process_change_tracking(operation):
    """Process a change tracking operation"""
    try:
        # Import here to avoid circular imports
        from app import db

        # Normalize operation casing before insert
        op = operation.get('operation')
        if op:
            operation['operation'] = op.lower()

        change_sql = text("""
            INSERT INTO database_changes (table_name, record_id, operation, change_data, old_data, timestamp, sync_status, created_by_server)
            VALUES (:table_name, :record_id, :operation, :change_data, :old_data, :timestamp, :sync_status, :created_by_server)
        """)

        with db.engine.connect() as conn:
            conn.execute(change_sql, operation)
            conn.commit()
    except Exception as e:
        print(f"❌ Error processing change tracking: {e}")

def _get_server_id():
    """Get the current server ID for change tracking"""
    try:
        if hasattr(current_app, 'config'):
            return current_app.config.get('SYNC_SERVER_ID', 'local')
        return 'local'
    except:
        return 'local'

def track_model_changes(model_class):
    """Add change tracking to a SQLAlchemy model"""
    
    # Start the worker if not already running
    start_change_tracking_worker()
    
    @event.listens_for(model_class, 'after_insert', propagate=True)
    def track_insert(mapper, connection, target):
        """Track record insertions with queue-based processing"""
        if not should_track_changes():
            return
        
        try:
            # Get record data
            record_data = {}
            for column in mapper.columns:
                value = getattr(target, column.name)
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif value is None:
                    value = None
                else:
                    # Convert to JSON-serializable type
                    value = str(value) if not isinstance(value, (str, int, float, bool, list, dict)) else value
                record_data[column.name] = value
            
            # Queue the operation for background processing
            operation = {
                'table_name': target.__tablename__,
                'record_id': str(target.id) if hasattr(target, 'id') else None,
                'operation': 'insert',  # normalized lowercase
                'change_data': json.dumps(record_data),
                'old_data': None,
                'timestamp': datetime.utcnow(),
                'sync_status': 'pending',
                'created_by_server': _get_server_id()
            }
            
            change_tracking_queue.put(operation)
            
        except Exception as e:
            # Log but don't raise to avoid breaking the transaction
            print(f"❌ Error queuing insert tracking for {model_class.__name__}: {e}")
    
    @event.listens_for(model_class, 'after_update', propagate=True)
    def track_update(mapper, connection, target):
        """Track record updates with queue-based processing"""
        if not should_track_changes():
            return
        
        try:
            # Get new record data
            new_data = {}
            for column in mapper.columns:
                value = getattr(target, column.name)
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif value is None:
                    value = None
                else:
                    # Convert to JSON-serializable type
                    value = str(value) if not isinstance(value, (str, int, float, bool, list, dict)) else value
                new_data[column.name] = value
            
            # Determine operation type by checking is_active field changes
            operation_type = 'update'
            if hasattr(target, 'is_active'):
                # Check SQLAlchemy's attribute history to detect soft deletes
                from sqlalchemy import inspect
                state = inspect(target)
                
                # Get the history of the is_active attribute
                is_active_history = state.attrs.is_active.history
                
                if is_active_history.has_changes():
                    # Check if is_active changed from True to False (soft delete)
                    if is_active_history.deleted and is_active_history.added:
                        old_value = is_active_history.deleted[0] if is_active_history.deleted else None
                        new_value = is_active_history.added[0] if is_active_history.added else None
                        
                        if old_value is True and new_value is False:
                            operation_type = 'soft_delete'
                        elif old_value is False and new_value is True:
                            operation_type = 'reactivate'
            
            # Queue the operation for background processing
            operation = {
                'table_name': target.__tablename__,
                'record_id': str(target.id) if hasattr(target, 'id') else None,
                'operation': operation_type.lower(),  # normalize
                'change_data': json.dumps(new_data),
                'old_data': None,
                'timestamp': datetime.utcnow(),
                'sync_status': 'pending',
                'created_by_server': _get_server_id()
            }
            
            change_tracking_queue.put(operation)
            
        except Exception as e:
            # Log but don't raise to avoid breaking the transaction
            print(f"❌ Error queuing update tracking for {model_class.__name__}: {e}")
    
    @event.listens_for(model_class, 'after_delete', propagate=True)
    def track_delete(mapper, connection, target):
        """Track record deletions (hard deletes) with queue-based processing"""
        if not should_track_changes():
            return
        
        try:
            # Get record data before deletion
            record_data = {}
            for column in mapper.columns:
                value = getattr(target, column.name)
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif value is None:
                    value = None
                else:
                    # Convert to JSON-serializable type
                    value = str(value) if not isinstance(value, (str, int, float, bool, list, dict)) else value
                record_data[column.name] = value
            
            # Queue the operation for background processing
            operation = {
                'table_name': target.__tablename__,
                'record_id': str(target.id) if hasattr(target, 'id') else None,
                'operation': 'delete',  # already lowercase
                'change_data': None,
                'old_data': json.dumps(record_data),
                'timestamp': datetime.utcnow(),
                'sync_status': 'pending',
                'created_by_server': _get_server_id()
            }
            
            change_tracking_queue.put(operation)
            
        except Exception as e:
            # Log but don't raise to avoid breaking the transaction
            print(f"❌ Error queuing delete tracking for {model_class.__name__}: {e}")


def should_track_changes():
    """Determine if we should track changes (avoid during sync operations)"""
    try:
        # Check if we're in a sync operation to avoid recursive tracking
        if hasattr(current_app, '_sync_in_progress'):
            return not current_app._sync_in_progress
        return True
    except:
        return True


def get_current_server_id():
    """Get the current server ID for change tracking"""
    try:
        if hasattr(current_app, 'config'):
            return current_app.config.get('SYNC_SERVER_ID', 'local')
        return 'local'
    except:
        return 'local'


def setup_change_tracking():
    """Set up change tracking for all syncable models"""
    from app.models import User, ScoutingData, Match, Team, Event
    
    models_to_track = [User, ScoutingData, Match, Team, Event]
    
    for model in models_to_track:
        track_model_changes(model)
        print(f"Change tracking enabled for {model.__name__}")


def disable_change_tracking():
    """Temporarily disable change tracking (e.g., during sync operations)"""
    try:
        current_app._sync_in_progress = True
    except:
        pass


def enable_change_tracking():
    """Re-enable change tracking after sync operations"""
    try:
        current_app._sync_in_progress = False
    except:
        pass


def stop_change_tracking_worker():
    """Stop the background worker for change tracking"""
    global change_tracking_running, change_tracking_worker
    change_tracking_running = False
    # Do not join thread here (daemon) to avoid blocking shutdown
