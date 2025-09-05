"""
Sync Utilities
Helper functions for multi-server synchronization
"""
import os
import json
import time
import threading
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from flask import current_app
from app.models import db
import traceback

class SyncLockManager:
    """Manages file-based locks for sync operations"""
    
    def __init__(self, lock_dir: str = None):
        self.lock_dir = lock_dir or os.path.join(os.getcwd(), 'instance', 'locks')
        self.ensure_lock_directory()
    
    def ensure_lock_directory(self):
        """Ensure lock directory exists"""
        try:
            os.makedirs(self.lock_dir, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create lock directory {self.lock_dir}: {e}")
    
    def acquire_lock(self, lock_name: str, timeout: int = 30) -> bool:
        """
        Acquire a file-based lock
        Returns True if lock acquired, False if timeout
        """
        lock_file = os.path.join(self.lock_dir, f"{lock_name}.lock")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Try to create lock file exclusively
                with open(lock_file, 'x') as f:
                    lock_data = {
                        'acquired_at': datetime.utcnow().isoformat(),
                        'process_id': os.getpid(),
                        'lock_name': lock_name
                    }
                    json.dump(lock_data, f)
                return True
            except FileExistsError:
                # Lock exists, check if it's stale
                if self.is_stale_lock(lock_file):
                    self.release_lock(lock_name, force=True)
                    continue
                time.sleep(0.1)
            except Exception as e:
                print(f"Error acquiring lock {lock_name}: {e}")
                return False
        
        return False
    
    def release_lock(self, lock_name: str, force: bool = False) -> bool:
        """Release a file-based lock"""
        lock_file = os.path.join(self.lock_dir, f"{lock_name}.lock")
        
        try:
            if os.path.exists(lock_file):
                if not force:
                    # Verify we own the lock
                    with open(lock_file, 'r') as f:
                        lock_data = json.load(f)
                        if lock_data.get('process_id') != os.getpid():
                            print(f"Warning: Attempting to release lock owned by different process")
                
                os.remove(lock_file)
                return True
        except Exception as e:
            print(f"Error releasing lock {lock_name}: {e}")
        
        return False
    
    def is_stale_lock(self, lock_file: str, max_age_minutes: int = 10) -> bool:
        """Check if a lock file is stale (older than max_age_minutes)"""
        try:
            if not os.path.exists(lock_file):
                return False
            
            with open(lock_file, 'r') as f:
                lock_data = json.load(f)
                acquired_at = datetime.fromisoformat(lock_data['acquired_at'])
                age = datetime.utcnow() - acquired_at
                
                return age > timedelta(minutes=max_age_minutes)
        except Exception:
            # If we can't read the lock file, consider it stale
            return True
    
    def list_active_locks(self) -> List[Dict[str, Any]]:
        """List all active locks"""
        locks = []
        try:
            if not os.path.exists(self.lock_dir):
                return locks
            
            for filename in os.listdir(self.lock_dir):
                if filename.endswith('.lock'):
                    lock_file = os.path.join(self.lock_dir, filename)
                    try:
                        with open(lock_file, 'r') as f:
                            lock_data = json.load(f)
                            lock_data['filename'] = filename
                            locks.append(lock_data)
                    except Exception as e:
                        print(f"Error reading lock file {filename}: {e}")
        except Exception as e:
            print(f"Error listing locks: {e}")
        
        return locks
    
    def cleanup_stale_locks(self):
        """Clean up stale lock files"""
        try:
            for lock_info in self.list_active_locks():
                lock_file = os.path.join(self.lock_dir, lock_info['filename'])
                if self.is_stale_lock(lock_file):
                    try:
                        os.remove(lock_file)
                        print(f"Cleaned up stale lock: {lock_info['filename']}")
                    except Exception as e:
                        print(f"Error cleaning stale lock {lock_info['filename']}: {e}")
        except Exception as e:
            print(f"Error during lock cleanup: {e}")

class SyncUtils:
    """Utility functions for synchronization operations"""
    
    @staticmethod
    def generate_sync_id() -> str:
        """Generate a unique sync operation ID"""
        timestamp = str(int(time.time() * 1000))
        random_part = hashlib.md5(os.urandom(16)).hexdigest()[:8]
        return f"sync_{timestamp}_{random_part}"
    
    @staticmethod
    def log_sync_operation(operation: str, details: Dict[str, Any]):
        """Log a synchronization operation"""
        try:
            log_entry = {
                'timestamp': datetime.utcnow().isoformat(),
                'operation': operation,
                'details': details,
                'sync_id': SyncUtils.generate_sync_id()
            }
            
            # Log to application logger if available
            if current_app:
                current_app.logger.info(f"Sync operation: {json.dumps(log_entry)}")
            else:
                print(f"Sync operation: {json.dumps(log_entry)}")
            
        except Exception as e:
            print(f"Error logging sync operation: {e}")
    
    @staticmethod
    def safe_database_operation(operation_func, max_retries: int = 3, retry_delay: float = 0.5):
        """
        Safely execute a database operation with retries
        Handles database locking and connection issues
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return operation_func()
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                
                # Check for database lock errors
                if any(keyword in error_msg for keyword in ['locked', 'busy', 'timeout']):
                    if attempt < max_retries - 1:
                        print(f"Database locked, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                
                # For other errors, don't retry
                break
        
        # If we get here, all retries failed
        raise last_error
    
    @staticmethod
    def check_sync_health() -> Dict[str, Any]:
        """Check the health of sync-related components"""
        health = {
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'unknown',
            'locks': 'unknown',
            'overall': 'unknown'
        }
        
        try:
            # Check database connectivity
            def db_check():
                db.session.execute(db.text('SELECT 1')).fetchone()
                return True
            
            if SyncUtils.safe_database_operation(db_check):
                health['database'] = 'healthy'
            else:
                health['database'] = 'error'
        except Exception as e:
            health['database'] = f'error: {str(e)}'
        
        try:
            # Check lock system
            lock_manager = SyncLockManager()
            test_lock = 'health_check'
            if lock_manager.acquire_lock(test_lock, timeout=1):
                lock_manager.release_lock(test_lock)
                health['locks'] = 'healthy'
            else:
                health['locks'] = 'timeout'
        except Exception as e:
            health['locks'] = f'error: {str(e)}'
        
        # Overall health
        if health['database'] == 'healthy' and health['locks'] == 'healthy':
            health['overall'] = 'healthy'
        else:
            health['overall'] = 'degraded'
        
        return health

# Global lock manager instance
sync_lock_manager = SyncLockManager()

def start_sync_maintenance():
    """Start background sync maintenance tasks"""
    def maintenance_worker():
        while True:
            try:
                # Clean up stale locks every 5 minutes
                sync_lock_manager.cleanup_stale_locks()
                time.sleep(300)  # 5 minutes
            except Exception as e:
                print(f"Error in sync maintenance worker: {e}")
                time.sleep(60)  # Retry in 1 minute
    
    # Start maintenance thread
    maintenance_thread = threading.Thread(target=maintenance_worker, daemon=True)
    maintenance_thread.start()
    print("Started sync maintenance worker")

def with_sync_lock(lock_name: str, timeout: int = 30):
    """Decorator to run function with sync lock"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            if sync_lock_manager.acquire_lock(lock_name, timeout):
                try:
                    return func(*args, **kwargs)
                finally:
                    sync_lock_manager.release_lock(lock_name)
            else:
                raise Exception(f"Could not acquire sync lock '{lock_name}' within {timeout}s")
        return wrapper
    return decorator
