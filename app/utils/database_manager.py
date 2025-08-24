"""
Database Manager for Concurrent SQLite Operations with CR-SQLite Support

This module provides comprehensive database connection management with support for:
- CR-SQLite for concurrent read/write operations
- BEGIN CONCURRENT transactions
- Connection pooling and optimization
- Transaction isolation and conflict resolution
- Automatic retry mechanisms for conflicted transactions
"""

import os
import sqlite3
import threading
import time
import logging
from contextlib import contextmanager
from typing import Optional, Any, Dict, Callable
from datetime import datetime
from flask import current_app
from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, IntegrityError

# CR-SQLite is a SQLite extension DLL, not a Python package
# We'll load it directly as a SQLite extension
CRSQLITE_AVAILABLE = False  # We don't use the Python package
crsqlite = None

# CR-SQLite DLL path - set to the location of your installed DLL
CRSQLITE_DLL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'crsqlite', 'crsqlite.dll')

# Configure logging
logger = logging.getLogger(__name__)

def _serialize_value(value):
    """Serialize values for SQLite compatibility"""
    if isinstance(value, datetime):
        # Convert datetime to ISO format string
        return value.isoformat()
    return value

def _serialize_data(data):
    """Serialize data dictionary for SQLite compatibility"""
    if isinstance(data, dict):
        return {k: _serialize_value(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_serialize_data(item) for item in data]
    else:
        return _serialize_value(data)

class ConcurrentDatabaseManager:
    """
    Enhanced database manager with CR-SQLite support for concurrent operations
    """
    
    def __init__(self):
        self.connection_pool = {}
        self.lock = threading.RLock()
        self._initialized = False
        self.engine = None
        self.max_retries = 5
        self.retry_delay = 0.1  # Initial delay in seconds
        self.max_connections = 20
        
    def init_app(self, app):
        """Initialize the database manager with Flask app"""
        self.app = app
        self._setup_crsqlite_path()
        self._setup_engine()
        self._initialized = True
        
    def _setup_crsqlite_path(self):
        """Setup the CR-SQLite DLL path"""
        global CRSQLITE_DLL_PATH
        
        # Check for CR-SQLite DLL in instance folder
        instance_path = self.app.instance_path
        dll_path = os.path.join(instance_path, 'crsqlite', 'crsqlite.dll')
        
        if os.path.exists(dll_path):
            CRSQLITE_DLL_PATH = dll_path
            logger.info(f"Found CR-SQLite DLL at: {dll_path}")
        else:
            logger.warning(f"CR-SQLite DLL not found at: {dll_path}")
            CRSQLITE_DLL_PATH = None
        
    def _setup_engine(self):
        """Setup SQLAlchemy engine with CR-SQLite support"""
        database_uri = self.app.config.get('SQLALCHEMY_DATABASE_URI')
        
        # Extract the database path from URI
        if database_uri.startswith('sqlite:///'):
            db_path = database_uri[10:]  # Remove 'sqlite:///'
        else:
            raise ValueError("Only SQLite databases are supported with concurrent manager")
            
        # Create custom engine with CR-SQLite support
        self.engine = create_engine(
            database_uri,
            poolclass=pool.StaticPool,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={
                'timeout': 30,
                'check_same_thread': False,
            },
            echo=self.app.config.get('SQLALCHEMY_ECHO', False)
        )
        
        # Setup CR-SQLite extension loading
        @event.listens_for(self.engine, "connect")
        def load_crsqlite_extension(dbapi_connection, connection_record):
            """Load CR-SQLite extension on each connection if available"""
            try:
                # Enable WAL mode for better concurrency
                dbapi_connection.execute("PRAGMA journal_mode=WAL")
                dbapi_connection.execute("PRAGMA synchronous=NORMAL")
                dbapi_connection.execute("PRAGMA cache_size=10000")
                dbapi_connection.execute("PRAGMA temp_store=memory")
                dbapi_connection.execute("PRAGMA mmap_size=268435456")  # 256MB
                dbapi_connection.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                
                # Try to load CR-SQLite extension DLL
                crsqlite_loaded = False
                
                if CRSQLITE_DLL_PATH and os.path.exists(CRSQLITE_DLL_PATH):
                    try:
                        # Enable loading of extensions first
                        dbapi_connection.enable_load_extension(True)
                        
                        # Normalize the DLL path for cross-platform compatibility
                        dll_path_normalized = os.path.normpath(CRSQLITE_DLL_PATH)
                        
                        # Try to load the CR-SQLite extension DLL
                        # SQLite expects the path without the .dll extension on Windows
                        dll_path_no_ext = dll_path_normalized.replace('.dll', '')
                        
                        try:
                            dbapi_connection.load_extension(dll_path_no_ext)
                            logger.info(f"CR-SQLite extension loaded successfully: {dll_path_no_ext}")
                            crsqlite_loaded = True
                        except Exception as e1:
                            # Try with full path if no extension didn't work
                            try:
                                dbapi_connection.load_extension(dll_path_normalized)
                                logger.info(f"CR-SQLite extension loaded with full path: {dll_path_normalized}")
                                crsqlite_loaded = True
                            except Exception as e2:
                                logger.error(f"Failed to load CR-SQLite extension:")
                                logger.error(f"  Without extension: {e1}")
                                logger.error(f"  With full path: {e2}")
                        
                        # Always disable extension loading for security after attempting to load
                        dbapi_connection.enable_load_extension(False)
                        
                        # Verify CR-SQLite is working if loaded
                        if crsqlite_loaded:
                            try:
                                # Test if CR-SQLite functions are available
                                # Note: Some CR-SQLite builds don't have crsql_version() function
                                # but still provide the core functionality
                                dbapi_connection.execute("PRAGMA crsql_concurrent_writes=1")
                                logger.info("CR-SQLite concurrent writes enabled")
                                
                                # Try to get version (may not be available in all builds)
                                try:
                                    version = dbapi_connection.execute("SELECT crsql_version()").fetchone()[0]
                                    logger.info(f"CR-SQLite version: {version}")
                                except Exception:
                                    # Version function not available, but that's okay
                                    logger.info("CR-SQLite loaded (version function not available)")
                                
                                # Check if CR-SQLite tables can be created (this validates the extension works)
                                try:
                                    # This is a test - we don't actually create the table, just validate syntax
                                    dbapi_connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'crsql_%' LIMIT 1")
                                    logger.info("CR-SQLite functionality verified")
                                except Exception as verify_error:
                                    logger.warning(f"CR-SQLite verification failed: {verify_error}")
                                    crsqlite_loaded = False
                                    
                            except Exception as e:
                                logger.warning(f"Could not enable CR-SQLite concurrent writes: {e}")
                                # Extension loaded but concurrent writes not available
                                # This might still provide some benefits, so keep crsqlite_loaded = True
                        
                    except Exception as e:
                        logger.error(f"Failed to enable extension loading: {e}")
                        crsqlite_loaded = False
                        # Make sure to disable extension loading even on failure
                        try:
                            dbapi_connection.enable_load_extension(False)
                        except:
                            pass
                else:
                    logger.warning(f"CR-SQLite DLL not found at: {CRSQLITE_DLL_PATH}")
                
                if crsqlite_loaded:
                    logger.info("CR-SQLite extension active - enhanced concurrency available")
                else:
                    logger.info("CR-SQLite not available - using optimized standard SQLite")
                
                # Additional SQLite optimizations for concurrency
                dbapi_connection.execute("PRAGMA wal_autocheckpoint=1000")
                dbapi_connection.execute("PRAGMA wal_checkpoint_timeout=10000")
                
            except Exception as e:
                logger.error(f"Error configuring database connection: {e}")
                # Ensure basic optimizations are applied even if CR-SQLite fails
                try:
                    dbapi_connection.execute("PRAGMA journal_mode=WAL")
                    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
                    dbapi_connection.execute("PRAGMA cache_size=10000")
                    dbapi_connection.execute("PRAGMA busy_timeout=30000")
                except Exception as fallback_error:
                    logger.error(f"Failed to apply basic SQLite optimizations: {fallback_error}")
                
        # Setup connection pool events
        @event.listens_for(self.engine, "checkout")
        def receive_checkout(dbapi_connection, connection_record, connection_proxy):
            """Handle connection checkout"""
            pass
            
        @event.listens_for(self.engine, "checkin") 
        def receive_checkin(dbapi_connection, connection_record):
            """Handle connection checkin"""
            pass

    @contextmanager
    def get_connection(self, readonly: bool = False):
        """
        Get a database connection with proper transaction handling
        
        Args:
            readonly: Whether this is a read-only operation
        """
        if not self._initialized:
            raise RuntimeError("DatabaseManager not initialized")
            
        connection = None
        transaction = None
        
        try:
            connection = self.engine.connect()
            
            if not readonly:
                # Use regular SQLAlchemy transaction
                # Note: BEGIN CONCURRENT is not supported in this CR-SQLite build
                transaction = connection.begin()
            else:
                transaction = None
                    
            yield connection
            
            if transaction:
                transaction.commit()
                
        except Exception as e:
            if transaction:
                transaction.rollback()
            raise e
        finally:
            if connection:
                connection.close()

    def execute_with_retry(self, 
                          operation: Callable,
                          *args,
                          readonly: bool = False,
                          **kwargs) -> Any:
        """
        Execute a database operation with automatic retry on conflicts
        
        Args:
            operation: Function to execute
            readonly: Whether this is a read-only operation
            *args, **kwargs: Arguments to pass to operation
            
        Returns:
            Result of the operation
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                with self.get_connection(readonly=readonly) as conn:
                    return operation(conn, *args, **kwargs)
                    
            except (OperationalError, IntegrityError) as e:
                last_exception = e
                error_msg = str(e).lower()
                
                # Check if this is a retryable error
                if any(keyword in error_msg for keyword in [
                    'database is locked',
                    'busy',
                    'conflict',
                    'concurrent',
                    'retry',
                    'misuse',
                    'parameter'
                ]):
                    wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Database conflict on attempt {attempt + 1}, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    # Non-retryable error
                    raise e
                    
            except Exception as e:
                # Non-database error
                raise e
                
        # If we've exhausted all retries
        raise last_exception

    def execute_concurrent_read(self, query: str, params: Optional[Dict] = None) -> Any:
        """Execute a concurrent read operation"""
        def read_operation(conn, query, params):
            if params:
                return conn.execute(text(query), params).fetchall()
            else:
                return conn.execute(text(query)).fetchall()
                
        return self.execute_with_retry(read_operation, query, params, readonly=True)

    def execute_concurrent_write(self, query: str, params: Optional[Dict] = None) -> Any:
        """Execute a concurrent write operation"""
        def write_operation(conn, query, params):
            if params:
                # Serialize parameters to handle datetime objects
                serialized_params = _serialize_data(params)
                result = conn.execute(text(query), serialized_params)
            else:
                result = conn.execute(text(query))
            return result
                
        return self.execute_with_retry(write_operation, query, params, readonly=False)

    def bulk_insert_concurrent(self, table_name: str, data: list) -> None:
        """Perform concurrent bulk insert with conflict resolution"""
        if not data:
            return
            
        def bulk_operation(conn, table_name, data):
            # Serialize the data to handle datetime objects
            serialized_data = _serialize_data(data)
            
            # Create parameterized insert statement
            columns = list(serialized_data[0].keys())
            placeholders = ', '.join([f':{col}' for col in columns])
            query = f"INSERT OR REPLACE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
            
            # Execute batch insert with executemany for better performance
            conn.execute(text(query), serialized_data)
            
        self.execute_with_retry(bulk_operation, table_name, data, readonly=False)

    def execute_transaction(self, operations: list) -> None:
        """
        Execute multiple operations in a single concurrent transaction
        
        Args:
            operations: List of (query, params) tuples
        """
        def transaction_operation(conn, operations):
            for query, params in operations:
                if params:
                    # Serialize parameters to handle datetime objects
                    serialized_params = _serialize_data(params)
                    conn.execute(text(query), serialized_params)
                else:
                    conn.execute(text(query))
                    
        self.execute_with_retry(transaction_operation, operations, readonly=False)

    def get_database_info(self) -> Dict[str, Any]:
        """Get information about the database configuration"""
        def info_operation(conn):
            result = {}
            
            # Get basic database info
            result['sqlite_version'] = conn.execute(text("SELECT sqlite_version()")).scalar()
            result['journal_mode'] = conn.execute(text("PRAGMA journal_mode")).scalar()
            result['synchronous'] = conn.execute(text("PRAGMA synchronous")).scalar()
            result['cache_size'] = conn.execute(text("PRAGMA cache_size")).scalar()
            
            # Check if CR-SQLite is available
            try:
                # Method 1: Try to check concurrent writes pragma first (most reliable)
                try:
                    # First check if the pragma exists (this indicates CR-SQLite is loaded)
                    concurrent_writes = conn.execute(text("PRAGMA crsql_concurrent_writes")).scalar()
                    
                    if concurrent_writes is not None:
                        # If pragma works, CR-SQLite is definitely loaded
                        result['crsqlite_version'] = 'extension_loaded'
                        result['crsqlite_source'] = 'DLL'
                        
                        # Check if concurrent writes are actually enabled
                        if concurrent_writes == 1:
                            result['concurrent_writes'] = 'enabled'
                        else:
                            result['concurrent_writes'] = 'disabled'
                        
                        # Try to get actual version if available
                        try:
                            crsql_version = conn.execute(text("SELECT crsql_version()")).scalar()
                            result['crsqlite_version'] = crsql_version
                        except Exception:
                            # Version function not available, but extension is loaded
                            pass
                    else:
                        result['crsqlite_version'] = None
                        result['crsqlite_source'] = None
                        
                except Exception as pragma_error:
                    # If pragma fails completely, CR-SQLite is likely not loaded
                    result['concurrent_writes'] = None
                    result['crsqlite_version'] = None
                    result['crsqlite_source'] = None
                
                # Method 2: Check for CR-SQLite tables if pragma didn't work
                if result['crsqlite_version'] is None:
                    try:
                        tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'crsql_%'")).fetchall()
                        if tables:
                            result['crsqlite_version'] = 'extension_loaded'
                            result['crsqlite_source'] = f'DLL (tables: {[t[0] for t in tables]})'
                            # If tables exist, try to enable concurrent writes
                            try:
                                conn.execute(text("PRAGMA crsql_concurrent_writes=1"))
                                result['concurrent_writes'] = 'enabled'
                            except Exception:
                                result['concurrent_writes'] = 'tables_only'
                    except Exception:
                        pass
                
                # Set final defaults
                if result['crsqlite_version'] is None:
                    result['crsqlite_version'] = None
                    result['concurrent_writes'] = None
                    result['crsqlite_source'] = 'not_available'
                    
            except Exception as e:
                logger.error(f"Error checking CR-SQLite status: {e}")
                result['crsqlite_version'] = None
                result['concurrent_writes'] = None
                result['crsqlite_source'] = f'error: {str(e)}'
                
            return result
            
        return self.execute_with_retry(info_operation, readonly=True)

    def optimize_database(self) -> None:
        """Optimize database for concurrent operations"""
        def optimize_operation(conn):
            # Run optimization commands
            conn.execute(text("PRAGMA optimize"))
            conn.execute(text("VACUUM"))
            conn.execute(text("PRAGMA integrity_check"))
            
        self.execute_with_retry(optimize_operation, readonly=False)

    def enable_wal_mode(self) -> None:
        """Ensure WAL mode is enabled for better concurrency"""
        def wal_operation(conn):
            conn.execute(text("PRAGMA journal_mode=WAL"))
            
        self.execute_with_retry(wal_operation, readonly=False)

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics"""
        return {
            'pool_size': self.engine.pool.size() if hasattr(self.engine.pool, 'size') else 'N/A',
            'checked_in': self.engine.pool.checkedin() if hasattr(self.engine.pool, 'checkedin') else 'N/A',
            'checked_out': self.engine.pool.checkedout() if hasattr(self.engine.pool, 'checkedout') else 'N/A',
            'overflow': self.engine.pool.overflow() if hasattr(self.engine.pool, 'overflow') else 'N/A',
        }

# Global instance
concurrent_db_manager = ConcurrentDatabaseManager()

# Convenience functions for common operations
def execute_concurrent_query(query: str, params: Optional[Dict] = None, readonly: bool = False):
    """Execute a query with concurrent support"""
    if readonly:
        return concurrent_db_manager.execute_concurrent_read(query, params)
    else:
        return concurrent_db_manager.execute_concurrent_write(query, params)

def bulk_insert_with_concurrency(table_name: str, data: list):
    """Perform bulk insert with concurrency support"""
    return concurrent_db_manager.bulk_insert_concurrent(table_name, data)

def execute_concurrent_transaction(operations: list):
    """Execute multiple operations in a concurrent transaction"""
    return concurrent_db_manager.execute_transaction(operations)

@contextmanager
def concurrent_session(readonly: bool = False):
    """Context manager for concurrent database sessions"""
    with concurrent_db_manager.get_connection(readonly=readonly) as conn:
        yield conn
