"""
Catch-up Synchronization Manager
Handles synchronization for servers that have been offline and need to catch up on missed changes
"""
import os
import json
import hashlib
import shutil
import time
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple, TYPE_CHECKING
from flask import current_app
from sqlalchemy import text, desc
from app import db
import logging

# Import models for type hints only (avoids circular imports)
if TYPE_CHECKING:
    from app.models import SyncServer, SyncLog, DatabaseChange

logger = logging.getLogger(__name__)


class CatchupSyncManager:
    """
    Manages catch-up synchronization for servers that have been offline
    Provides comprehensive recovery for missed database and file changes
    """
    
    def __init__(self, app=None):
        self.app = app
        self.catchup_enabled = True
        self.max_catchup_days = 30  # Maximum days to look back for changes
        self.batch_size = 100  # Number of changes to process in each batch
        self.connection_timeout = 60  # Longer timeout for catch-up operations
        self.max_retry_attempts = 5
        self._servers_in_catchup = set()  # Track servers currently being synced
        self._unknown_table_warnings_logged = set()  # Track which table warnings we've already shown
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the catch-up sync manager with Flask app"""
        self.app = app
        
        # Load configuration
        with app.app_context():
            try:
                from app.models import SyncConfig
                self.catchup_enabled = SyncConfig.get_value('catchup_enabled', True)
                self.max_catchup_days = SyncConfig.get_value('max_catchup_days', 30)
                self.batch_size = SyncConfig.get_value('catchup_batch_size', 100)
            except Exception as e:
                logger.warning(f"Could not load catch-up configuration: {e}")
    
    def detect_servers_needing_catchup(self) -> List['SyncServer']:
        """
        Detect servers that don't have the latest data and need catch-up sync
        Returns list of servers that are missing recent changes
        """
        from app.models import SyncServer, DatabaseChange
        
        # Get all active sync servers
        active_servers = SyncServer.query.filter(
            SyncServer.is_active == True,
            SyncServer.sync_enabled == True
        ).all()
        
        servers_needing_catchup = []
        
        # Get the timestamp of the latest change in our database
        latest_change = DatabaseChange.query.order_by(DatabaseChange.timestamp.desc()).first()
        if not latest_change:
            logger.info("🔍 No database changes found - no catch-up needed")
            return []
        
        latest_change_time = latest_change.timestamp
        logger.info(f"🔍 Latest database change: {latest_change_time}")
        
        for server in active_servers:
            # Skip servers that are already in catchup to prevent queue buildup
            if server.id in self._servers_in_catchup:
                logger.debug(f"  🔄 {server.name} ({server.host}): Already in catch-up, skipping")
                continue
                
            needs_catchup = False
            reason = ""
            
            # Check if server has never synced
            if server.last_sync is None:
                needs_catchup = True
                reason = "Never synced"
            
            # Check if server's last sync is before the latest change
            elif server.last_sync < latest_change_time:
                needs_catchup = True
                # Count how many changes the server is missing
                missing_changes = DatabaseChange.query.filter(
                    DatabaseChange.timestamp > server.last_sync
                ).count()
                reason = f"Missing {missing_changes} changes since {server.last_sync.strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Check if server is currently reachable (optional - only if it needs catchup)
            if needs_catchup:
                if self.check_server_availability(server):
                    servers_needing_catchup.append(server)
                    logger.info(f"  📊 {server.name} ({server.host}): {reason} - Available for catch-up")
                else:
                    logger.info(f"  ⏸️  {server.name} ({server.host}): {reason} - Not reachable, skipping")
            else:
                logger.debug(f"  ✅ {server.name} ({server.host}): Up to date")
        
        logger.info(f"🔍 Detected {len(servers_needing_catchup)} servers needing catch-up")
        
        # Debug: Show which servers are currently in progress
        if self._servers_in_catchup:
            in_progress_names = [f"ID:{server_id}" for server_id in self._servers_in_catchup]
            logger.info(f"🔄 Servers currently in catch-up: {', '.join(in_progress_names)}")
            
        return servers_needing_catchup
    
    def check_server_availability(self, server: 'SyncServer') -> bool:
        """
        Check if a server is now available for catch-up sync
        """
        try:
            logger.info(f"🔍 Checking availability of {server.name} ({server.base_url})")
            
            url = f"{server.base_url}/api/sync/ping"
            response = requests.get(url, timeout=10, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                server.server_version = data.get('version')
                server.update_ping(success=True)
                logger.info(f"✅ Server {server.name} is now available")
                return True
            else:
                server.update_ping(success=False, error_message=f"HTTP {response.status_code}")
                logger.warning(f"❌ Server {server.name} returned HTTP {response.status_code}")
                return False
                
        except Exception as e:
            server.update_ping(success=False, error_message=str(e))
            logger.warning(f"❌ Server {server.name} is not available: {e}")
            return False
    
    def perform_catchup_sync(self, server: 'SyncServer') -> Dict[str, Any]:
        """
        Perform comprehensive catch-up synchronization for a server that was offline
        Returns detailed results of the catch-up operation
        """
        # Mark server as in catchup to prevent duplicate processing
        self._servers_in_catchup.add(server.id)
        
        logger.info(f"🚀 Starting catch-up sync for {server.name}")
        
        catchup_start = datetime.utcnow()
        results = {
            'server_id': server.id,
            'server_name': server.name,
            'started_at': catchup_start.isoformat(),
            'completed_at': None,
            'success': False,
            'database_changes': {'sent': 0, 'received': 0, 'applied': 0},
            'file_changes': {'uploaded': 0, 'downloaded': 0},
            'errors': [],
            'duration': None
        }
        
        try:
            # Step 1: Determine catch-up period
            catchup_since = self._determine_catchup_period(server)
            logger.info(f"📅 Catch-up period: since {catchup_since}")
            
            # Step 2: Exchange database changes
            db_result = self._catchup_database_changes(server, catchup_since)
            results['database_changes'] = db_result
            
            # Step 3: Synchronize file changes
            file_result = self._catchup_file_changes(server, catchup_since)
            results['file_changes'] = file_result
            
            # Step 4: Update server sync timestamp
            server.last_sync = datetime.utcnow()
            db.session.commit()
            
            results['success'] = True
            results['completed_at'] = datetime.utcnow().isoformat()
            results['duration'] = (datetime.utcnow() - catchup_start).total_seconds()
            
            logger.info(f"✅ Catch-up sync completed for {server.name} in {results['duration']:.2f} seconds")
            logger.info(f"   Database: {db_result['sent']} sent, {db_result['received']} received, {db_result['applied']} applied")
            logger.info(f"   Files: {file_result['uploaded']} uploaded, {file_result['downloaded']} downloaded")
            
        except Exception as e:
            logger.error(f"❌ Catch-up sync failed for {server.name}: {e}")
            results['errors'].append(str(e))
            results['completed_at'] = datetime.utcnow().isoformat()
            results['duration'] = (datetime.utcnow() - catchup_start).total_seconds()
        
        finally:
            # Always remove server from in-progress tracking when done
            self._servers_in_catchup.discard(server.id)
        
        return results
    
    def _determine_catchup_period(self, server: 'SyncServer') -> datetime:
        """
        Determine how far back to look for changes during catch-up
        Now uses the server's last sync time or a reasonable fallback
        """
        # If server has never synced, look back a reasonable amount (e.g., 7 days)
        if server.last_sync is None:
            fallback_time = datetime.utcnow() - timedelta(days=7)
            logger.info(f"📅 Server {server.name} has never synced, using 7-day fallback: {fallback_time}")
            return fallback_time
        
        # Use the server's last sync time as the starting point
        logger.info(f"📅 Server {server.name} last synced: {server.last_sync}")
        return server.last_sync
    
    def _catchup_database_changes(self, server: 'SyncServer', since: datetime) -> Dict[str, int]:
        """
        Perform database catch-up synchronization
        Returns counts of changes sent, received, and applied
        """
        logger.info(f"🗄️  Starting database catch-up for {server.name} since {since}")
        
        result = {'sent': 0, 'received': 0, 'applied': 0, 'errors': []}
        
        try:
            # Get all local changes since the catch-up period
            local_changes = self._get_database_changes_since(since)
            logger.info(f"📤 Found {len(local_changes)} local changes to send")
            
            # Send changes in batches to avoid overwhelming the network/server
            if local_changes:
                sent_count = self._send_database_changes_in_batches(server, local_changes)
                result['sent'] = sent_count
                logger.info(f"📤 Sent {sent_count} database changes to {server.name}")
            
            # Get all remote changes since the catch-up period
            remote_changes = self._get_remote_database_changes(server, since)
            result['received'] = len(remote_changes)
            logger.info(f"📥 Received {len(remote_changes)} database changes from {server.name}")
            
            # Apply remote changes in batches
            if remote_changes:
                applied_count = self._apply_database_changes_in_batches(remote_changes)
                result['applied'] = applied_count
                logger.info(f"✅ Applied {applied_count} database changes from {server.name}")
            
        except Exception as e:
            logger.error(f"❌ Database catch-up failed for {server.name}: {e}")
            result['errors'].append(str(e))
            raise
        
        return result
    
    def _catchup_file_changes(self, server: 'SyncServer', since: datetime) -> Dict[str, int]:
        """
        Perform file catch-up synchronization
        Returns counts of files uploaded and downloaded
        """
        logger.info(f"📁 Starting file catch-up for {server.name} since {since}")
        
        result = {'uploaded': 0, 'downloaded': 0, 'errors': []}
        
        try:
            # Sync instance files
            if server.sync_instance_files:
                instance_result = self._catchup_directory_files(server, 'instance', since)
                result['uploaded'] += instance_result['uploaded']
                result['downloaded'] += instance_result['downloaded']
            
            # Sync config files
            if server.sync_config_files:
                config_result = self._catchup_directory_files(server, 'config', since)
                result['uploaded'] += config_result['uploaded']
                result['downloaded'] += config_result['downloaded']
            
            # Sync uploads
            if server.sync_uploads:
                uploads_result = self._catchup_directory_files(server, 'uploads', since)
                result['uploaded'] += uploads_result['uploaded']
                result['downloaded'] += uploads_result['downloaded']
            
        except Exception as e:
            logger.error(f"❌ File catch-up failed for {server.name}: {e}")
            result['errors'].append(str(e))
            raise
        
        return result
    
    def _get_database_changes_since(self, since: datetime) -> List[Dict]:
        """
        Get all database changes since a specific timestamp for catch-up
        """
        changes = []
        
        try:
            # Import models here to avoid circular imports
            from app.models import DatabaseChange, User, ScoutingData, Match, Team, Event
            
            logger.info(f"🔍 Getting database changes since {since}")
            
            # Get tracked changes first
            tracked_changes = DatabaseChange.query.filter(
                DatabaseChange.timestamp > since
            ).order_by(DatabaseChange.timestamp.asc()).all()
            
            if tracked_changes:
                logger.info(f"📋 Found {len(tracked_changes)} tracked changes")
                for change in tracked_changes:
                    changes.append(change.to_dict())
                return changes
            
            # Fallback: If no change tracking, detect changes by timestamp
            logger.info("📋 No tracked changes found, using timestamp-based detection")
            
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
                        query = model_class.query.filter(modified_field > since)
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
                                'timestamp': datetime.utcnow().isoformat()
                            })
                        
                        logger.info(f"📋 Found {len(modified_records)} changes in {table_name} since {since}")
                
                except Exception as e:
                    logger.warning(f"⚠️  Could not get changes for {table_name}: {e}")
            
            logger.info(f"📋 Total database changes found: {len(changes)}")
            
        except Exception as e:
            logger.error(f"❌ Error getting database changes: {e}")
            raise
        
        return changes
    
    def _send_database_changes_in_batches(self, server: 'SyncServer', changes: List[Dict]) -> int:
        """
        Send database changes to remote server in batches
        """
        total_sent = 0
        batch_count = 0
        
        for i in range(0, len(changes), self.batch_size):
            batch = changes[i:i + self.batch_size]
            batch_count += 1
            
            logger.info(f"📤 Sending batch {batch_count} ({len(batch)} changes) to {server.name}")
            
            try:
                url = f"{server.base_url}/api/sync/receive-changes"
                payload = {
                    'changes': batch,
                    'server_id': self._get_server_id(),
                    'timestamp': datetime.utcnow().isoformat(),
                    'catchup_mode': True
                }
                
                response = requests.post(url, json=payload, 
                                       timeout=self.connection_timeout, verify=False)
                
                if response.status_code == 200:
                    result = response.json()
                    applied_count = result.get('applied_count', 0)
                    total_sent += applied_count
                    logger.info(f"✅ Batch {batch_count} applied successfully ({applied_count} changes)")
                else:
                    logger.error(f"❌ Batch {batch_count} failed: HTTP {response.status_code} - {response.text}")
                    # Continue with next batch instead of failing completely
                
                # Small delay between batches to avoid overwhelming the server
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"❌ Error sending batch {batch_count}: {e}")
                # Continue with next batch
                continue
        
        return total_sent
    
    def _get_remote_database_changes(self, server: 'SyncServer', since: datetime) -> List[Dict]:
        """
        Get database changes from remote server since specified time
        """
        try:
            url = f"{server.base_url}/api/sync/changes"
            params = {
                'since': since.isoformat(),
                'server_id': self._get_server_id(),
                'catchup_mode': True
            }
            
            logger.info(f"📥 Requesting changes from {server.name} since {since}")
            
            response = requests.get(url, params=params, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                changes = data.get('changes', [])
                logger.info(f"📥 Received {len(changes)} changes from {server.name}")
                return changes
            else:
                logger.error(f"❌ Failed to get changes from {server.name}: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error getting changes from {server.name}: {e}")
            return []
    
    def _apply_database_changes_in_batches(self, changes: List[Dict]) -> int:
        """
        Apply database changes in batches for better performance
        """
        total_applied = 0
        batch_count = 0
        
        # Disable change tracking during catch-up to prevent recursive tracking
        from app.utils.change_tracking import disable_change_tracking, enable_change_tracking
        disable_change_tracking()
        
        try:
            for i in range(0, len(changes), self.batch_size):
                batch = changes[i:i + self.batch_size]
                batch_count += 1
                
                logger.info(f"📥 Applying batch {batch_count} ({len(batch)} changes)")
                
                try:
                    applied_count = self._apply_change_batch(batch)
                    total_applied += applied_count
                    logger.info(f"✅ Applied batch {batch_count} successfully ({applied_count} changes)")
                    
                    # Commit each batch separately
                    db.session.commit()
                    
                except Exception as e:
                    logger.error(f"❌ Error applying batch {batch_count}: {e}")
                    db.session.rollback()
                    # Continue with next batch
                    continue
        
        finally:
            # Re-enable change tracking
            enable_change_tracking()
        
        return total_applied
    
    def _apply_change_batch(self, changes: List[Dict]) -> int:
        """
        Apply a batch of database changes
        """
        # Import models here to avoid circular imports
        from app.models import User, ScoutingData, Match, Team, Event
        
        model_map = {
            'user': User,  # Fixed: table name is 'user' not 'users'
            'users': User,  # Keep both for compatibility
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
                    # Only warn once per table name to avoid spam
                    if table_name not in self._unknown_table_warnings_logged:
                        self._unknown_table_warnings_logged.add(table_name)
                        logger.warning(f"⚠️  Unknown table for catch-up: {table_name} (future warnings for this table suppressed)")
                    continue
                
                model_class = model_map[table_name]
                
                if operation in ['upsert', 'insert', 'update']:
                    # Handle insert/update operations
                    if record_id:
                        existing_record = model_class.query.get(record_id)
                        if existing_record:
                            # Update existing record
                            for key, value in data.items():
                                if key == 'id':
                                    continue
                                if hasattr(existing_record, key):
                                    # Convert ISO date strings back to datetime
                                    if key.endswith('_at') and isinstance(value, str):
                                        try:
                                            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                        except:
                                            pass
                                    setattr(existing_record, key, value)
                        else:
                            # Create new record
                            processed_data = {}
                            for key, value in data.items():
                                if key.endswith('_at') and isinstance(value, str):
                                    try:
                                        processed_data[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                    except:
                                        processed_data[key] = value
                                else:
                                    processed_data[key] = value
                            
                            new_record = model_class(**processed_data)
                            db.session.add(new_record)
                    
                    applied_count += 1
                
                elif operation == 'delete':
                    # Handle hard deletion
                    if record_id:
                        existing_record = model_class.query.get(record_id)
                        if existing_record:
                            db.session.delete(existing_record)
                            applied_count += 1
                
                elif operation == 'soft_delete':
                    # Handle soft deletion
                    if record_id:
                        existing_record = model_class.query.get(record_id)
                        if existing_record and hasattr(existing_record, 'is_active'):
                            existing_record.is_active = False
                            if hasattr(existing_record, 'updated_at'):
                                existing_record.updated_at = datetime.utcnow()
                            applied_count += 1
                
                elif operation == 'reactivate':
                    # Handle reactivation
                    if record_id:
                        existing_record = model_class.query.get(record_id)
                        if existing_record and hasattr(existing_record, 'is_active'):
                            existing_record.is_active = True
                            if hasattr(existing_record, 'updated_at'):
                                existing_record.updated_at = datetime.utcnow()
                            applied_count += 1
                
            except Exception as e:
                logger.warning(f"⚠️  Error applying change to {table_name}: {e}")
                continue
        
        return applied_count
    
    def _catchup_directory_files(self, server: 'SyncServer', directory_type: str, since: datetime) -> Dict[str, int]:
        """
        Perform catch-up file synchronization for a specific directory
        """
        result = {'uploaded': 0, 'downloaded': 0}
        
        try:
            # Get directory path
            if directory_type == 'instance':
                directory_path = current_app.instance_path
            elif directory_type == 'config':
                directory_path = os.path.join(os.getcwd(), 'config')
            elif directory_type == 'uploads':
                directory_path = os.path.join(os.getcwd(), 'uploads')
            else:
                logger.warning(f"⚠️  Unknown directory type: {directory_type}")
                return result
            
            # Get local file checksums (only files modified since catch-up period)
            local_checksums = self._get_directory_checksums_since(directory_path, since)
            logger.info(f"📁 Found {len(local_checksums)} local files in {directory_type} modified since {since}")
            
            # Get remote file checksums
            url = f"{server.base_url}/api/sync/files/checksums"
            response = requests.get(url, params={'path': directory_type}, 
                                  timeout=self.connection_timeout, verify=False)
            
            if response.status_code != 200:
                logger.error(f"❌ Failed to get remote checksums for {directory_type}: {response.text}")
                return result
            
            remote_checksums = response.json()
            logger.info(f"📁 Found {len(remote_checksums)} remote files in {directory_type}")
            
            # Compare and sync files
            files_to_upload, files_to_download = self._compare_checksums_for_catchup(
                local_checksums, remote_checksums, since)
            
            logger.info(f"📁 Files to upload: {len(files_to_upload)}, Files to download: {len(files_to_download)}")
            
            # Upload files that are newer locally
            for file_info in files_to_upload:
                try:
                    self._upload_file_to_server(server, file_info['path'], directory_type)
                    result['uploaded'] += 1
                    logger.debug(f"📤 Uploaded {file_info['path']}")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to upload {file_info['path']}: {e}")
            
            # Download files that are newer remotely
            for file_info in files_to_download:
                try:
                    self._download_file_from_server(server, file_info['path'], directory_type)
                    result['downloaded'] += 1
                    logger.debug(f"📥 Downloaded {file_info['path']}")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to download {file_info['path']}: {e}")
            
        except Exception as e:
            logger.error(f"❌ Directory catch-up failed for {directory_type}: {e}")
            raise
        
        return result
    
    def _get_directory_checksums_since(self, directory_path: str, since: datetime) -> Dict[str, Dict]:
        """
        Get checksums for files in a directory that have been modified since a specific time
        """
        checksums = {}
        
        # Files to exclude from sync (database files and lock files)
        excluded_extensions = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.lock'}
        excluded_files = {'app.db', 'database.db', 'scouting.db', 'app.db-wal', 'app.db-shm'}
        
        if not os.path.exists(directory_path):
            return checksums
        
        for root, dirs, files in os.walk(directory_path):
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
                    continue
                
                try:
                    stat = os.stat(file_path)
                    file_modified = datetime.fromtimestamp(stat.st_mtime)
                    
                    # Only include files modified since the catch-up period
                    if file_modified > since:
                        with open(file_path, 'rb') as f:
                            content = f.read()
                            checksum = hashlib.sha256(content).hexdigest()
                        
                        checksums[relative_path] = {
                            'checksum': checksum,
                            'size': stat.st_size,
                            'modified': file_modified.isoformat()
                        }
                except Exception as e:
                    logger.warning(f"⚠️  Could not process file {file_path}: {e}")
        
        return checksums
    
    def _compare_checksums_for_catchup(self, local_checksums: Dict, remote_checksums: Dict, since: datetime) -> Tuple[List[Dict], List[Dict]]:
        """
        Compare local and remote checksums for catch-up sync
        Only consider files that have been modified since the catch-up period
        """
        files_to_upload = []
        files_to_download = []
        
        # Check for files to upload (local is newer or remote doesn't have)
        for path, local_info in local_checksums.items():
            local_modified = datetime.fromisoformat(local_info['modified'])
            
            # Only consider files modified since catch-up period
            if local_modified <= since:
                continue
            
            if path not in remote_checksums:
                files_to_upload.append({'path': path, **local_info})
            else:
                remote_info = remote_checksums[path]
                if local_info['checksum'] != remote_info['checksum']:
                    remote_modified = datetime.fromisoformat(remote_info['modified'])
                    
                    if local_modified > remote_modified:
                        files_to_upload.append({'path': path, **local_info})
                    elif remote_modified > since:  # Only download if remote was modified during catch-up period
                        files_to_download.append({'path': path, **remote_info})
        
        # Check for files to download (remote has newer versions modified during catch-up period)
        for path, remote_info in remote_checksums.items():
            remote_modified = datetime.fromisoformat(remote_info['modified'])
            
            # Only consider files modified since catch-up period
            if remote_modified <= since:
                continue
            
            if path not in local_checksums:
                files_to_download.append({'path': path, **remote_info})
        
        return files_to_upload, files_to_download
    
    def _upload_file_to_server(self, server: 'SyncServer', file_path: str, base_folder: str):
        """Upload a file to a remote server during catch-up"""
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
                    'server_id': self._get_server_id(),
                    'catchup_mode': 'true'
                }
                
                response = requests.post(url, files=files, data=data, 
                                       timeout=self.connection_timeout, verify=False)
                
                if response.status_code != 200:
                    raise Exception(f"Upload failed: {response.text}")
            
        except Exception as e:
            logger.error(f"❌ Failed to upload {file_path} to {server.name}: {e}")
            raise
    
    def _download_file_from_server(self, server: 'SyncServer', file_path: str, base_folder: str):
        """Download a file from a remote server during catch-up"""
        try:
            url = f"{server.base_url}/api/sync/files/download"
            params = {
                'path': file_path,
                'base_folder': base_folder,
                'catchup_mode': 'true'
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
            
        except Exception as e:
            logger.error(f"❌ Failed to download {file_path} from {server.name}: {e}")
            raise
    
    def _get_server_id(self):
        """Get the current server ID"""
        try:
            # Use Universal Sync System server ID
            return 'universal-sync-server'
        except:
            return 'unknown'
    
    def run_automatic_catchup(self):
        """
        Run automatic catch-up for all servers that don't have the latest data
        This should be called periodically to detect and sync servers missing changes
        """
        if not self.catchup_enabled:
            return
        
        logger.info("🔍 Running automatic catch-up scan...")
        
        servers_needing_catchup = self.detect_servers_needing_catchup()
        if not servers_needing_catchup:
            logger.info("✅ All servers are up to date")
            return
        
        catchup_results = []
        
        for server in servers_needing_catchup:
            try:
                # Server is already confirmed to be available in detect_servers_needing_catchup
                # Perform catch-up sync
                result = self.perform_catchup_sync(server)
                catchup_results.append(result)
            
            except Exception as e:
                logger.error(f"❌ Catch-up failed for {server.name}: {e}")
                continue
        
        if catchup_results:
            logger.info(f"🎯 Completed catch-up for {len(catchup_results)} servers")
            for result in catchup_results:
                if result['success']:
                    logger.info(f"  ✅ {result['server_name']}: {result['database_changes']['applied']} DB changes, {result['file_changes']['downloaded']} files")
                else:
                    logger.info(f"  ❌ {result['server_name']}: Failed - {len(result['errors'])} errors")
        
        return catchup_results


# Global catch-up sync manager instance
catchup_sync_manager = CatchupSyncManager()
