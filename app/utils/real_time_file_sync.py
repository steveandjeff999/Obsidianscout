import os
import threading
import time
import hashlib
import json
import queue
from datetime import datetime, timedelta
from pathlib import Path
from typing import Set, Dict, Any, Optional, List
from collections import defaultdict, deque

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from app.models import SyncServer, SyncLog, db
from app.utils.multi_server_sync import MultiServerSyncManager
import logging

logger = logging.getLogger(__name__)


class SyncFailure:
    """Represents a failed sync operation for retry"""
    
    def __init__(self, file_path: str, event_type: str, server_id: int, error: str):
        self.file_path = file_path
        self.event_type = event_type
        self.server_id = server_id
        self.error = error
        self.timestamp = datetime.utcnow()
        self.retry_count = 0
        self.next_retry = datetime.utcnow() + timedelta(seconds=5)  # Initial retry in 5 seconds
    
    def should_retry(self) -> bool:
        """Check if this failure should be retried"""
        max_retries = 10
        max_age_hours = 24
        
        if self.retry_count >= max_retries:
            return False
        
        if (datetime.utcnow() - self.timestamp).total_seconds() > max_age_hours * 3600:
            return False
        
        return datetime.utcnow() >= self.next_retry
    
    def increment_retry(self):
        """Increment retry count and calculate next retry time with exponential backoff"""
        self.retry_count += 1
        # Exponential backoff: 5s, 10s, 20s, 40s, 80s, then cap at 5 minutes
        delay_seconds = min(5 * (2 ** self.retry_count), 300)
        self.next_retry = datetime.utcnow() + timedelta(seconds=delay_seconds)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/debugging"""
        return {
            'file_path': self.file_path,
            'event_type': self.event_type,
            'server_id': self.server_id,
            'error': self.error,
            'timestamp': self.timestamp.isoformat(),
            'retry_count': self.retry_count,
            'next_retry': self.next_retry.isoformat()
        }


class FileConflictResolver:
    """Handles file conflicts during synchronization"""
    
    @staticmethod
    def resolve_conflict(local_file: str, remote_checksum: str, remote_modified: str) -> str:
        """
        Resolve file conflicts based on modification time and checksum
        Returns: 'local', 'remote', or 'backup'
        """
        try:
            if not os.path.exists(local_file):
                return 'remote'  # Local file doesn't exist, use remote
            
            # Get local file info
            local_stat = os.stat(local_file)
            local_modified = datetime.fromtimestamp(local_stat.st_mtime)
            remote_modified_dt = datetime.fromisoformat(remote_modified.replace('Z', '+00:00'))
            
            # Calculate local checksum
            with open(local_file, 'rb') as f:
                local_content = f.read()
                local_checksum = hashlib.sha256(local_content).hexdigest()
            
            if local_checksum == remote_checksum:
                return 'local'  # Files are identical, no conflict
            
            # Files are different, compare modification times
            time_diff = (local_modified - remote_modified_dt.replace(tzinfo=None)).total_seconds()
            
            if abs(time_diff) < 5:  # Within 5 seconds, create backup
                return 'backup'
            elif time_diff > 0:  # Local is newer
                return 'local'
            else:  # Remote is newer
                return 'remote'
                
        except Exception as e:
            logger.error(f"Error resolving conflict for {local_file}: {e}")
            return 'backup'  # Safe default


class RealTimeFileEventHandler(FileSystemEventHandler):
    """File system event handler for real-time file synchronization with reliability improvements"""
    
    def __init__(self, sync_manager, app=None, debounce_time=0.5):
        super().__init__()
        self.sync_manager = sync_manager
        self.app = app
        self.conflict_resolver = FileConflictResolver()
        self.debounce_time = debounce_time  # Reduced to 0.5 seconds for better responsiveness
        self.pending_files = {}  # {file_path: timestamp}
        self.lock = threading.Lock()
        
        # Reliability features
        self.failed_syncs = queue.Queue()  # Queue for failed syncs
        self.sync_stats = defaultdict(int)  # Track sync statistics
        self.file_checksums = {}  # Track file checksums to detect changes
        
        # Enhanced file exclusion patterns
        self.excluded_extensions = {
            '.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.db-journal',  # Database files
            '.lock', '.tmp', '.temp', '.swp', '.swo',  # Temporary files
            '.log', '.pid', '.pyc', '.pyo', '__pycache__',  # Log and cache files
            '.DS_Store', 'Thumbs.db', '.git'  # System files
        }
        self.excluded_files = {
            'app.db', 'database.db', 'scouting.db', 'instance.db',
            'app.db-wal', 'app.db-shm', 'app.db-journal'
        }
        self.excluded_patterns = {
            '__pycache__', '.git', '.venv', 'node_modules', '.pytest_cache'
        }
        
        # Start background threads
        self.debounce_thread = threading.Thread(target=self._process_pending_files, daemon=True)
        self.debounce_thread.start()
        
        self.retry_thread = threading.Thread(target=self._process_failed_syncs, daemon=True)
        self.retry_thread.start()
    
    def _calculate_checksum(self, file_path: str) -> Optional[str]:
        """Calculate SHA256 checksum of a file"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.warning(f"Could not calculate checksum for {file_path}: {e}")
            return None
    
    def _should_sync_file(self, file_path: str) -> bool:
        """Check if file should be synced with enhanced change detection"""
        try:
            file_name = os.path.basename(file_path).lower()
            file_ext = os.path.splitext(file_name)[1].lower()
            file_path_lower = file_path.lower()
            
            # Skip excluded file extensions
            if file_ext in self.excluded_extensions:
                logger.debug(f"Skipping file due to excluded extension: {file_path}")
                return False
            
            # Skip excluded file names
            if file_name in self.excluded_files:
                logger.debug(f"Skipping file due to excluded filename: {file_path}")
                return False
            
            # Skip excluded path patterns
            for pattern in self.excluded_patterns:
                if pattern in file_path_lower:
                    logger.debug(f"Skipping file due to excluded pattern '{pattern}': {file_path}")
                    return False
            
            # Skip hidden files (starting with .)
            if file_name.startswith('.') and file_name not in {'.gitignore', '.htaccess'}:
                logger.debug(f"Skipping hidden file: {file_path}")
                return False
            
            # Skip if file doesn't exist (for non-delete events)
            if not os.path.exists(file_path):
                logger.debug(f"File doesn't exist, cannot sync: {file_path}")
                return False
            
            # Skip files that are too large (> 100MB)
            try:
                file_size = os.path.getsize(file_path)
                if file_size > 100 * 1024 * 1024:  # 100MB
                    logger.warning(f"Skipping large file (>{file_size/1024/1024:.1f}MB): {file_path}")
                    return False
            except OSError:
                logger.warning(f"Could not get file size for: {file_path}")
                return False
            
            # Check if file actually changed using checksum
            current_checksum = self._calculate_checksum(file_path)
            if current_checksum is None:
                logger.debug(f"Could not calculate checksum for: {file_path}")
                return False
            
            previous_checksum = self.file_checksums.get(file_path)
            if current_checksum == previous_checksum:
                # File hasn't actually changed
                logger.debug(f"File content unchanged (checksum match): {file_path}")
                return False
            
            # Update checksum
            self.file_checksums[file_path] = current_checksum
            logger.info(f"File should be synced: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking if file should be synced: {file_path}, error: {e}")
            return False
    
    def _process_failed_syncs(self):
        """Process failed syncs with retry logic"""
        while True:
            try:
                time.sleep(30)  # Check every 30 seconds
                
                # Process retry queue
                retry_items = []
                while not self.failed_syncs.empty():
                    try:
                        failed_sync = self.failed_syncs.get_nowait()
                        if failed_sync.should_retry():
                            retry_items.append(failed_sync)
                        else:
                            # Log permanently failed sync
                            logger.error(f"Permanently failed sync after {failed_sync.retry_count} retries: {failed_sync.to_dict()}")
                    except queue.Empty:
                        break
                
                # Retry failed syncs
                for failed_sync in retry_items:
                    try:
                        success = self._retry_sync_operation(failed_sync)
                        if not success:
                            failed_sync.increment_retry()
                            self.failed_syncs.put(failed_sync)
                        else:
                            logger.info(f"Successfully retried sync for {failed_sync.file_path} after {failed_sync.retry_count} retries")
                    except Exception as e:
                        logger.error(f"Error retrying sync: {e}")
                        failed_sync.increment_retry()
                        self.failed_syncs.put(failed_sync)
                
            except Exception as e:
                logger.error(f"Error in failed sync processor: {e}")
                time.sleep(60)  # Wait longer before retrying
    
    def _retry_sync_operation(self, failed_sync: SyncFailure) -> bool:
        """Retry a failed sync operation"""
        try:
            if self.app:
                with self.app.app_context():
                    return self._execute_sync_retry(failed_sync)
            else:
                return self._execute_sync_retry(failed_sync)
        except Exception as e:
            logger.error(f"Exception during retry: {e}")
            return False
    
    def _execute_sync_retry(self, failed_sync: SyncFailure) -> bool:
        """Execute the actual sync retry"""
        server = SyncServer.query.get(failed_sync.server_id)
        if not server or not server.is_active:
            logger.warning(f"Server {failed_sync.server_id} no longer active, abandoning retry")
            return True  # Don't retry inactive servers
        
        if failed_sync.event_type == 'deleted':
            return self.sync_manager.delete_file_on_server(server, failed_sync.file_path)
        else:
            if os.path.exists(failed_sync.file_path):
                return self.sync_manager.upload_file_to_server(server, failed_sync.file_path)
            else:
                logger.info(f"File {failed_sync.file_path} no longer exists, marking retry as successful")
                return True
    
    def _handle_sync_conflict(self, file_path: str, server_response: Dict[str, Any]) -> bool:
        """Handle file conflicts during sync"""
        try:
            if 'conflict' in server_response:
                conflict_info = server_response['conflict']
                resolution = self.conflict_resolver.resolve_conflict(
                    file_path,
                    conflict_info.get('remote_checksum', ''),
                    conflict_info.get('remote_modified', '')
                )
                
                if resolution == 'backup':
                    # Create backup and use remote version
                    backup_path = f"{file_path}.backup.{int(time.time())}"
                    os.rename(file_path, backup_path)
                    logger.info(f"Created backup {backup_path} and accepting remote version")
                    return True
                elif resolution == 'local':
                    # Force upload local version
                    logger.info(f"Local version newer, forcing upload for {file_path}")
                    return False  # Will trigger retry with force flag
                else:  # resolution == 'remote'
                    # Accept remote version (download it)
                    logger.info(f"Remote version newer, accepting for {file_path}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error handling conflict for {file_path}: {e}")
            return False
    
    def on_modified(self, event):
        """Handle file modification events"""
        if not event.is_directory and self._should_sync_file(event.src_path):
            self._queue_file_for_sync(event.src_path, 'modified')
    
    def on_created(self, event):
        """Handle file creation events"""
        if not event.is_directory and self._should_sync_file(event.src_path):
            self._queue_file_for_sync(event.src_path, 'created')
    
    def on_deleted(self, event):
        """Handle file deletion events"""
        if not event.is_directory:
            # For delete events, we can't check if file should be synced since it's gone
            # But we should sync the deletion if it was a tracked file or meets basic criteria
            file_path = event.src_path
            file_name = os.path.basename(file_path).lower()
            file_ext = os.path.splitext(file_name)[1].lower()
            
            # Check if this was a file we would have tracked
            should_sync_delete = True
            
            # Skip excluded extensions and filenames
            if file_ext in self.excluded_extensions or file_name in self.excluded_files:
                should_sync_delete = False
            
            # Skip excluded patterns
            file_path_lower = file_path.lower()
            for pattern in self.excluded_patterns:
                if pattern in file_path_lower:
                    should_sync_delete = False
                    break
            
            # Skip hidden files
            if file_name.startswith('.') and file_name not in {'.gitignore', '.htaccess'}:
                should_sync_delete = False
            
            if should_sync_delete or file_path in self.file_checksums:
                # Remove from checksum tracking
                self.file_checksums.pop(file_path, None)
                self._queue_file_for_sync(file_path, 'deleted')
                logger.info(f"Queued file deletion for sync: {file_path}")
            else:
                logger.debug(f"Skipping deletion sync for excluded file: {file_path}")
    
    def on_moved(self, event):
        """Handle file move/rename events"""
        if not event.is_directory:
            # Handle move as delete + create with proper exclusion checking
            src_path = event.src_path
            dest_path = event.dest_path
            
            # Handle source (deletion)
            if src_path in self.file_checksums:
                self.file_checksums.pop(src_path, None)
                self._queue_file_for_sync(src_path, 'deleted')
                logger.info(f"Queued source file deletion for move: {src_path}")
            
            # Handle destination (creation)
            if self._should_sync_file(dest_path):
                self._queue_file_for_sync(dest_path, 'created')
                logger.info(f"Queued destination file creation for move: {dest_path}")
            else:
                logger.debug(f"Destination file excluded from sync: {dest_path}")
    
    def _queue_file_for_sync(self, file_path: str, event_type: str):
        """Queue file for syncing with debouncing and enhanced reliability"""
        try:
            with self.lock:
                current_time = time.time()
                
                # Create event key for tracking
                event_key = f"{file_path}:{event_type}"
                
                # Update pending files with new timestamp
                self.pending_files[event_key] = {
                    'file_path': file_path,
                    'event_type': event_type,
                    'timestamp': current_time
                }
                
                logger.debug(f"Queued {event_type} event for {file_path}")
                
        except Exception as e:
            logger.error(f"Error queuing file for sync: {e}")
    
    def _process_pending_files(self):
        """Process pending file events with debouncing and enhanced error handling"""
        while True:
            try:
                time.sleep(0.2)  # Check every 200ms for better responsiveness
                current_time = time.time()
                
                events_to_process = []
                
                with self.lock:
                    events_to_remove = []
                    
                    for event_key, event_data in self.pending_files.items():
                        # Check if enough time has passed (debouncing)
                        if current_time - event_data['timestamp'] >= self.debounce_time:
                            events_to_process.append(event_data)
                            events_to_remove.append(event_key)
                    
                    # Remove processed events
                    for event_key in events_to_remove:
                        del self.pending_files[event_key]
                
                # Process events outside the lock
                for event_data in events_to_process:
                    self._sync_file_with_reliability(
                        event_data['file_path'], 
                        event_data['event_type']
                    )
                    
            except Exception as e:
                logger.error(f"Error in pending files processor: {e}")
                time.sleep(2)  # Wait before retrying
    
    def _sync_file_with_reliability(self, file_path: str, event_type: str):
        """Sync file with enhanced reliability and error handling"""
        try:
            if self.app:
                with self.app.app_context():
                    self._execute_file_sync(file_path, event_type)
            else:
                self._execute_file_sync(file_path, event_type)
                
        except Exception as e:
            logger.error(f"Error syncing file {file_path}: {e}")
    
    def _execute_file_sync(self, file_path: str, event_type: str):
        """Execute file synchronization with retry logic"""
        try:
            # Get all active sync servers
            servers = SyncServer.query.filter_by(is_active=True).all()
            
            for server in servers:
                try:
                    success = False
                    error_msg = None
                    
                    if event_type == 'deleted':
                        success = self.sync_manager.delete_file_on_server(server, file_path)
                    else:
                        if os.path.exists(file_path):
                            success = self.sync_manager.upload_file_to_server(server, file_path)
                        else:
                            logger.warning(f"File {file_path} no longer exists, skipping sync to {server.name}")
                            continue
                    
                    if success:
                        logger.info(f"Successfully synced {event_type} for {file_path} to {server.name}")
                        self.sync_stats[f'success_{event_type}'] += 1
                        
                        # Log successful sync
                        sync_log = SyncLog(
                            operation=f'file_{event_type}',
                            details=f'File: {file_path}',
                            success=True,
                            sync_server_id=server.id
                        )
                        db.session.add(sync_log)
                        
                    else:
                        error_msg = f"Sync operation failed for {event_type}"
                        logger.error(f"Failed to sync {event_type} for {file_path} to {server.name}")
                        self.sync_stats[f'failed_{event_type}'] += 1
                        
                        # Queue for retry
                        failed_sync = SyncFailure(file_path, event_type, server.id, error_msg)
                        self.failed_syncs.put(failed_sync)
                        
                        # Log failed sync
                        sync_log = SyncLog(
                            operation=f'file_{event_type}',
                            details=f'File: {file_path}, Error: {error_msg}',
                            success=False,
                            sync_server_id=server.id
                        )
                        db.session.add(sync_log)
                
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Exception syncing {event_type} for {file_path} to {server.name}: {error_msg}")
                    self.sync_stats[f'exception_{event_type}'] += 1
                    
                    # Queue for retry
                    failed_sync = SyncFailure(file_path, event_type, server.id, error_msg)
                    self.failed_syncs.put(failed_sync)
                    
                    # Log exception
                    sync_log = SyncLog(
                        operation=f'file_{event_type}',
                        details=f'File: {file_path}, Exception: {error_msg}',
                        success=False,
                        sync_server_id=server.id
                    )
                    db.session.add(sync_log)
            
            # Commit all sync logs
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Database error during file sync: {e}")
            try:
                db.session.rollback()
            except:
                pass
    
    def get_sync_statistics(self) -> Dict[str, Any]:
        """Get current sync statistics for monitoring"""
        return {
            'sync_stats': dict(self.sync_stats),
            'pending_files': len(self.pending_files),
            'failed_syncs_queue': self.failed_syncs.qsize(),
            'tracked_files': len(self.file_checksums)
        }


# Observer management functions
file_observer = None
file_event_handler = None


def setup_real_time_file_sync(app, base_dir=None):
    """Set up real-time file synchronization with enhanced reliability"""
    global file_observer, file_event_handler
    
    if file_observer is not None:
        logger.info("Real-time file sync already running")
        return
    
    try:
        # Initialize sync manager
        sync_manager = MultiServerSyncManager()
        
        # Create event handler with app context
        file_event_handler = RealTimeFileEventHandler(sync_manager, app)
        
        # Set up observer
        file_observer = Observer()
        
        # Determine directory to watch
        if base_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        
        # Watch the instance directory and templates directory
        instance_dir = os.path.join(base_dir, 'instance')
        templates_dir = os.path.join(base_dir, 'app', 'templates')
        static_dir = os.path.join(base_dir, 'app', 'static')
        
        directories_to_watch = []
        for directory in [instance_dir, templates_dir, static_dir]:
            if os.path.exists(directory):
                directories_to_watch.append(directory)
        
        if not directories_to_watch:
            logger.warning("No directories found to watch for file sync")
            return
        
        # Add each directory to the observer
        for directory in directories_to_watch:
            file_observer.schedule(file_event_handler, directory, recursive=True)
            logger.info(f"Watching directory for real-time file sync: {directory}")
        
        # Start observer
        file_observer.start()
        logger.info("Real-time file synchronization with enhanced reliability started successfully")
        
        # Log initial statistics
        stats = file_event_handler.get_sync_statistics()
        logger.info(f"File sync initialized with stats: {stats}")
        
    except Exception as e:
        logger.error(f"Failed to set up real-time file sync: {e}")
        if file_observer:
            try:
                file_observer.stop()
                file_observer = None
            except:
                pass


def stop_real_time_file_sync():
    """Stop real-time file synchronization"""
    global file_observer, file_event_handler
    
    if file_observer:
        try:
            file_observer.stop()
            file_observer.join(timeout=5)
            logger.info("Real-time file synchronization stopped")
        except Exception as e:
            logger.error(f"Error stopping file sync: {e}")
        finally:
            file_observer = None
            file_event_handler = None


def get_file_sync_status():
    """Get current file sync status and statistics"""
    global file_observer, file_event_handler
    
    if not file_observer or not file_event_handler:
        return {
            'active': False,
            'message': 'File sync not running'
        }
    
    try:
        stats = file_event_handler.get_sync_statistics()
        return {
            'active': file_observer.is_alive(),
            'statistics': stats,
            'message': 'File sync running with enhanced reliability'
        }
    except Exception as e:
        return {
            'active': False,
            'error': str(e),
            'message': 'Error getting file sync status'
        }
