"""
Setup Script for Concurrent SQLite Operations with CR-SQLite DLL

This script tests the CR-SQLite DLL extension functionality.
CR-SQLite is loaded as a SQLite extension DLL, not a Python package.
"""

import subprocess
import sys
import os
import sqlite3
from pathlib import Path

def check_crsqlite_dll():
    """Check if CR-SQLite DLL exists"""
    print("Checking for CR-SQLite DLL...")
    dll_path = os.path.join('instance', 'crsqlite', 'crsqlite.dll')
    
    if os.path.exists(dll_path):
        print(f"✓ CR-SQLite DLL found at: {dll_path}")
        return True
    else:
        print(f"✗ CR-SQLite DLL not found at: {dll_path}")
        print("Please ensure the CR-SQLite DLL is placed in the instance/crsqlite/ directory")
        return False

def test_database_setup():
    """Test database setup with CR-SQLite DLL"""
    print("Testing database setup with CR-SQLite DLL...")
    try:
        # Create a test database
        test_db_path = "test_concurrent.db"
        conn = sqlite3.connect(test_db_path)
        
        # Enable extension loading
        conn.enable_load_extension(True)
        
        # Load CR-SQLite extension DLL
        dll_path = os.path.join('instance', 'crsqlite', 'crsqlite')  # Without .dll extension
        dll_path_normalized = os.path.normpath(dll_path)
        
        try:
            conn.load_extension(dll_path_normalized)
            print("✓ CR-SQLite DLL loaded successfully")
        except Exception as e:
            print(f"✗ Failed to load CR-SQLite DLL: {e}")
            conn.close()
            return False
        finally:
            # Disable extension loading for security
            conn.enable_load_extension(False)
        
        # Test basic CR-SQLite functionality
        cursor = conn.cursor()
        
        # Enable WAL mode
        cursor.execute("PRAGMA journal_mode=WAL")
        
        # Check if concurrent writes can be enabled
        try:
            cursor.execute("PRAGMA crsql_concurrent_writes=1")
            print("✓ CR-SQLite concurrent writes enabled")
        except Exception as e:
            print(f"⚠ Could not enable concurrent writes: {e}")
        
        # Create a test table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                value INTEGER
            )
        """)
        
        # Test BEGIN CONCURRENT
        try:
            cursor.execute("BEGIN CONCURRENT")
            cursor.execute("INSERT INTO test_table (name, value) VALUES (?, ?)", ("test", 123))
            cursor.execute("COMMIT")
            print("✓ BEGIN CONCURRENT works")
        except Exception as e:
            print(f"⚠ BEGIN CONCURRENT not available: {e}")
        
        # Try to get CR-SQLite version (may not be available in all builds)
        try:
            version = cursor.execute("SELECT crsql_version()").fetchone()[0]
            print(f"✓ CR-SQLite version: {version}")
        except Exception as e:
            print(f"⚠ Version function not available: {e}")
            print("✓ CR-SQLite extension loaded (version function not supported)")
        
        conn.close()
        
        # Clean up test database
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        print("✓ Database setup test successful")
        return True
        
    except Exception as e:
        print(f"✗ Database setup test failed: {e}")
        return False

def test_flask_integration():
    """Test Flask app integration"""
    print("Testing Flask integration...")
    try:
        # Set up Flask app context
        sys.path.insert(0, os.getcwd())
        
        from app import create_app, db
        from app.utils.database_manager import concurrent_db_manager
        
        app = create_app()
        
        with app.app_context():
            # Test database manager initialization
            db_info = concurrent_db_manager.get_database_info()
            
            print(f"✓ SQLite version: {db_info.get('sqlite_version', 'Unknown')}")
            print(f"✓ Journal mode: {db_info.get('journal_mode', 'Unknown')}")
            
            if db_info.get('crsqlite_version'):
                print(f"✓ CR-SQLite version: {db_info['crsqlite_version']}")
                print(f"✓ Concurrent writes: {db_info.get('concurrent_writes', 'Unknown')}")
            else:
                print("⚠ CR-SQLite not detected in Flask context")
            
            # Test connection pool
            pool_stats = concurrent_db_manager.get_connection_stats()
            print(f"✓ Connection pool configured: {pool_stats}")
        
        print("✓ Flask integration test successful")
        return True
        
    except Exception as e:
        print(f"✗ Flask integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_migration_script():
    """Create a migration script for existing databases"""
    migration_script = '''
"""
Database Migration for Concurrent Operations

This script migrates an existing SQLite database to support concurrent operations.
"""

import sqlite3
import os
from pathlib import Path

def migrate_database(db_path):
    """Migrate database to support concurrent operations"""
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return False
    
    # Backup the original database
    backup_path = f"{db_path}.backup"
    import shutil
    shutil.copy2(db_path, backup_path)
    print(f"Database backed up to: {backup_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Enable WAL mode for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        result = cursor.fetchone()
        print(f"Journal mode set to: {result[0]}")
        
        # Set synchronous mode to NORMAL for better performance
        cursor.execute("PRAGMA synchronous=NORMAL")
        
        # Increase cache size
        cursor.execute("PRAGMA cache_size=10000")
        
        # Enable memory temp store
        cursor.execute("PRAGMA temp_store=memory")
        
        # Set mmap size for better performance
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB
        
        # Try to load CR-SQLite DLL if available
        try:
            # Enable extension loading
            conn.enable_load_extension(True)
            
            # Try to load CR-SQLite DLL
            dll_path = os.path.join('instance', 'crsqlite', 'crsqlite')  # Without .dll extension
            dll_path_normalized = os.path.normpath(dll_path)
            
            try:
                conn.load_extension(dll_path_normalized)
                cursor.execute("PRAGMA crsql_concurrent_writes=1")
                print("✓ CR-SQLite DLL loaded and concurrent writes enabled")
            except Exception as load_error:
                print(f"⚠ CR-SQLite DLL not available: {load_error}")
            finally:
                # Disable extension loading for security
                conn.enable_load_extension(False)
                
        except Exception as e:
            print(f"⚠ Could not load CR-SQLite extension: {e}")
        
        # Optimize the database
        cursor.execute("PRAGMA optimize")
        
        conn.close()
        print("✓ Database migration completed successfully")
        return True
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        # Restore backup if migration failed
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, db_path)
            print("Database restored from backup")
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
        migrate_database(db_path)
    else:
        # Default database path
        db_path = "instance/scouting.db"
        if os.path.exists(db_path):
            migrate_database(db_path)
        else:
            print(f"Database not found at {db_path}")
            print("Usage: python migrate_database.py <database_path>")
'''
    
    with open('migrate_database.py', 'w') as f:
        f.write(migration_script)
    
    print("✓ Migration script created: migrate_database.py")

def main():
    """Main setup function"""
    print("=" * 60)
    print("Setting up Concurrent SQLite Operations with CR-SQLite DLL")
    print("=" * 60)
    
    success = True
    
    # Step 1: Check for CR-SQLite DLL
    if not check_crsqlite_dll():
        success = False
    
    # Step 2: Test database functionality
    if not test_database_setup():
        success = False
    
    # Step 3: Test Flask integration
    if not test_flask_integration():
        success = False
    
    # Step 4: Create migration script
    create_migration_script()
    
    print("\n" + "=" * 60)
    if success:
        print("✓ Setup completed successfully!")
        print("\nNext steps:")
        print("1. Restart your Flask application")
        print("2. Visit /admin/database to check the status")
        print("3. Run migrate_database.py on existing databases if needed")
        print("4. Check concurrent_examples.py for usage examples")
    else:
        print("✗ Setup completed with errors")
        print("\nTroubleshooting:")
        print("1. Ensure CR-SQLite DLL is in instance/crsqlite/crsqlite.dll")
        print("2. Download CR-SQLite DLL from: https://github.com/vlcn-io/cr-sqlite")
        print("3. Verify SQLite version compatibility")
        print("4. Check file permissions on the DLL")
    print("=" * 60)

if __name__ == "__main__":
    main()
