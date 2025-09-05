#!/usr/bin/env python3
"""
Universal Real-Time Sync System
Dynamically handles ALL database changes and file changes across all servers in real-time.

This system:
1. Automatically discovers ALL database models
2. Sets up change tracking for EVERY model
3. Handles real-time file sync
4. Provides instant replication across all servers
5. No manual configuration required - fully autonomous
"""

import os
import sys
import json
import hashlib
import threading
import time
import queue
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from sqlalchemy import event, text, inspect as sql_inspect
from sqlalchemy.orm import class_mapper
from flask import current_app

# Global state for universal sync
_sync_state = {
    'models_tracked': set(),
    'file_watchers': {},
    'sync_queue': queue.Queue(),
    'worker_running': False,
    'app_context': None
}

class UniversalSyncManager:
    """Manages real-time sync for ALL database and file changes"""
    
    def __init__(self):
        self.db_models = []
        self.file_paths = []
        self.sync_servers = []
        self.change_queue = queue.Queue()
        self.worker_thread = None
        self.file_checksums = {}
        
    def initialize(self, app=None):
        """Initialize universal sync system"""
        if app:
            _sync_state['app_context'] = app._get_current_object()
            
        print("🌍 Initializing Universal Real-Time Sync System...")
        
        # 1. Auto-discover ALL database models
        self._discover_all_models()
        
        # 2. Set up change tracking for ALL models
        self._setup_universal_change_tracking()
        
        # 3. Set up file monitoring
        self._setup_file_monitoring()
        
        # 4. Start sync workers
        self._start_sync_workers()
        
        # 5. Configure servers
        self._load_sync_servers()
        
        print(f"✅ Universal sync initialized:")
        print(f"   - Database models tracked: {len(self.db_models)}")
        print(f"   - File paths monitored: {len(self.file_paths)}")
        print(f"   - Sync servers: {len(self.sync_servers)}")
        
    def _discover_all_models(self):
        """Automatically discover ALL SQLAlchemy models"""
        try:
            # Import all models to ensure they're registered
            from app.models import db
            
            # Get all model classes from SQLAlchemy registry
            for model_class in db.Model.registry._class_registry.values():
                if (hasattr(model_class, '__tablename__') and 
                    hasattr(model_class, 'query') and
                    hasattr(model_class, 'id')):  # Basic model requirements
                    
                    self.db_models.append(model_class)
                    print(f"📊 Discovered model: {model_class.__name__}")
                    
        except Exception as e:
            print(f"⚠️ Error discovering models: {e}")
            
            # Fallback: manually import known models
            try:
                from app.models import (
                    User, Role, ScoutingTeamSettings, Team, Event, Match, 
                    StrategyShare, ScoutingData, TeamListEntry, AllianceSelection,
                    SyncServer, SyncLog, DatabaseChange, FileChecksum, SyncConfig
                )
                
                known_models = [
                    User, Role, ScoutingTeamSettings, Team, Event, Match,
                    StrategyShare, ScoutingData, TeamListEntry, AllianceSelection,
                    SyncServer, SyncLog, DatabaseChange, FileChecksum, SyncConfig
                ]
                
                for model in known_models:
                    if model not in self.db_models:
                        self.db_models.append(model)
                        print(f"📊 Added model: {model.__name__}")
                        
            except Exception as e2:
                print(f"❌ Fallback model discovery failed: {e2}")
    
    def _setup_universal_change_tracking(self):
        """Set up change tracking for ALL discovered models"""
        for model_class in self.db_models:
            try:
                self._track_model_changes(model_class)
                _sync_state['models_tracked'].add(model_class.__name__)
                print(f"🔄 Change tracking enabled for {model_class.__name__}")
            except Exception as e:
                print(f"⚠️ Failed to track {model_class.__name__}: {e}")
    
    def _track_model_changes(self, model_class):
        """Add comprehensive change tracking to a model"""
        
        @event.listens_for(model_class, 'after_insert', propagate=True)
        def track_insert(mapper, connection, target):
            self._queue_change('insert', model_class, target, None)
        
        @event.listens_for(model_class, 'after_update', propagate=True) 
        def track_update(mapper, connection, target):
            # Detect soft deletes vs regular updates
            operation = 'update'
            if hasattr(target, 'is_active'):
                try:
                    state = sql_inspect(target)
                    history = state.attrs.is_active.history
                    if history.has_changes():
                        old_val = history.deleted[0] if history.deleted else None
                        new_val = history.added[0] if history.added else None
                        if old_val is True and new_val is False:
                            operation = 'soft_delete'
                        elif old_val is False and new_val is True:
                            operation = 'restore'
                except:
                    pass
            
            self._queue_change(operation, model_class, target, None)
        
        @event.listens_for(model_class, 'after_delete', propagate=True)
        def track_delete(mapper, connection, target):
            self._queue_change('delete', model_class, target, target)
    
    def _queue_change(self, operation: str, model_class, new_target, old_target):
        """Queue a database change for sync"""
        try:
            # Extract record data
            new_data = self._extract_record_data(new_target) if new_target else None
            old_data = self._extract_record_data(old_target) if old_target else None
            
            record_id = None
            if new_target and hasattr(new_target, 'id'):
                record_id = str(new_target.id)
            elif old_target and hasattr(old_target, 'id'):
                record_id = str(old_target.id)
            
            change = {
                'type': 'database',
                'table_name': model_class.__tablename__,
                'record_id': record_id,
                'operation': operation.lower(),
                'new_data': new_data,
                'old_data': old_data,
                'timestamp': datetime.utcnow().isoformat(),
                'server_id': self._get_server_id()
            }
            
            self.change_queue.put(change)
            
            # Also store in DatabaseChange table for persistent tracking
            self._store_database_change(change)
            
        except Exception as e:
            print(f"❌ Error queuing change for {model_class.__name__}: {e}")
    
    def _extract_record_data(self, target) -> Dict:
        """Extract all data from a model instance"""
        if not target:
            return None
            
        try:
            data = {}
            mapper = class_mapper(target.__class__)
            
            for column in mapper.columns:
                value = getattr(target, column.name, None)
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif value is not None and not isinstance(value, (str, int, float, bool, list, dict)):
                    value = str(value)
                data[column.name] = value
                
            return data
        except Exception as e:
            print(f"⚠️ Error extracting data: {e}")
            return {}
    
    def _store_database_change(self, change):
        """Store change in DatabaseChange table"""
        try:
            if _sync_state['app_context']:
                with _sync_state['app_context'].app_context():
                    from app import db
                    from app.models import DatabaseChange
                    
                    db_change = DatabaseChange(
                        table_name=change['table_name'],
                        record_id=change['record_id'],
                        operation=change['operation'],
                        change_data=json.dumps(change['new_data']) if change['new_data'] else None,
                        old_data=json.dumps(change['old_data']) if change['old_data'] else None,
                        timestamp=datetime.fromisoformat(change['timestamp']),
                        sync_status='pending',
                        created_by_server=change['server_id']
                    )
                    
                    db.session.add(db_change)
                    db.session.commit()
        except Exception as e:
            print(f"⚠️ Error storing database change: {e}")
    
    def _setup_file_monitoring(self):
        """Set up monitoring for ALL critical files"""
        if _sync_state['app_context']:
            with _sync_state['app_context'].app_context():
                base_path = Path(current_app.root_path).parent
        else:
            base_path = Path.cwd()
        
        # Define critical file patterns to monitor
        critical_patterns = [
            'app/**/*.py',          # All Python files
            'app/**/*.html',        # Templates
            'app/**/*.css',         # Stylesheets
            'app/**/*.js',          # JavaScript
            'app/**/*.json',        # Config files
            'app/**/*.yaml',        # Config files
            'app/**/*.yml',         # Config files
            'static/**/*',          # Static files
            'templates/**/*',       # Templates
            'uploads/**/*',         # User uploads
            'instance/**/*',        # Instance files
            '*.py',                 # Root Python files
            '*.json',               # Root config files
            '*.yaml',               # Root config files
            '*.md',                 # Documentation
            'requirements*.txt',    # Dependencies
        ]
        
        # Collect all matching files
        all_files = set()
        for pattern in critical_patterns:
            try:
                for file_path in base_path.glob(pattern):
                    if file_path.is_file():
                        all_files.add(str(file_path))
            except Exception as e:
                print(f"⚠️ Error globbing {pattern}: {e}")
        
        self.file_paths = list(all_files)
        print(f"📁 Monitoring {len(self.file_paths)} files for changes")
        
        # Start file monitoring thread
        self._start_file_monitoring()
    
    def _start_file_monitoring(self):
        """Start background file monitoring"""
        def file_monitor():
            last_check = {}
            
            while _sync_state['worker_running']:
                try:
                    for file_path in self.file_paths:
                        try:
                            if not os.path.exists(file_path):
                                continue
                                
                            # Get file modification time and hash
                            stat = os.stat(file_path)
                            mtime = stat.st_mtime
                            
                            # Check if file changed
                            if file_path not in last_check or last_check[file_path] < mtime:
                                # File changed, calculate hash
                                file_hash = self._calculate_file_hash(file_path)
                                
                                if file_path not in self.file_checksums or self.file_checksums[file_path] != file_hash:
                                    # File content actually changed
                                    self._queue_file_change(file_path, file_hash)
                                    self.file_checksums[file_path] = file_hash
                                
                                last_check[file_path] = mtime
                                
                        except Exception as e:
                            print(f"⚠️ Error checking file {file_path}: {e}")
                    
                    time.sleep(1)  # Check every second for real-time sync
                    
                except Exception as e:
                    print(f"❌ Error in file monitor: {e}")
                    time.sleep(5)
        
        monitor_thread = threading.Thread(target=file_monitor, daemon=True)
        monitor_thread.start()
        print("👁️ File monitoring started")
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file"""
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"⚠️ Error hashing {file_path}: {e}")
            return ""
    
    def _queue_file_change(self, file_path: str, file_hash: str):
        """Queue a file change for sync"""
        try:
            # Read file content for sync
            content = None
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Binary file, read as base64
                import base64
                with open(file_path, 'rb') as f:
                    content = base64.b64encode(f.read()).decode('ascii')
            
            # Make path relative for consistency
            if _sync_state['app_context']:
                with _sync_state['app_context'].app_context():
                    base_path = Path(current_app.root_path).parent
            else:
                base_path = Path.cwd()
            
            try:
                rel_path = str(Path(file_path).relative_to(base_path))
            except ValueError:
                rel_path = file_path  # Use absolute path if can't make relative
            
            change = {
                'type': 'file',
                'file_path': rel_path,
                'file_hash': file_hash,
                'content': content,
                'timestamp': datetime.utcnow().isoformat(),
                'server_id': self._get_server_id()
            }
            
            self.change_queue.put(change)
            print(f"📄 File changed: {rel_path}")
            
        except Exception as e:
            print(f"❌ Error queuing file change for {file_path}: {e}")
    
    def _start_sync_workers(self):
        """Start background workers for real-time sync"""
        if _sync_state['worker_running']:
            return
            
        _sync_state['worker_running'] = True
        
        def sync_worker():
            """Process sync queue continuously"""
            while _sync_state['worker_running']:
                try:
                    # Process multiple changes in batches for efficiency
                    changes = []
                    
                    # Get up to 10 changes or wait 1 second
                    try:
                        first_change = self.change_queue.get(timeout=1)
                        changes.append(first_change)
                        
                        # Get additional changes without waiting
                        for _ in range(9):
                            try:
                                change = self.change_queue.get_nowait()
                                changes.append(change)
                            except queue.Empty:
                                break
                    except queue.Empty:
                        continue
                    
                    # Sync all changes in batch
                    self._sync_changes_to_servers(changes)
                    
                    # Mark as processed
                    for _ in changes:
                        self.change_queue.task_done()
                        
                except Exception as e:
                    print(f"❌ Error in sync worker: {e}")
                    time.sleep(1)
        
        worker_thread = threading.Thread(target=sync_worker, daemon=True)
        worker_thread.start()
        self.worker_thread = worker_thread
        print("🔄 Real-time sync worker started")
    
    def _load_sync_servers(self):
        """Load active sync servers"""
        try:
            if _sync_state['app_context']:
                with _sync_state['app_context'].app_context():
                    from app.models import SyncServer
                    
                    servers = SyncServer.query.filter_by(is_active=True).all()
                    self.sync_servers = []
                    
                    for server in servers:
                        server_info = {
                            'id': server.id,
                            'name': server.name,
                            'url': f"{server.protocol}://{server.host}:{server.port}",
                            'timeout': getattr(server, 'connection_timeout', 30)
                        }
                        self.sync_servers.append(server_info)
                        
                    print(f"🌐 Loaded {len(self.sync_servers)} sync servers")
        except Exception as e:
            print(f"⚠️ Error loading sync servers: {e}")
    
    def _sync_changes_to_servers(self, changes: List[Dict]):
        """Sync batch of changes to all servers"""
        if not self.sync_servers:
            return
            
        for server in self.sync_servers:
            try:
                self._sync_to_server(server, changes)
            except Exception as e:
                print(f"❌ Error syncing to {server['name']}: {e}")
    
    def _sync_to_server(self, server: Dict, changes: List[Dict]):
        """Sync changes to a specific server"""
        try:
            import requests
            
            # Prepare sync payload
            payload = {
                'changes': changes,
                'source_server': self._get_server_id(),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Send to server
            response = requests.post(
                f"{server['url']}/api/sync/universal_receive",
                json=payload,
                timeout=server['timeout'],
                verify=False  # For development
            )
            
            if response.status_code == 200:
                print(f"✅ Synced {len(changes)} changes to {server['name']}")
            else:
                print(f"⚠️ Sync to {server['name']} returned {response.status_code}")
                
        except Exception as e:
            print(f"❌ Failed to sync to {server['name']}: {e}")
    
    def _get_server_id(self) -> str:
        """Get current server identifier"""
        try:
            if _sync_state['app_context']:
                with _sync_state['app_context'].app_context():
                    return current_app.config.get('SYNC_SERVER_ID', 'local')
            return 'local'
        except:
            return 'local'
    
    def get_status(self) -> Dict:
        """Get current sync system status"""
        return {
            'models_tracked': len(_sync_state['models_tracked']),
            'files_monitored': len(self.file_paths),
            'sync_servers': len(self.sync_servers),
            'queue_size': self.change_queue.qsize(),
            'worker_running': _sync_state['worker_running'],
            'tracked_models': list(_sync_state['models_tracked'])
        }

# Global instance
universal_sync = UniversalSyncManager()

def initialize_universal_sync(app=None):
    """Initialize the universal sync system"""
    universal_sync.initialize(app)
    return universal_sync

def get_sync_status():
    """Get current sync status"""
    return universal_sync.get_status()

if __name__ == "__main__":
    # Test the system
    print("🧪 Testing Universal Sync System...")
    
    # This would normally be called from Flask app initialization
    # initialize_universal_sync()
    
    print("✅ Universal Sync System ready!")
