#!/usr/bin/env python3
"""
Debug User Column Detection
"""
import sqlite3
import os
from app import create_app

# Create Flask app
app = create_app()

with app.app_context():
    # Check both database paths
    scouting_db_path = os.path.join(app.instance_path, 'scouting.db')
    users_db_path = os.path.join(app.instance_path, 'users.db')
    
    print(f"Scouting database path: {scouting_db_path}")
    print(f"Users database path: {users_db_path}")
    
    for db_name, db_path in [('scouting', scouting_db_path), ('users', users_db_path)]:
        if os.path.exists(db_path):
            print(f"\n=== {db_name.upper()} DATABASE ===")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # List all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            print(f"Tables: {[t[0] for t in tables]}")
            
            # Check if user table exists
            user_table_exists = any(t[0] == 'user' for t in tables)
            print(f"User table exists: {user_table_exists}")
            
            if user_table_exists:
                cursor.execute("PRAGMA table_info(user)")
                columns = cursor.fetchall()
                
                print("User table columns:")
                for col in columns:
                    print(f"  {col[1]} ({col[2]}) - nullable: {not col[3]}")
                
                # Check if user table has any data
                cursor.execute("SELECT COUNT(*) FROM user")
                count = cursor.fetchone()[0]
                print(f"User table has {count} records")
                
            conn.close()
        else:
            print(f"{db_name} database file does not exist")
        
    # Also check the automatic sync system's database access
    from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
    
    auto_sync = AutomaticSQLite3Sync()
    
    # Check which database paths the sync system is using
    print(f"\n=== SYNC SYSTEM DATABASE ACCESS ===")
    print(f"Database paths: {auto_sync.database_paths}")
    print(f"Table mapping: {auto_sync.table_database_map}")
    
    # Test getting database path for user table
    user_db_path = auto_sync._get_database_path_for_table('user')
    print(f"User table database path: {user_db_path}")
    
    # Test applying a change
    test_change = {
        'table': 'user',
        'record_id': '999',
        'operation': 'upsert',
        'data': {
            'id': 999,
            'username': 'debug_test_user',
            'email': 'debug@test.com',
            'scouting_team_number': 1234
        },
        'timestamp': '2025-01-01T00:00:00',
        'change_hash': 'debug_hash'
    }
    
    print(f"\nTesting change application: {test_change['data']}")
    result = auto_sync.apply_changes_zero_loss([test_change])
    print(f"Result: {result}")
    
    # Check if the change was applied
    with sqlite3.connect(users_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM user WHERE id = 999")
        user_check = cursor.fetchone()
        print(f"User 999 in database: {user_check}")
