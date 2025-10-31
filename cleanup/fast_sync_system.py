#!/usr/bin/env python3
"""
Fast and Efficient Sync System
Replaces the heavy universal sync with a lightweight, fast system
that only syncs essential data and avoids database locking
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, ScoutingData, Team, Match, Event
from sqlalchemy import event, text
import threading
import queue
import time
import json
from datetime import datetime, timezone

# Global sync queue - lightweight
fast_sync_queue = queue.Queue(maxsize=100)  # Limit queue size to prevent memory issues
sync_worker_running = False

class FastSyncSystem:
    """Enhanced sync system for complete data synchronization"""
    
    def __init__(self):
        # ALL critical models that need to sync
        self.essential_models = [
            User,                    # Users (as requested)
            ScoutingData,           # Scouting data (critical)
            Team,                   # Team info (critical)  
            Match,                  # Match data (critical)
            Event                   # Event info (critical)
        ]
        
        # Additional models for complete sync
        self.config_models = []
        self.sync_servers = []
        self.worker_thread = None
        self.batch_size = 15      # Increased for more data
        self.batch_delay = 0.5    # Faster processing
        
    def initialize(self, app):
        """Initialize enhanced fast sync system"""
        with app.app_context():
            print(" Initializing Enhanced Fast Sync System...")
            
            # Import additional models for config sync
            self._import_config_models()
            
            # Track all essential models
            self._setup_essential_tracking()
            
            # Track config models
            self._setup_config_tracking()
            
            # Start enhanced worker
            self._start_fast_worker()
            
            # Load sync servers
            self._load_servers()
            
            total_models = len(self.essential_models) + len(self.config_models)
            print(f" Enhanced fast sync initialized:")
            print(f"   - Core models: {len(self.essential_models)}")
            print(f"   - Config models: {len(self.config_models)}")
            print(f"   - Total tracked: {total_models}")
            print(f"   - Sync servers: {len(self.sync_servers)}")
    
    def _import_config_models(self):
        """Import and add configuration-related models"""
        try:
            from app.models import ScoutingTeamSettings, SyncConfig
            
            # Add config models (MUST set self.config_models)
            self.config_models = [
                ScoutingTeamSettings,    # Team settings/configs (as requested)
                SyncConfig              # Sync configurations
            ]
            
            print(f" Config models loaded: {[m.__name__ for m in self.config_models]}")
            print(f" Debug - config_models length: {len(self.config_models)}")
            
        except ImportError as e:
            print(f"️ Could not import some config models: {e}")
            self.config_models = []  # Ensure it's at least an empty list
        except Exception as e:
            print(f"️ Error importing config models: {e}")
            self.config_models = []
    
    def _setup_config_tracking(self):
        """Set up tracking for config models"""
        print(f" Debug - Setting up tracking for {len(self.config_models)} config models")
        for model_class in self.config_models:
            try:
                self._track_model(model_class)
                print(f"️ Config tracking: {model_class.__name__}")
                print(f"   - Sync servers: {len(self.sync_servers)}")
                print(f"   - Queue limit: {fast_sync_queue.maxsize}")
            except Exception as e:
                print(f"️ Failed to track config {model_class.__name__}: {e}")
    
    def _setup_essential_tracking(self):
        """Set up tracking only for essential models"""
        for model_class in self.essential_models:
            self._track_model(model_class)
            print(f" Tracking {model_class.__name__}")
    
    def _track_model(self, model_class):
        """Add lightweight change tracking to a model"""
        
        @event.listens_for(model_class, 'after_insert', propagate=True)
        def track_insert(mapper, connection, target):
            self._queue_change('insert', model_class.__tablename__, target)
        
        @event.listens_for(model_class, 'after_update', propagate=True)
        def track_update(mapper, connection, target):
            # Detect soft deletes
            operation = 'update'
            if hasattr(target, 'is_active'):
                try:
                    from sqlalchemy import inspect
                    state = inspect(target)
                    history = state.attrs.is_active.history
                    if history.has_changes():
                        old_val = history.deleted[0] if history.deleted else None
                        new_val = history.added[0] if history.added else None
                        if old_val is True and new_val is False:
                            operation = 'soft_delete'
                except:
                    pass
            
            self._queue_change(operation, model_class.__tablename__, target)
        
        @event.listens_for(model_class, 'after_delete', propagate=True)
        def track_delete(mapper, connection, target):
            self._queue_change('delete', model_class.__tablename__, target)
    
    def _queue_change(self, operation, table_name, target):
        """Queue a change for sync (lightweight)"""
        try:
            # Don't queue if sync queue is full (prevent memory issues)
            if fast_sync_queue.full():
                print(f"️ Sync queue full, skipping change for {table_name}")
                return
            
            # Extract minimal data needed for sync
            record_data = self._extract_minimal_data(target)
            
            change = {
                'operation': operation,
                'table': table_name,
                'id': str(getattr(target, 'id', 'unknown')),
                'data': record_data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            fast_sync_queue.put_nowait(change)
            
        except queue.Full:
            print(f"️ Fast sync queue full, dropping change for {table_name}")
        except Exception as e:
            print(f" Error queuing change: {e}")
    
    def _extract_minimal_data(self, target):
        """Extract comprehensive data from model for complete sync"""
        if not target:
            return {}
            
        try:
            data = {}
            
            # Get all columns from the model
            from sqlalchemy import inspect
            mapper = inspect(target.__class__)
            
            for column in mapper.columns:
                try:
                    value = getattr(target, column.name, None)
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    elif value is not None and not isinstance(value, (str, int, float, bool, list, dict)):
                        value = str(value)
                    data[column.name] = value
                except Exception as e:
                    print(f"️ Error extracting {column.name}: {e}")
                    data[column.name] = None
            
            # Add model-specific important data
            model_name = target.__class__.__name__
            
            if model_name == 'User':
                # Ensure all user data is captured
                try:
                    data['role_names'] = [role.name for role in target.roles] if hasattr(target, 'roles') else []
                except:
                    data['role_names'] = []
            
            elif model_name == 'ScoutingData':
                # Ensure scouting data JSON is captured
                try:
                    if hasattr(target, 'data_json') and target.data_json:
                        data['data_json'] = target.data_json
                    if hasattr(target, 'team') and target.team:
                        data['team_number'] = target.team.team_number
                except:
                    pass
            
            elif model_name == 'Team':
                # Ensure team info is complete
                try:
                    if hasattr(target, 'team_number'):
                        data['team_number'] = target.team_number
                    if hasattr(target, 'name'):
                        data['name'] = target.name
                except:
                    pass
            
            elif model_name == 'Match':
                # Ensure match info is complete
                try:
                    if hasattr(target, 'match_number'):
                        data['match_number'] = target.match_number
                    if hasattr(target, 'competition_level'):
                        data['competition_level'] = target.competition_level
                    if hasattr(target, 'event_id'):
                        data['event_id'] = target.event_id
                except:
                    pass
            
            elif model_name == 'Event':
                # Ensure event info is complete
                try:
                    if hasattr(target, 'name'):
                        data['name'] = target.name
                    if hasattr(target, 'event_key'):
                        data['event_key'] = target.event_key
                except:
                    pass
            
            elif model_name in ['ScoutingTeamSettings', 'SyncConfig']:
                # Config models - capture all fields
                try:
                    for attr in ['key', 'value', 'scouting_team_number', 'account_creation_locked']:
                        if hasattr(target, attr):
                            data[attr] = getattr(target, attr, None)
                except:
                    pass
            
            print(f" Extracted {len(data)} fields from {model_name}")
            return data
            
        except Exception as e:
            print(f"️ Data extraction error for {target.__class__.__name__}: {e}")
            return {'id': getattr(target, 'id', 'unknown'), 'error': str(e)}
    
    def _start_fast_worker(self):
        """Start lightweight sync worker"""
        global sync_worker_running
        
        if sync_worker_running:
            return
            
        sync_worker_running = True
        
        def fast_worker():
            """Process sync queue in small batches"""
            batch = []
            last_batch_time = time.time()
            
            while sync_worker_running:
                try:
                    # Collect changes for batch processing
                    try:
                        change = fast_sync_queue.get(timeout=0.5)
                        batch.append(change)
                        fast_sync_queue.task_done()
                    except queue.Empty:
                        pass
                    
                    # Process batch when it's full or enough time has passed
                    now = time.time()
                    if (len(batch) >= self.batch_size or 
                        (batch and now - last_batch_time >= self.batch_delay)):
                        
                        if batch:
                            self._process_batch(batch)
                            batch = []
                            last_batch_time = now
                            
                            # Brief pause to prevent overwhelming database
                            time.sleep(0.1)
                
                except Exception as e:
                    print(f" Fast worker error: {e}")
                    time.sleep(1)
        
        self.worker_thread = threading.Thread(target=fast_worker, daemon=True)
        self.worker_thread.start()
        print(" Fast sync worker started")
    
    def _process_batch(self, changes):
        """Process a batch of changes efficiently"""
        if not self.sync_servers:
            return
        
        try:
            # Send batch to servers (non-blocking)
            for server in self.sync_servers:
                threading.Thread(
                    target=self._send_batch_to_server,
                    args=(server, changes),
                    daemon=True
                ).start()
            
            print(f" Processed batch of {len(changes)} changes")
            
        except Exception as e:
            print(f" Batch processing error: {e}")
    
    def _send_batch_to_server(self, server, changes):
        """Send batch to a server (runs in separate thread)"""
        try:
            import requests
            
            payload = {
                'changes': changes,
                'batch_size': len(changes),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            response = requests.post(
                f"{server['url']}/api/sync/fast_receive",
                json=payload,
                timeout=5,  # Short timeout to avoid blocking
                verify=False
            )
            
            if response.status_code == 200:
                print(f" Fast sync to {server['name']}: {len(changes)} changes")
            else:
                print(f"️ Fast sync to {server['name']} returned {response.status_code}")
                
        except Exception as e:
            print(f" Failed to sync to {server['name']}: {e}")
    
    def _load_servers(self):
        """Load sync servers"""
        try:
            from app.models import SyncServer
            
            servers = SyncServer.query.filter_by(is_active=True).all()
            self.sync_servers = []
            
            for server in servers:
                server_info = {
                    'name': server.name,
                    'url': f"{server.protocol}://{server.host}:{server.port}"
                }
                self.sync_servers.append(server_info)
                
        except Exception as e:
            print(f"️ Error loading sync servers: {e}")
    
    def get_status(self):
        """Get sync system status"""
        return {
            'queue_size': fast_sync_queue.qsize(),
            'queue_limit': fast_sync_queue.maxsize,
            'worker_running': sync_worker_running,
            'tracked_models': len(self.essential_models),
            'sync_servers': len(self.sync_servers),
            'batch_size': self.batch_size
        }

# Global instance
fast_sync = FastSyncSystem()

def initialize_fast_sync(app):
    """Initialize fast sync system"""
    fast_sync.initialize(app)
    return fast_sync

def disable_universal_sync():
    """Disable the heavy universal sync system"""
    try:
        from universal_real_time_sync import universal_sync
        # Stop the heavy system
        universal_sync.change_queue.queue.clear()  # Clear queue
        print(" Disabled heavy universal sync system")
    except:
        pass

def apply_database_optimizations():
    """Apply database optimizations directly"""
    app = create_app()
    
    with app.app_context():
        print(" Applying Database Optimizations...")
        
        try:
            # Apply SQLite optimizations
            db.session.execute(text("PRAGMA journal_mode = WAL"))
            db.session.execute(text("PRAGMA synchronous = NORMAL"))
            db.session.execute(text("PRAGMA cache_size = -64000"))  # 64MB cache
            db.session.execute(text("PRAGMA busy_timeout = 30000"))  # 30 second timeout
            db.session.execute(text("PRAGMA temp_store = MEMORY"))
            db.session.commit()
            
            print(" Database optimizations applied")
            
            # Verify settings
            journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
            cache_size = db.session.execute(text("PRAGMA cache_size")).scalar()
            print(f" Journal mode: {journal_mode}")
            print(f" Cache size: {cache_size}")
            
        except Exception as e:
            print(f" Database optimization error: {e}")

if __name__ == "__main__":
    print(" Fast Sync System Setup")
    print("=" * 40)
    
    # Step 1: Apply database optimizations
    apply_database_optimizations()
    
    # Step 2: Test fast sync
    app = create_app()
    with app.app_context():
        initialize_fast_sync(app)
        
        # Test sync system
        status = fast_sync.get_status()
        print(f"\n Fast Sync Status:")
        for key, value in status.items():
            print(f"   {key}: {value}")
    
    print(f"\n Fast Sync System ready!")
    print(f"   - Lightweight and efficient")
    print(f"   - Only tracks essential models")
    print(f"   - Prevents database locking")
    print(f"   - Batch processing for performance")
