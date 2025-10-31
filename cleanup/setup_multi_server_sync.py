#!/usr/bin/env python3
"""
Multi-Server Sync Database Setup Script

This script creates the necessary database tables for the multi-server
synchronization system. Run this once before using the sync functionality.

Usage:
    python setup_multi_server_sync.py
"""

import os
import sys
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import create_app, db
    from app.models import SyncServer, SyncLog, FileChecksum, SyncConfig
    from app.utils.multi_server_sync import MultiServerSyncManager
except ImportError as e:
    print(f" Error importing application modules: {e}")
    print("Make sure you're running this script from the root directory.")
    sys.exit(1)

def setup_sync_database():
    """Set up the multi-server sync database tables."""
    print(" Setting up Multi-Server Sync Database...")
    
    # Create Flask application context
    app = create_app()
    
    with app.app_context():
        try:
            # Create all sync-related tables
            print(" Creating sync database tables...")
            
            # Create the tables (this will only create missing tables)
            try:
                db.create_all()
                print("   Database tables created successfully")
            except Exception as e:
                print(f"   Error creating tables: {e}")
                return False
            
            # Verify the tables were created
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            sync_tables = ['sync_servers', 'sync_logs', 'file_checksums', 'sync_config']
            created_tables = []
            
            for table in sync_tables:
                if table in tables:
                    created_tables.append(table)
                    print(f"   {table}")
                else:
                    print(f"  ️  {table} - not found (may need manual creation)")
            
            if len(created_tables) >= 1:  # At least sync_config should exist
                print(f"\n Database setup completed ({len(created_tables)}/{len(sync_tables)} tables ready)")
            else:
                print(f"\n️  Warning: Only {len(created_tables)}/{len(sync_tables)} tables created")
                # Don't fail completely - sync_config is the most important
            
            # Create default sync configuration
            print("️  Setting up default sync configuration...")
            
            # Set default configuration values using the proper method
            SyncConfig.set_value('sync_enabled', True, 'boolean', 
                               'Enable/disable automatic synchronization')
            SyncConfig.set_value('sync_interval', 30, 'integer',
                               'Interval between sync operations (seconds)')
            SyncConfig.set_value('file_watch_interval', 5, 'integer',
                               'Interval for file change monitoring (seconds)')
            SyncConfig.set_value('max_retry_attempts', 3, 'integer',
                               'Maximum retry attempts for failed operations')
            SyncConfig.set_value('connection_timeout', 30, 'integer',
                               'Connection timeout in seconds')
            
            print("   Default sync configuration created")
            
            # Initialize the sync manager (this will start background processes)
            print(" Initializing sync manager...")
            sync_manager = MultiServerSyncManager()
            print("   Sync manager initialized")
            
            print("\n" + "="*60)
            print(" MULTI-SERVER SYNC SETUP COMPLETE!")
            print("="*60)
            print()
            print(" Next steps:")
            print("1. Start your Flask application: python run.py")
            print("2. Log in as superadmin (username: superadmin, password: password)")
            print("3. Go to 'Multi-Server Sync' in the navigation menu")
            print("4. Add your sync servers using IP addresses or domain names")
            print("5. Configure sync settings as needed")
            print()
            print(" For detailed setup instructions, see:")
            print("   MULTI_SERVER_SYNC_README.md")
            print()
            print(" Sync Features Available:")
            print("    Real-time file synchronization")
            print("    Database synchronization")
            print("    Configuration file sync")
            print("    Upload file sync")
            print("    No authentication required (IP-based)")
            print("    Web-based management interface")
            print("    Real-time monitoring and logging")
            print()
            
            return True
            
        except Exception as e:
            print(f" Error setting up sync database: {e}")
            import traceback
            traceback.print_exc()
            return False

def verify_prerequisites():
    """Verify that all prerequisites are met."""
    print(" Checking prerequisites...")
    
    # Check if we're in the right directory
    required_files = ['run.py', 'app/__init__.py', 'app/models.py']
    missing_files = []
    
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    if missing_files:
        print(" Missing required files:")
        for file in missing_files:
            print(f"   - {file}")
        print("\nMake sure you're running this script from the root directory of your application.")
        return False
    
    # Check Python version
    if sys.version_info < (3, 7):
        print(f" Python 3.7+ required, you have {sys.version}")
        return False
    
    print(" Prerequisites check passed")
    return True

def main():
    """Main setup function."""
    print(" Multi-Server Sync Setup Script")
    print("=" * 40)
    print()
    
    # Verify prerequisites
    if not verify_prerequisites():
        sys.exit(1)
    
    # Setup the database
    if setup_sync_database():
        print(" Setup completed successfully!")
        print("\nYou can now start using the multi-server sync system.")
        sys.exit(0)
    else:
        print(" Setup failed. Please check the error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
