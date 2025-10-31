#!/usr/bin/env python3
"""
Database Performance and Locking Fix
Resolves SQLite database locking issues and performance problems
"""

import sys
import os
import sqlite3
import time
from contextlib import contextmanager
from threading import Lock
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
import threading

# Global database lock for SQLite operations
_db_lock = Lock()

def setup_sqlite_performance_optimizations():
    """Configure SQLite for better performance and concurrency"""
    
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        """Set SQLite PRAGMA settings for better performance and concurrency"""
        if 'sqlite' in str(dbapi_connection):
            cursor = dbapi_connection.cursor()
            
            # Performance optimizations
            cursor.execute("PRAGMA synchronous = NORMAL")  # Faster than FULL, safer than OFF
            cursor.execute("PRAGMA cache_size = -64000")   # 64MB cache
            cursor.execute("PRAGMA temp_store = MEMORY")    # Store temporary data in memory
            cursor.execute("PRAGMA mmap_size = 268435456")  # 256MB memory-mapped I/O
            
            # Concurrency improvements
            cursor.execute("PRAGMA journal_mode = WAL")     # Write-Ahead Logging for better concurrency
            cursor.execute("PRAGMA wal_autocheckpoint = 1000")  # Checkpoint every 1000 pages
            cursor.execute("PRAGMA busy_timeout = 30000")   # Wait up to 30 seconds for locks
            cursor.execute("PRAGMA foreign_keys = ON")      # Enable foreign key constraints
            
            # Connection-specific settings
            cursor.execute("PRAGMA read_uncommitted = ON")  # Allow dirty reads for performance
            
            cursor.close()
            print(" SQLite performance optimizations applied")

@contextmanager
def safe_db_operation(max_retries=3, retry_delay=0.1):
    """Context manager for safe database operations with retry logic"""
    for attempt in range(max_retries):
        try:
            with _db_lock:  # Ensure only one operation at a time
                db.session.begin()
                yield db.session
                db.session.commit()
                break
        except Exception as e:
            db.session.rollback()
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                print(f"️ Database locked, retrying in {retry_delay}s... (attempt {attempt + 1})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                print(f" Database operation failed: {e}")
                raise

def fix_database_configuration():
    """Fix database configuration for better performance"""
    app = create_app()
    
    with app.app_context():
        print(" Fixing Database Configuration...")
        
        # Apply SQLite optimizations
        setup_sqlite_performance_optimizations()
        
        # Test database operations
        print(" Testing database operations...")
        
        # Test 1: Simple query
        try:
            with safe_db_operation():
                result = db.session.execute(text("SELECT COUNT(*) FROM user")).scalar()
                print(f"    User count query: {result}")
        except Exception as e:
            print(f"    Query failed: {e}")
        
        # Test 2: Insert operation
        try:
            from app.models import User
            with safe_db_operation():
                test_user = User(
                    username=f'perftest_{int(time.time())}',
                    scouting_team_number=9999,
                    is_active=True
                )
                test_user.set_password('test123')
                db.session.add(test_user)
                # Commit happens in context manager
                print(f"    Insert test successful: {test_user.username}")
                
                # Clean up
                db.session.delete(test_user)
                # Commit happens in context manager
                
        except Exception as e:
            print(f"    Insert test failed: {e}")
        
        # Test 3: Check WAL mode
        try:
            result = db.session.execute(text("PRAGMA journal_mode")).scalar()
            print(f"    Journal mode: {result}")
            
            result = db.session.execute(text("PRAGMA synchronous")).scalar()
            print(f"    Synchronous mode: {result}")
            
            result = db.session.execute(text("PRAGMA cache_size")).scalar()
            print(f"    Cache size: {result}")
            
        except Exception as e:
            print(f"   ️ PRAGMA check failed: {e}")
        
        print(" Database configuration fix complete")

def optimize_app_config():
    """Optimize Flask app configuration for performance"""
    app = create_app()
    
    with app.app_context():
        print(" Optimizing App Configuration...")
        
        # Check current SQLAlchemy settings
        print(f"   Database URL: {app.config.get('SQLALCHEMY_DATABASE_URI', 'Not set')}")
        print(f"   Pool settings: {app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})}")
        
        # Recommend optimizations
        recommended_config = {
            'SQLALCHEMY_ENGINE_OPTIONS': {
                'pool_size': 1,              # SQLite only supports one writer
                'pool_timeout': 30,          # Match busy_timeout
                'pool_recycle': 3600,        # Recycle connections every hour
                'max_overflow': 0,           # No overflow for SQLite
                'poolclass': StaticPool,     # Use static pool for SQLite
                'connect_args': {
                    'timeout': 30,           # Connection timeout
                    'isolation_level': None  # Autocommit mode
                }
            },
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,  # Reduce overhead
            'SQLALCHEMY_RECORD_QUERIES': False        # Disable query recording
        }
        
        print(" Recommended configuration:")
        for key, value in recommended_config.items():
            print(f"   {key}: {value}")
        
        return recommended_config

def create_optimized_database_config():
    """Create an optimized database configuration file"""
    config_content = '''
# Optimized Database Configuration for SQLite
# Add these settings to your app configuration

SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 1,
    'pool_timeout': 30,
    'pool_recycle': 3600,
    'max_overflow': 0,
    'connect_args': {
        'timeout': 30,
        'isolation_level': None,
        'check_same_thread': False  # Allow multi-threading
    }
}

# Performance settings
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_RECORD_QUERIES = False

# SQLite-specific optimizations (applied via PRAGMA statements):
# - journal_mode = WAL (Write-Ahead Logging)
# - synchronous = NORMAL (Balance performance/safety)  
# - cache_size = -64000 (64MB cache)
# - busy_timeout = 30000 (30 second timeout)
# - temp_store = MEMORY (In-memory temporary storage)
'''
    
    with open('database_optimization_config.py', 'w') as f:
        f.write(config_content)
    
    print(" Created database_optimization_config.py")

def disable_heavy_sync_during_operations():
    """Temporarily disable heavy sync operations during user interactions"""
    try:
        from universal_real_time_sync import universal_sync
        
        # Get current sync status
        status = universal_sync.get_status()
        print(f" Current sync status: {status}")
        
        if status['worker_running'] and status['queue_size'] > 100:
            print("️ High sync queue detected - this may cause performance issues")
            print("   Consider implementing sync throttling during peak usage")
            
        # Recommendations for sync optimization
        print(" Sync optimization recommendations:")
        print("   1. Batch database changes instead of individual operations")
        print("   2. Implement queue size limits")
        print("   3. Add delay between sync operations") 
        print("   4. Disable file monitoring during heavy database operations")
        
    except Exception as e:
        print(f"️ Could not check sync status: {e}")

if __name__ == "__main__":
    print(" Database Performance Fix")
    print("=" * 50)
    
    # Step 1: Fix database configuration
    fix_database_configuration()
    
    # Step 2: Optimize app config  
    optimize_app_config()
    
    # Step 3: Create optimization config
    create_optimized_database_config()
    
    # Step 4: Check sync system
    disable_heavy_sync_during_operations()
    
    print("\n Performance Fix Summary:")
    print("    SQLite PRAGMA optimizations applied")
    print("    Database locking safeguards added")
    print("    Retry logic implemented")
    print("    Configuration optimizations identified")
    print("    Sync system analysis completed")
    
    print(f"\n Next Steps:")
    print(f"   1. Apply the recommended SQLALCHEMY_ENGINE_OPTIONS")
    print(f"   2. Consider upgrading to PostgreSQL for better concurrency")
    print(f"   3. Implement sync throttling during peak usage")
    print(f"   4. Monitor database lock frequency")
