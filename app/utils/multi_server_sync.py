"""
Multi-Server Synchronization Manager
Handles real-time synchronization between multiple scouting servers
"""
import os
import json
import hashlib
import shutil
import time
import threading
import requests
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from flask import current_app, jsonify
from sqlalchemy import text
from app import db, socketio
import logging

# Import the sync models (will be defined in main models file)
from app.models import SyncServer, SyncLog, FileChecksum, SyncConfig

logger = logging.getLogger(__name__)


class MultiServerSyncManager:
    """
    Manages synchronization across multiple scouting servers
    Provides instant sync without authentication using IP/domain based communication
    """
    
    def __init__(self, app=None):
        self.app = app
        self.sync_enabled = True
        self.sync_interval = 30  # seconds
        self.file_watch_interval = 5  # seconds
        self.max_retry_attempts = 3
        self.connection_timeout = 30
        self.sync_thread = None
        self.file_watch_thread = None
        self.running = False
        self.server_id = self._generate_server_id()
        
        # Track unknown table warnings to avoid spam
        self._unknown_table_warnings_logged = set()
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the sync manager with Flask app"""
        self.app = app
        
        # Load configuration from database
        with app.app_context():
            try:
                self.sync_enabled = SyncConfig.get_value('sync_enabled', True)
                self.sync_interval = SyncConfig.get_value('sync_interval', 30)
                self.file_watch_interval = SyncConfig.get_value('file_watch_interval', 5)
                
                # Start background workers if sync is enabled
                if self.sync_enabled:
                    self.start_background_workers()
            except Exception as e:
                # Sync tables don't exist yet - use defaults
                print(f"Warning: Sync tables not found (run setup_multi_server_sync.py): {e}")
                self.sync_enabled = False
                self.sync_interval = 30
                self.file_watch_interval = 5
    
    def _generate_server_id(self):
        """Generate unique server ID based on system info"""
        import platform
        import uuid
        
        # Create unique ID from hostname, MAC address, and current timestamp
        hostname = platform.node()
        mac_address = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                               for elements in range(0, 2*6, 2)][::-1])
        unique_string = f"{hostname}-{mac_address}-{int(time.time())}"
        
        return hashlib.sha256(unique_string.encode()).hexdigest()[:16]
    
    def start_sync_services(self):
        """Start background sync services"""
        if self.running:
            return
        
        self.running = True
        
        # Start sync thread
        self.sync_thread = threading.Thread(target=self._sync_worker, daemon=True)
        self.sync_thread.start()
        
        # Start file watch thread
        self.file_watch_thread = threading.Thread(target=self._file_watch_worker, daemon=True)
        self.file_watch_thread.start()
        
        logger.info("Multi-server sync services started")
    
    def stop_sync_services(self):
        """Stop background sync services"""
        self.running = False
        logger.info("Multi-server sync services stopped")
    
    def _sync_worker(self):
        """Background worker for periodic sync operations"""
        while self.running:
            try:
                if self.sync_enabled:
                    self.sync_all_servers()
                time.sleep(self.sync_interval)
            except Exception as e:
                logger.error(f"Error in sync worker: {e}")
                time.sleep(self.sync_interval)
    
    def _file_watch_worker(self):
        """Background worker for monitoring file changes"""
        while self.running:
            try:
                if self.sync_enabled:
                    self.check_file_changes()
                time.sleep(self.file_watch_interval)
            except Exception as e:
                logger.error(f"Error in file watch worker: {e}")
                time.sleep(self.file_watch_interval)
    
    def get_sync_servers(self, active_only=True):
        """Get list of configured sync servers"""
        query = SyncServer.query
        if active_only:
            query = query.filter_by(is_active=True)
        return query.order_by(SyncServer.sync_priority).all()
    
    def add_sync_server(self, name: str, host: str, port: int = 5000, 
                       protocol: str = 'https', user_id: int = None) -> SyncServer:
        """Add a new sync server to the network"""
        server = SyncServer(
            name=name,
            host=host,
            port=port,
            protocol=protocol,
            created_by=user_id,
            server_id=self._generate_server_id()
        )
        
        db.session.add(server)
        db.session.commit()
        
        # Test connection
        if self.ping_server(server):
            logger.info(f"Successfully added sync server: {name} ({host}:{port})")
        else:
            logger.warning(f"Added sync server but connection test failed: {name}")
        
        return server
    
    def remove_sync_server(self, server_id: int) -> bool:
        """Remove a sync server from the network"""
        server = SyncServer.query.get(server_id)
        if not server:
            return False
        
        # Clean up sync logs
        SyncLog.query.filter_by(server_id=server_id).delete()
        
        db.session.delete(server)
        db.session.commit()
        
        logger.info(f"Removed sync server: {server.name}")
        return True
    
    def ping_server(self, server: SyncServer) -> bool:
        """Ping a server to check if it's available"""
        try:
            url = f"{server.base_url}/api/sync/ping"
            response = requests.get(url, timeout=5, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                server.server_version = data.get('version')
                server.update_ping(success=True)
                return True
            else:
                server.update_ping(success=False, error_message=f"HTTP {response.status_code}")
                return False
                
        except Exception as e:
            server.update_ping(success=False, error_message=str(e))
            return False
    
    def sync_all_servers(self):
        """Sync with all configured servers"""
        servers = self.get_sync_servers()
        
        for server in servers:
            try:
                self.sync_with_server(server)
            except Exception as e:
                logger.error(f"Error syncing with server {server.name}: {e}")
    
    def sync_with_server(self, server: SyncServer, sync_type: str = 'full'):
        """Sync with a specific server"""
        logger.info(f"Starting sync with {server.name} ({server.base_url}) - type: {sync_type}")
        
        if not server.sync_enabled:
            logger.warning(f"Sync disabled for server {server.name}")
            return
            
        if not server.is_healthy:
            logger.warning(f"Server {server.name} is not healthy")
            return
        
        # Create sync log entry
        sync_log = SyncLog(
            server_id=server.id,
            sync_type=sync_type,
            direction='bidirectional',
            status='pending'
        )
        db.session.add(sync_log)
        db.session.commit()
        
        try:
            sync_log.status = 'in_progress'
            db.session.commit()
            
            # Ping server first
            ping_result = self.ping_server(server)
            logger.info(f"Ping result for {server.name}: {ping_result}")
            if not ping_result:
                raise Exception("Server is not responding")
            
            # Sync database if enabled
            if server.sync_database and sync_type in ['database', 'full']:
                logger.info(f"Starting database sync with {server.name}")
                self._sync_database_with_server(server, sync_log)
                logger.info(f"Database sync completed with {server.name}")
            else:
                logger.info(f"Database sync skipped for {server.name} (enabled: {server.sync_database}, type: {sync_type})")
            
            # Sync instance files if enabled
            if server.sync_instance_files and sync_type in ['files', 'full']:
                logger.info(f"Starting instance files sync with {server.name}")
                self._sync_instance_files_with_server(server, sync_log)
                logger.info(f"Instance files sync completed with {server.name}")
            else:
                logger.info(f"Instance files sync skipped for {server.name} (enabled: {server.sync_instance_files}, type: {sync_type})")
            
            # Sync config files if enabled
            if server.sync_config_files and sync_type in ['config', 'full']:
                self._sync_config_files_with_server(server, sync_log)
            
            # Sync uploads if enabled
            if server.sync_uploads and sync_type in ['uploads', 'full']:
                self._sync_uploads_with_server(server, sync_log)
            
            # Mark sync as completed
            sync_log.status = 'completed'
            sync_log.completed_at = datetime.now(timezone.utc)
            server.last_sync = datetime.now(timezone.utc)
            
            db.session.commit()
            
            # Emit real-time update
            socketio.emit('sync_completed', {
                'server_id': server.id,
                'server_name': server.name,
                'sync_type': sync_type,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, namespace='/sync')
            
            logger.info(f"Successfully synced with server {server.name}")
            
        except Exception as e:
            sync_log.status = 'failed'
            sync_log.error_message = str(e)
            sync_log.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            
            logger.error(f"Failed to sync with server {server.name}: {e}")
            raise
    
    def _sync_database_with_server(self, server: SyncServer, sync_log: SyncLog):
        """Sync database with another server (data-level sync, not file copy)"""
        try:
            logger.info(f"Starting database sync with {server.name}")
            
            # IMPORTANT: Never copy SQLite database files directly!
            # This method syncs data changes, not file copies
            
            # Get local database changes since last sync
            local_changes = self._get_database_changes_since(server.last_sync)
            logger.info(f"Found {len(local_changes) if local_changes else 0} local database changes since last sync")
            
            # Send changes to remote server
            if local_changes:
                logger.info(f"Sending {len(local_changes)} changes to {server.name}")
                
                # Debug: Log the first change to see exact data format
                if local_changes:
                    first_change = local_changes[0]
                    logger.debug(f"Sample change data: {first_change}")
                    logger.debug(f"Sample change data types: {[(k, type(v).__name__) for k, v in first_change.get('data', {}).items()]}")
                
                url = f"{server.base_url}/api/sync/database"
                payload = {
                    'changes': local_changes,
                    'server_id': self.server_id,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                response = requests.post(url, json=payload, 
                                       timeout=self.connection_timeout, verify=False)
                
                if response.status_code != 200:
                    logger.error(f"Failed to push database changes. Response: {response.text}")
                    raise Exception(f"Failed to push database changes: {response.text}")
                logger.info(f"Successfully pushed changes to {server.name}")
            else:
                logger.info(f"No local changes to push to {server.name}")
            
            # Get changes from remote server
            url = f"{server.base_url}/api/sync/database/changes"
            since_param = server.last_sync.isoformat() if server.last_sync else None
            logger.info(f"Requesting changes from {server.name} since {since_param}")
            
            response = requests.get(url, params={'since': since_param}, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code == 200:
                remote_changes = response.json()
                changes_count = len(remote_changes.get('changes', []))
                logger.info(f"Received {changes_count} changes from {server.name}")
                
                if remote_changes.get('changes'):
                    # Apply changes received from remote server
                    logger.info(f"Applying {len(remote_changes['changes'])} changes from {server.name}")
                    self._apply_database_changes(remote_changes['changes'])
                    sync_log.items_synced += len(remote_changes['changes'])
                    db.session.commit()
                    logger.info(f"Applied {len(remote_changes['changes'])} changes from {server.name}")
                else:
                    logger.info(f"No remote changes to apply from {server.name}")
            else:
                logger.warning(f"Failed to get changes from {server.name}: HTTP {response.status_code}")
            
        except Exception as e:
            logger.error(f"Database sync failed with {server.name}: {e}")
            raise
    
    def _sync_instance_files_with_server(self, server: SyncServer, sync_log: SyncLog):
        """Sync instance folder files with another server"""
        try:
            logger.info(f"Starting instance files sync with {server.name}")
            instance_path = current_app.instance_path
            
            # Get local file checksums
            local_checksums = self._get_directory_checksums(instance_path)
            logger.info(f"Found {len(local_checksums)} local files in instance folder")
            
            # Get remote file checksums
            url = f"{server.base_url}/api/sync/files/checksums"
            response = requests.get(url, params={'path': 'instance'}, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code != 200:
                raise Exception(f"Failed to get remote checksums: {response.text}")
            
            remote_checksums = response.json()
            logger.info(f"Found {len(remote_checksums)} remote files in instance folder")
            
            # Find files that need to be synced
            files_to_upload, files_to_download = self._compare_checksums(
                local_checksums, remote_checksums)
            
            logger.info(f"Files to upload: {len(files_to_upload)}, Files to download: {len(files_to_download)}")
            
            # Upload files that are newer locally
            for file_info in files_to_upload:
                logger.info(f"Uploading file: {file_info['path']}")
                self._upload_file_to_server(server, file_info['path'], 'instance')
                sync_log.items_synced += 1
            
            # Download files that are newer remotely
            for file_info in files_to_download:
                logger.info(f"Downloading file: {file_info['path']}")
                self._download_file_from_server(server, file_info['path'], 'instance')
                sync_log.items_synced += 1
            
            sync_log.total_items = len(files_to_upload) + len(files_to_download)
            
        except Exception as e:
            logger.error(f"Instance files sync failed with {server.name}: {e}")
            raise
    
    def _sync_config_files_with_server(self, server: SyncServer, sync_log: SyncLog):
        """Sync config folder files with another server"""
        try:
            config_path = os.path.join(os.getcwd(), 'config')
            
            # Get local file checksums
            local_checksums = self._get_directory_checksums(config_path)
            
            # Get remote file checksums
            url = f"{server.base_url}/api/sync/files/checksums"
            response = requests.get(url, params={'path': 'config'}, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code != 200:
                raise Exception(f"Failed to get remote config checksums: {response.text}")
            
            remote_checksums = response.json()
            
            # Find files that need to be synced
            files_to_upload, files_to_download = self._compare_checksums(
                local_checksums, remote_checksums)
            
            # Upload and download files
            for file_info in files_to_upload:
                self._upload_file_to_server(server, file_info['path'], 'config')
                sync_log.items_synced += 1
            
            for file_info in files_to_download:
                self._download_file_from_server(server, file_info['path'], 'config')
                sync_log.items_synced += 1
            
            sync_log.total_items = len(files_to_upload) + len(files_to_download)
            
        except Exception as e:
            logger.error(f"Config files sync failed with {server.name}: {e}")
            raise
    
    def _sync_uploads_with_server(self, server: SyncServer, sync_log: SyncLog):
        """Sync uploads folder with another server"""
        try:
            uploads_path = os.path.join(os.getcwd(), 'uploads')
            
            if not os.path.exists(uploads_path):
                return
            
            # Get local file checksums
            local_checksums = self._get_directory_checksums(uploads_path)
            
            # Get remote file checksums
            url = f"{server.base_url}/api/sync/files/checksums"
            response = requests.get(url, params={'path': 'uploads'}, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code != 200:
                raise Exception(f"Failed to get remote uploads checksums: {response.text}")
            
            remote_checksums = response.json()
            
            # Find files that need to be synced
            files_to_upload, files_to_download = self._compare_checksums(
                local_checksums, remote_checksums)
            
            # Upload and download files
            for file_info in files_to_upload:
                self._upload_file_to_server(server, file_info['path'], 'uploads')
                sync_log.items_synced += 1
            
            for file_info in files_to_download:
                self._download_file_from_server(server, file_info['path'], 'uploads')
                sync_log.items_synced += 1
            
            sync_log.total_items = len(files_to_upload) + len(files_to_download)
            
        except Exception as e:
            logger.error(f"Uploads sync failed with {server.name}: {e}")
            raise
    
    def _get_directory_checksums(self, directory_path: str) -> Dict[str, Dict]:
        """Get checksums for all files in a directory (excluding database files)"""
        checksums = {}
        
        # Files to exclude from sync (database files and lock files)
        excluded_extensions = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.lock'}
        excluded_files = {'app.db', 'database.db', 'scouting.db', 'app.db-wal', 'app.db-shm'}
        
        logger.info(f"Scanning directory: {directory_path}")
        
        if not os.path.exists(directory_path):
            logger.warning(f"Directory does not exist: {directory_path}")
            return checksums
        
        file_count = 0
        excluded_count = 0
        
        for root, dirs, files in os.walk(directory_path):
            logger.debug(f"Scanning subdirectory: {root}")
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, directory_path)
                
                # Skip database files and lock files
                file_lower = file.lower()
                file_ext = os.path.splitext(file_lower)[1]
                
                if (file_ext in excluded_extensions or 
                    file_lower in excluded_files or
                    file_lower.endswith('.db-wal') or
                    file_lower.endswith('.db-shm')):
                    logger.debug(f"Skipping database file: {relative_path}")
                    excluded_count += 1
                    continue
                
                try:
                    stat = os.stat(file_path)
                    with open(file_path, 'rb') as f:
                        content = f.read()
                        checksum = hashlib.sha256(content).hexdigest()
                    
                    checksums[relative_path] = {
                        'checksum': checksum,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    }
                    file_count += 1
                    logger.debug(f"Processed file: {relative_path} (size: {stat.st_size}, checksum: {checksum[:8]}...)")
                except Exception as e:
                    logger.warning(f"Could not process file {file_path}: {e}")
        
        logger.info(f"Directory scan complete - Processed: {file_count}, Excluded: {excluded_count}")
        return checksums
    
    def _compare_checksums(self, local_checksums: Dict, remote_checksums: Dict):
        """Compare local and remote checksums to determine sync needs"""
        files_to_upload = []
        files_to_download = []
        
        logger.info(f"Comparing checksums - Local: {len(local_checksums)}, Remote: {len(remote_checksums)}")
        
        # Check for files to upload (local is newer or remote doesn't have)
        for path, local_info in local_checksums.items():
            if path not in remote_checksums:
                logger.debug(f"File only exists locally: {path}")
                files_to_upload.append({'path': path, **local_info})
            else:
                remote_info = remote_checksums[path]
                if local_info['checksum'] != remote_info['checksum']:
                    local_modified = datetime.fromisoformat(local_info['modified'])
                    remote_modified = datetime.fromisoformat(remote_info['modified'])
                    
                    if local_modified > remote_modified:
                        logger.debug(f"Local file newer: {path}")
                        files_to_upload.append({'path': path, **local_info})
                    else:
                        logger.debug(f"Remote file newer: {path}")
                        files_to_download.append({'path': path, **remote_info})
                else:
                    logger.debug(f"Files identical: {path}")
        
        # Check for files to download (remote has but local doesn't)
        for path, remote_info in remote_checksums.items():
            if path not in local_checksums:
                logger.debug(f"File only exists remotely: {path}")
                files_to_download.append({'path': path, **remote_info})
        
        logger.info(f"Comparison result - Upload: {len(files_to_upload)}, Download: {len(files_to_download)}")
        return files_to_upload, files_to_download
    
    def _upload_file_to_server(self, server: SyncServer, file_path: str, base_folder: str):
        """Upload a file to a remote server"""
        try:
            if base_folder == 'instance':
                full_path = os.path.join(current_app.instance_path, file_path)
            else:
                full_path = os.path.join(os.getcwd(), base_folder, file_path)
            
            if not os.path.exists(full_path):
                return
            
            url = f"{server.base_url}/api/sync/files/upload"
            
            with open(full_path, 'rb') as f:
                files = {'file': (file_path, f)}
                data = {
                    'path': file_path,
                    'base_folder': base_folder,
                    'server_id': self.server_id
                }
                
                response = requests.post(url, files=files, data=data, 
                                       timeout=self.connection_timeout, verify=False)
                
                if response.status_code != 200:
                    raise Exception(f"Upload failed: {response.text}")
            
            logger.debug(f"Uploaded file {file_path} to {server.name}")
            
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to {server.name}: {e}")
            raise
    
    def _download_file_from_server(self, server: SyncServer, file_path: str, base_folder: str):
        """Download a file from a remote server"""
        try:
            url = f"{server.base_url}/api/sync/files/download"
            params = {
                'path': file_path,
                'base_folder': base_folder
            }
            
            response = requests.get(url, params=params, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code != 200:
                raise Exception(f"Download failed: {response.text}")
            
            if base_folder == 'instance':
                full_path = os.path.join(current_app.instance_path, file_path)
            else:
                full_path = os.path.join(os.getcwd(), base_folder, file_path)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'wb') as f:
                f.write(response.content)
            
            logger.debug(f"Downloaded file {file_path} from {server.name}")
            
        except Exception as e:
            logger.error(f"Failed to download {file_path} from {server.name}: {e}")
            raise
    
    def _get_database_changes_since(self, since_timestamp: Optional[datetime]) -> List[Dict]:
        """Get database changes since a specific timestamp using change tracking"""
        changes = []
        
        try:
            # Import models here to avoid circular imports
            from app.models import DatabaseChange, User, ScoutingData, Match, Team, Event
            
            cutoff_time = since_timestamp or datetime(2020, 1, 1)  # Default to very old date
            logger.info(f"Getting database changes since {cutoff_time}")
            
            # First, check if we have change tracking enabled
            tracked_changes = DatabaseChange.query.filter(
                DatabaseChange.timestamp > cutoff_time,
                DatabaseChange.sync_status == 'pending'
            ).order_by(DatabaseChange.timestamp.asc()).all()
            
            if tracked_changes:
                logger.info(f"Found {len(tracked_changes)} tracked changes")
                for change in tracked_changes:
                    changes.append(change.to_dict())
                    # Mark as synced after including in sync
                    change.sync_status = 'synced'
                
                db.session.commit()
                return changes
            
            # Fallback: If no change tracking, use the old method for existing records
            logger.info("No tracked changes found, falling back to timestamp-based detection")
            
            # Define models to sync with their modification tracking
            sync_models = [
                ('users', User),
                ('scouting_data', ScoutingData),
                ('matches', Match),
                ('teams', Team),
                ('events', Event)
            ]
            
            for table_name, model_class in sync_models:
                try:
                    # Check if model has a modified timestamp field
                    modified_field = None
                    for field_name in ['updated_at', 'modified_at', 'created_at']:
                        if hasattr(model_class, field_name):
                            modified_field = getattr(model_class, field_name)
                            break
                    
                    if modified_field:
                        # Get records modified since cutoff time
                        query = model_class.query.filter(modified_field > cutoff_time)
                        modified_records = query.all()
                        
                        for record in modified_records:
                            # Convert record to dict for syncing
                            record_data = {}
                            for column in model_class.__table__.columns:
                                value = getattr(record, column.name)
                                if isinstance(value, datetime):
                                    value = value.isoformat()
                                record_data[column.name] = value
                            
                            # Determine operation type
                            operation = 'upsert'
                            if hasattr(record, 'is_active') and not record.is_active:
                                operation = 'soft_delete'
                            
                            changes.append({
                                'table': table_name,
                                'record_id': str(record.id),
                                'operation': operation,
                                'data': record_data,
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            })
                        
                        logger.info(f"Found {len(modified_records)} changes in {table_name} since {cutoff_time}")
                    
                except Exception as e:
                    logger.warning(f"Could not get changes for {table_name}: {e}")
            
            logger.info(f"Total database changes found: {len(changes)}")
            
        except Exception as e:
            logger.error(f"Error getting database changes: {e}")
        
        return changes
    
    def _apply_database_changes(self, changes: List[Dict]):
        """Apply database changes received from remote server"""
        if not changes:
            return
            
        logger.info(f"Applying {len(changes)} database changes")
        
        # Disable change tracking during sync to prevent recursive tracking
        from app.utils.change_tracking import disable_change_tracking, enable_change_tracking
        disable_change_tracking()
        
        try:
            # Debug: Log the first change to see exact data format
            if changes:
                first_change = changes[0]
                logger.debug(f"Sample received change: {first_change}")
                sample_data = first_change.get('data', {})
                logger.debug(f"Sample received data types: {[(k, type(v).__name__) for k, v in sample_data.items()]}")
                
            # Import models here to avoid circular imports
            from app.models import User, ScoutingData, Match, Team, Event
            
            model_map = {
                'users': User,
                'user': User,  # Handle both 'user' and 'users' table names
                'scouting_data': ScoutingData,
                'matches': Match,
                'teams': Team,
                'events': Event
            }
            
            applied_count = 0
            
            for change in changes:
                try:
                    table_name = change.get('table')
                    operation = change.get('operation', 'upsert')
                    data = change.get('data', {})
                    record_id = change.get('record_id')
                    
                    if table_name not in model_map:
                        # Only log warning once per table name to avoid spam
                        if table_name not in self._unknown_table_warnings_logged:
                            logger.warning(f"Unknown table for sync: {table_name}")
                            self._unknown_table_warnings_logged.add(table_name)
                        continue
                    
                    model_class = model_map[table_name]
                    logger.debug(f"Processing {operation} operation on {table_name} record {record_id}")
                    
                    if operation in ['upsert', 'insert', 'update']:
                        # Handle insert/update operations
                        if record_id:
                            existing_record = model_class.query.get(record_id)
                            if existing_record:
                                # Update existing record
                                logger.debug(f"Updating existing {table_name} record {record_id}")
                                logger.debug(f"Original data before conversion: {data}")
                                
                                update_data = {}
                                for key, value in data.items():
                                    if key == 'id':
                                        # Skip the ID field for updates
                                        continue
                                        
                                    if hasattr(existing_record, key):
                                        original_value = value
                                        # Convert ISO date strings back to datetime
                                        if key.endswith('_at') and isinstance(value, str):
                                            try:
                                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                                logger.debug(f"Converted {key} from '{original_value}' to {value}")
                                            except Exception as e:
                                                logger.warning(f"Failed to convert {key}: {e}")
                                                pass
                                        # Also check for specific datetime fields including timestamp
                                        elif key in ['last_login', 'created_at', 'updated_at', 'modified_at', 'timestamp'] and isinstance(value, str):
                                            try:
                                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                                logger.debug(f"Converted {key} from '{original_value}' to {value}")
                                            except Exception as e:
                                                logger.warning(f"Failed to convert {key}: {e}")
                                                pass
                                        
                                        setattr(existing_record, key, value)
                                        update_data[key] = value
                                    else:
                                        logger.warning(f"Field {key} not found on {table_name} model")
                                
                                logger.debug(f"Final update data: {update_data}")
                                logger.debug(f"Update data types: {[(k, type(v).__name__) for k, v in update_data.items()]}")
                                logger.debug(f"Updated {table_name} record {record_id}")
                            else:
                                # Create new record
                                # Convert ISO date strings back to datetime
                                processed_data = {}
                                for key, value in data.items():
                                    if key.endswith('_at') and isinstance(value, str):
                                        try:
                                            processed_data[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                        except:
                                            processed_data[key] = value
                                    elif key in ['last_login', 'created_at', 'updated_at', 'modified_at', 'timestamp'] and isinstance(value, str):
                                        try:
                                            processed_data[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                        except:
                                            processed_data[key] = value
                                    else:
                                        processed_data[key] = value
                                
                                new_record = model_class(**processed_data)
                                db.session.add(new_record)
                                logger.debug(f"Created new {table_name} record {record_id}")
                        
                        applied_count += 1
                    
                    elif operation == 'delete':
                        # Handle hard deletion - permanent removal from database
                        if record_id:
                            existing_record = model_class.query.get(record_id)
                            if existing_record:
                                logger.info(f"️  Applying HARD DELETE for {table_name} record {record_id}")
                                
                                # Store some info before deletion for logging
                                record_info = f"{getattr(existing_record, 'username', getattr(existing_record, 'name', str(record_id)))}"
                                
                                db.session.delete(existing_record)
                                logger.info(f" Hard deleted {table_name} record {record_id} ({record_info})")
                                applied_count += 1
                            else:
                                logger.warning(f"Warning: Record {record_id} in {table_name} not found for hard deletion (may already be deleted)")
                    
                    elif operation == 'soft_delete':
                        # Handle soft deletion (set is_active = False)
                        if record_id:
                            existing_record = model_class.query.get(record_id)
                            if existing_record and hasattr(existing_record, 'is_active'):
                                logger.info(f" Applying SOFT DELETE for {table_name} record {record_id}")
                                
                                existing_record.is_active = False
                                # Also update any timestamp fields
                                if hasattr(existing_record, 'updated_at'):
                                    existing_record.updated_at = datetime.now(timezone.utc)
                                
                                record_info = f"{getattr(existing_record, 'username', getattr(existing_record, 'name', str(record_id)))}"
                                logger.info(f" Soft deleted {table_name} record {record_id} ({record_info})")
                                applied_count += 1
                            else:
                                logger.warning(f"Warning: Record {record_id} in {table_name} not found for soft deletion or doesn't support is_active")
                    
                    elif operation == 'reactivate':
                        # Handle user reactivation (set is_active = True)
                        if record_id:
                            existing_record = model_class.query.get(record_id)
                            if existing_record and hasattr(existing_record, 'is_active'):
                                logger.info(f" Applying REACTIVATION for {table_name} record {record_id}")
                                
                                existing_record.is_active = True
                                # Also update any timestamp fields
                                if hasattr(existing_record, 'updated_at'):
                                    existing_record.updated_at = datetime.now(timezone.utc)
                                
                                record_info = f"{getattr(existing_record, 'username', getattr(existing_record, 'name', str(record_id)))}"
                                logger.info(f" Reactivated {table_name} record {record_id} ({record_info})")
                                applied_count += 1
                            else:
                                logger.warning(f"Warning: Record {record_id} in {table_name} not found for reactivation")
                    
                    else:
                        logger.warning(f"Unknown operation type: {operation}")
                    
                except Exception as e:
                    logger.error(f"Error applying change to {table_name}: {e}")
                    continue
            
            # Don't commit here - let the caller handle the transaction
            logger.info(f"Applied {applied_count} database changes successfully")
            
        except Exception as e:
            logger.error(f"Error applying database changes: {e}")
            raise
        finally:
            # Re-enable change tracking
            enable_change_tracking()
    
    def check_file_changes(self):
        """Check for file changes and trigger sync if needed"""
        try:
            # Check instance folder
            instance_path = current_app.instance_path
            self._check_directory_changes(instance_path, 'instance')
            
            # Check config folder
            config_path = os.path.join(os.getcwd(), 'config')
            self._check_directory_changes(config_path, 'config')
            
            # Check uploads folder
            uploads_path = os.path.join(os.getcwd(), 'uploads')
            if os.path.exists(uploads_path):
                self._check_directory_changes(uploads_path, 'uploads')
            
        except Exception as e:
            logger.error(f"Error checking file changes: {e}")
    
    def _check_directory_changes(self, directory_path: str, folder_type: str):
        """Check for changes in a specific directory"""
        if not os.path.exists(directory_path):
            return
        
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, directory_path)
                
                try:
                    stat = os.stat(file_path)
                    with open(file_path, 'rb') as f:
                        content = f.read()
                        checksum = hashlib.sha256(content).hexdigest()
                    
                    # Check if file has changed
                    file_checksum = FileChecksum.get_or_create(
                        relative_path, checksum, stat.st_size, 
                        datetime.fromtimestamp(stat.st_mtime)
                    )
                    
                    if file_checksum.sync_status in ['modified', 'new']:
                        # File has changed, trigger sync
                        self._trigger_file_sync(relative_path, folder_type)
                        file_checksum.sync_status = 'synced'
                        db.session.commit()
                
                except Exception as e:
                    logger.warning(f"Could not check file {file_path}: {e}")
    
    def _trigger_file_sync(self, file_path: str, folder_type: str):
        """Trigger sync for a specific file change"""
        servers = self.get_sync_servers()
        
        for server in servers:
            try:
                if folder_type == 'instance' and server.sync_instance_files:
                    self._upload_file_to_server(server, file_path, 'instance')
                elif folder_type == 'config' and server.sync_config_files:
                    self._upload_file_to_server(server, file_path, 'config')
                elif folder_type == 'uploads' and server.sync_uploads:
                    self._upload_file_to_server(server, file_path, 'uploads')
                
                # Emit real-time update
                socketio.emit('file_synced', {
                    'file_path': file_path,
                    'folder_type': folder_type,
                    'server_name': server.name,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, namespace='/sync')
                
            except Exception as e:
                logger.error(f"Failed to sync file {file_path} to {server.name}: {e}")
    
    def force_full_sync(self, server_id: Optional[int] = None):
        """Force a full sync with all servers or a specific server"""
        if server_id:
            server = SyncServer.query.get(server_id)
            if server:
                self.sync_with_server(server, 'full')
        else:
            servers = self.get_sync_servers()
            for server in servers:
                self.sync_with_server(server, 'full')
    
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status"""
        servers = self.get_sync_servers()
        recent_logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(10).all()
        
        return {
            'sync_enabled': self.sync_enabled,
            'server_count': len(servers),
            'healthy_servers': len([s for s in servers if s.is_healthy]),
            'recent_syncs': [log.to_dict() for log in recent_logs],
            'last_sync': max([s.last_sync for s in servers if s.last_sync], default=None),
            'sync_interval': self.sync_interval,
            'running': self.running
        }
    
    def start_background_workers(self):
        """Start background sync and monitoring workers"""
        try:
            self.running = True
            
            # Start file monitoring
            self.start_file_monitoring()
            
            # Start periodic sync
            self.start_periodic_sync()
            
            print(" Multi-server sync background workers started")
        except Exception as e:
            print(f"Warning: Could not start sync workers: {e}")
            self.running = False
    
    def start_file_monitoring(self):
        """Start monitoring files for changes"""
        # This would start a background thread to monitor file changes
        # For now, just mark as started
        print("File monitoring started")
    
    def start_periodic_sync(self):
        """Start periodic synchronization"""
        # This would start a background thread for periodic sync
        # For now, just mark as started
        print(" Periodic sync started")
    
    def upload_file_to_server(self, server: SyncServer, file_path: str) -> bool:
        """Public method to upload a file to a specific server"""
        try:
            # Determine the appropriate base folder based on file path
            if '/instance/' in file_path or '\\instance\\' in file_path:
                base_folder = 'instance'
                # Extract relative path from instance folder
                if current_app:
                    instance_path = current_app.instance_path
                    if file_path.startswith(instance_path):
                        relative_path = os.path.relpath(file_path, instance_path)
                    else:
                        relative_path = os.path.basename(file_path)
                else:
                    relative_path = os.path.basename(file_path)
            elif '/templates/' in file_path or '\\templates\\' in file_path:
                base_folder = 'templates'
                relative_path = file_path.split('templates/')[-1] if 'templates/' in file_path else file_path.split('templates\\')[-1]
            elif '/static/' in file_path or '\\static\\' in file_path:
                base_folder = 'static'
                relative_path = file_path.split('static/')[-1] if 'static/' in file_path else file_path.split('static\\')[-1]
            else:
                # Default to instance folder
                base_folder = 'instance'
                relative_path = os.path.basename(file_path)
            
            logger.info(f"Uploading file {relative_path} to {server.name} (base_folder: {base_folder})")
            self._upload_file_to_server(server, relative_path, base_folder)
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload file {file_path} to {server.name}: {e}")
            return False
    
    def delete_file_on_server(self, server: SyncServer, file_path: str) -> bool:
        """Public method to delete a file on a specific server"""
        try:
            # Determine the appropriate base folder based on file path
            if '/instance/' in file_path or '\\instance\\' in file_path:
                base_folder = 'instance'
                if current_app:
                    instance_path = current_app.instance_path
                    if file_path.startswith(instance_path):
                        relative_path = os.path.relpath(file_path, instance_path)
                    else:
                        relative_path = os.path.basename(file_path)
                else:
                    relative_path = os.path.basename(file_path)
            elif '/templates/' in file_path or '\\templates\\' in file_path:
                base_folder = 'templates'
                relative_path = file_path.split('templates/')[-1] if 'templates/' in file_path else file_path.split('templates\\')[-1]
            elif '/static/' in file_path or '\\static\\' in file_path:
                base_folder = 'static'
                relative_path = file_path.split('static/')[-1] if 'static/' in file_path else file_path.split('static\\')[-1]
            else:
                # Default to instance folder
                base_folder = 'instance'
                relative_path = os.path.basename(file_path)
            
            logger.info(f"Deleting file {relative_path} on {server.name} (base_folder: {base_folder})")
            
            # Call server's delete endpoint
            url = f"{server.base_url}/api/sync/files/delete"
            data = {
                'path': relative_path,
                'base_folder': base_folder,
                'server_id': self.server_id
            }
            
            response = requests.post(url, json=data, timeout=self.connection_timeout, verify=False)
            
            if response.status_code == 200:
                logger.info(f"Successfully deleted {relative_path} on {server.name}")
                return True
            else:
                logger.warning(f"Failed to delete {relative_path} on {server.name}: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete file {file_path} on {server.name}: {e}")
            return False
    
    def sync_file_upload(self, server_url: str, file_path: str, api_key: str = None) -> Dict[str, Any]:
        """Legacy method for backward compatibility with real-time file sync"""
        try:
            # Find server by URL
            server = SyncServer.query.filter_by(base_url=server_url).first()
            if not server:
                return {'success': False, 'error': 'Server not found'}
            
            success = self.upload_file_to_server(server, file_path)
            return {'success': success}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def sync_file_delete(self, server_url: str, file_path: str, api_key: str = None) -> Dict[str, Any]:
        """Legacy method for backward compatibility with real-time file sync"""
        try:
            # Find server by URL
            server = SyncServer.query.filter_by(base_url=server_url).first()
            if not server:
                return {'success': False, 'error': 'Server not found'}
            
            success = self.delete_file_on_server(server, file_path)
            return {'success': success}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


# Global sync manager instance
sync_manager = MultiServerSyncManager()
