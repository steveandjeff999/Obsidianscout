#!/usr/bin/env python3
"""
Universal Sync System
Syncs ALL database tables dynamically without knowing field names
AND syncs all instance folder files (except database files)
Fast, efficient, and works with any database schema
"""

import sys
import os
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
import threading
import queue
import time
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import inspect, text, Table, MetaData
from sqlalchemy.orm import scoped_session
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UniversalSyncSystem:
    """Universal sync system that works with any database and syncs all files"""
    
    def __init__(self):
        self.sync_queue = queue.Queue(maxsize=500)
        self.file_sync_queue = queue.Queue(maxsize=200)
        self.worker_running = False
        self.file_worker_running = False
        self.sync_servers = []
        self.instance_path = None
        self.excluded_files = {
            # Database files (handled by database sync)
            '.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3',
            # Lock files
            '.lock', '.lck', '.tmp',
            # Log files (usually server-specific)
            'server_update_stdout.log', 'server_update_stderr.log'
        }
        
    def initialize(self, app):
        """Initialize the universal sync system"""
        with app.app_context():
            print("🚀 Initializing Universal Sync System...")
            
            self.instance_path = Path(app.instance_path)
            print(f"📁 Instance path: {self.instance_path}")
            
            # Setup universal database sync
            self._setup_universal_database_sync()
            
            # Setup file sync monitoring
            self._setup_file_sync_monitoring()
            
            # Load sync servers
            self._load_sync_servers()
            
            # Start workers
            self._start_database_worker()
            self._start_file_worker()
            
            print("✅ Universal Sync System initialized")
            print(f"   - Database tables tracked: {len(self._get_all_tables())}")
            print(f"   - File sync enabled for instance folder")
            print(f"   - Sync servers: {len(self.sync_servers)}")
    
    def _setup_universal_database_sync(self):
        """Setup sync for ALL database tables automatically"""
        print("🗄️ Setting up universal database sync...")
        
        try:
            # Get all tables dynamically
            tables = self._get_all_tables()
            
            print(f"📊 Found {len(tables)} database tables:")
            for table_name in tables[:10]:  # Show first 10
                print(f"   - {table_name}")
            if len(tables) > 10:
                print(f"   ... and {len(tables) - 10} more")
            
            # Set up universal change tracking
            self._setup_universal_tracking()
            
        except Exception as e:
            logger.error(f"Error setting up universal database sync: {e}")
    
    def _get_all_tables(self):
        """Get all table names from the database dynamically"""
        try:
            # Use SQLAlchemy inspector to get all tables
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            # Filter out system tables
            filtered_tables = []
            for table in tables:
                if not table.startswith('sqlite_'):  # Skip SQLite system tables
                    filtered_tables.append(table)
            
            return filtered_tables
            
        except Exception as e:
            logger.error(f"Error getting table names: {e}")
            return []
    
    def _setup_universal_tracking(self):
        """Setup universal change tracking that works with any table"""
        print("🔄 Setting up universal change tracking...")
        
        try:
            # Use SQLAlchemy's event system at the session level
            from sqlalchemy import event
            
            @event.listens_for(db.session, 'after_insert')
            def universal_insert_listener(session, insert_context):
                try:
                    for obj in session.new:
                        self._queue_universal_change('insert', obj)
                except Exception as e:
                    logger.warning(f"Insert listener error: {e}")
            
            @event.listens_for(db.session, 'after_update') 
            def universal_update_listener(session, update_context):
                try:
                    for obj in session.dirty:
                        if session.is_modified(obj):
                            self._queue_universal_change('update', obj)
                except Exception as e:
                    logger.warning(f"Update listener error: {e}")
            
            @event.listens_for(db.session, 'after_delete')
            def universal_delete_listener(session, delete_context):
                try:
                    for obj in session.deleted:
                        self._queue_universal_change('delete', obj)
                except Exception as e:
                    logger.warning(f"Delete listener error: {e}")
            
            print("✅ Universal change tracking enabled")
            
        except Exception as e:
            logger.error(f"Error setting up universal tracking: {e}")
            # Don't fail completely, just log the error
            print("⚠️ Universal tracking setup had issues, but continuing...")
    
    def _queue_universal_change(self, operation, obj):
        """Queue a database change universally without knowing the model"""
        try:
            if self.sync_queue.full():
                logger.warning("Database sync queue full, skipping change")
                return
            
            # Extract data universally
            table_name = obj.__tablename__
            record_id = getattr(obj, 'id', None)
            
            # Get all column data dynamically
            data = self._extract_universal_data(obj)
            
            change = {
                'type': 'database',
                'operation': operation,
                'table': table_name,
                'id': record_id,
                'data': data,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            self.sync_queue.put(change)
            
        except Exception as e:
            logger.error(f"Error queuing universal change: {e}")
    
    def _extract_universal_data(self, obj):
        """Extract all data from any database object dynamically"""
        try:
            data = {}
            
            # Use SQLAlchemy inspector to get all columns
            mapper = inspect(obj.__class__)
            
            for column in mapper.columns:
                try:
                    value = getattr(obj, column.name, None)
                    
                    # Handle different data types
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    elif value is not None and not isinstance(value, (str, int, float, bool, list, dict, type(None))):
                        value = str(value)
                    
                    data[column.name] = value
                    
                except Exception as e:
                    logger.warning(f"Could not extract {column.name}: {e}")
                    data[column.name] = None
            
            return data
            
        except Exception as e:
            logger.error(f"Error extracting universal data: {e}")
            return {'error': str(e)}
    
    def _setup_file_sync_monitoring(self):
        """Setup monitoring for all instance folder files"""
        print("📁 Setting up instance folder file sync...")
        
        try:
            # Get all files in instance folder
            syncable_files = self._get_syncable_files()
            print(f"📄 Found {len(syncable_files)} syncable files")
            
            # Start file monitoring thread
            self._start_file_monitoring()
            
        except Exception as e:
            logger.error(f"Error setting up file sync: {e}")
    
    def _get_syncable_files(self):
        """Get all files in instance folder that should be synced"""
        syncable_files = []
        
        try:
            for file_path in self.instance_path.rglob('*'):
                if file_path.is_file():
                    # Check if file should be excluded
                    should_exclude = False
                    
                    # Check file extension
                    if file_path.suffix.lower() in self.excluded_files:
                        should_exclude = True
                    
                    # Check filename
                    if file_path.name in self.excluded_files:
                        should_exclude = True
                    
                    if not should_exclude:
                        relative_path = file_path.relative_to(self.instance_path)
                        syncable_files.append(relative_path)
            
            return syncable_files
            
        except Exception as e:
            logger.error(f"Error getting syncable files: {e}")
            return []
    
    def _start_file_monitoring(self):
        """Start monitoring instance files for changes"""
        def monitor_files():
            """Monitor file changes"""
            file_hashes = {}
            
            while self.file_worker_running:
                try:
                    syncable_files = self._get_syncable_files()
                    
                    for relative_path in syncable_files:
                        full_path = self.instance_path / relative_path
                        
                        if full_path.exists():
                            # Calculate file hash
                            try:
                                with open(full_path, 'rb') as f:
                                    content = f.read()
                                    current_hash = hashlib.sha256(content).hexdigest()
                                
                                # Check if file changed
                                if str(relative_path) not in file_hashes or file_hashes[str(relative_path)] != current_hash:
                                    file_hashes[str(relative_path)] = current_hash
                                    self._queue_file_change(relative_path, content, current_hash)
                                    
                            except Exception as e:
                                logger.warning(f"Could not read file {relative_path}: {e}")
                    
                    time.sleep(5)  # Check every 5 seconds
                    
                except Exception as e:
                    logger.error(f"File monitoring error: {e}")
                    time.sleep(10)
        
        if not self.file_worker_running:
            self.file_worker_running = True
            threading.Thread(target=monitor_files, daemon=True).start()
            print("📁 File monitoring started")
    
    def _queue_file_change(self, relative_path, content, file_hash):
        """Queue a file change for sync"""
        try:
            if self.file_sync_queue.full():
                logger.warning("File sync queue full, skipping file change")
                return
            
            # Determine if content should be base64 encoded (binary files)
            try:
                content_str = content.decode('utf-8')
                is_binary = False
            except UnicodeDecodeError:
                import base64
                content_str = base64.b64encode(content).decode('ascii')
                is_binary = True
            
            change = {
                'type': 'file',
                'operation': 'update',
                'path': str(relative_path),
                'content': content_str,
                'hash': file_hash,
                'is_binary': is_binary,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            self.file_sync_queue.put(change)
            logger.info(f"📄 Queued file change: {relative_path}")
            
        except Exception as e:
            logger.error(f"Error queuing file change: {e}")
    
    def _load_sync_servers(self):
        """Load sync servers from database with proper connection handling"""
        try:
            from app.models import SyncServer
            from app import db
            
            # Use a dedicated session to avoid connection pool conflicts
            from sqlalchemy.orm import sessionmaker
            Session = sessionmaker(bind=db.engine)
            session = Session()
            
            try:
                servers = session.query(SyncServer).filter_by(is_active=True).all()
                self.sync_servers = []
                
                for server in servers:
                    server_config = {
                        'id': server.id,
                        'name': server.name,
                        'host': server.host,
                        'port': server.port,
                        'protocol': server.protocol,
                        'url': f"{server.protocol}://{server.host}:{server.port}"
                    }
                    self.sync_servers.append(server_config)
                
                logger.info(f"Loaded {len(self.sync_servers)} sync servers")
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error loading sync servers: {e}")
            self.sync_servers = []
    
    def _start_database_worker(self):
        """Start database sync worker"""
        def database_worker():
            """Process database changes"""
            batch = []
            
            while self.worker_running:
                try:
                    # Collect batch of changes
                    while len(batch) < 20:  # Process in batches of 20
                        try:
                            change = self.sync_queue.get(timeout=1.0)
                            batch.append(change)
                        except queue.Empty:
                            break
                    
                    if batch:
                        self._sync_database_batch(batch)
                        batch.clear()
                    
                except Exception as e:
                    logger.error(f"Database worker error: {e}")
                    time.sleep(1)
        
        if not self.worker_running:
            self.worker_running = True
            threading.Thread(target=database_worker, daemon=True).start()
            print("🗄️ Database sync worker started")
    
    def _start_file_worker(self):
        """Start file sync worker"""
        def file_worker():
            """Process file changes"""
            batch = []
            
            while self.file_worker_running:
                try:
                    # Collect batch of file changes
                    while len(batch) < 10:  # Process in smaller batches
                        try:
                            change = self.file_sync_queue.get(timeout=2.0)
                            batch.append(change)
                        except queue.Empty:
                            break
                    
                    if batch:
                        self._sync_file_batch(batch)
                        batch.clear()
                    
                except Exception as e:
                    logger.error(f"File worker error: {e}")
                    time.sleep(2)
        
        if not self.file_worker_running:
            self.file_worker_running = True
            threading.Thread(target=file_worker, daemon=True).start()
            print("📁 File sync worker started")
    
    def _sync_database_batch(self, batch):
        """Sync a batch of database changes to all servers"""
        if not self.sync_servers or not batch:
            return
        
        try:
            payload = {
                'changes': batch,
                'type': 'database_batch',
                'count': len(batch),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            for server in self.sync_servers:
                try:
                    response = requests.post(
                        f"{server['url']}/api/sync/universal_receive",
                        json=payload,
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ Synced {len(batch)} database changes to {server['name']}")
                    else:
                        logger.warning(f"⚠️ Sync failed to {server['name']}: {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    logger.error(f"❌ Could not reach {server['name']}: {e}")
                
        except Exception as e:
            logger.error(f"Error syncing database batch: {e}")
    
    def _sync_file_batch(self, batch):
        """Sync a batch of file changes to all servers"""
        if not self.sync_servers or not batch:
            return
        
        try:
            payload = {
                'changes': batch,
                'type': 'file_batch',
                'count': len(batch),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            for server in self.sync_servers:
                try:
                    response = requests.post(
                        f"{server['url']}/api/sync/universal_receive",
                        json=payload,
                        timeout=15
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ Synced {len(batch)} file changes to {server['name']}")
                    else:
                        logger.warning(f"⚠️ File sync failed to {server['name']}: {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    logger.error(f"❌ Could not reach {server['name']} for files: {e}")
                
        except Exception as e:
            logger.error(f"Error syncing file batch: {e}")


# Global instance
universal_sync = UniversalSyncSystem()


def initialize_universal_sync(app):
    """Initialize the universal sync system"""
    universal_sync.initialize(app)


if __name__ == '__main__':
    # Test the universal sync system
    app = create_app()
    initialize_universal_sync(app)
    
    print("🚀 Universal Sync System running...")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Shutting down Universal Sync System")
