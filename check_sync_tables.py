#!/usr/bin/env python3
"""Check what tables are discovered by auto-sync system"""

from app import create_app, db
from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
import sqlite3

app = create_app()
with app.app_context():
    sync = AutomaticSQLite3Sync()
    print('Table mappings discovered:')
    for table, database in sorted(sync.table_database_map.items()):
        print(f'  {table} -> {database}')
    
    print('\nChecking user_roles table specifically:')
    if 'user_roles' in sync.table_database_map:
        print(f'  user_roles found in: {sync.table_database_map["user_roles"]}')
    else:
        print('  ❌ user_roles NOT found in discovered tables')
        
    print('\nChecking if user_roles exists in databases:')
    for db_name, db_path in sync.database_paths.items():
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_roles'")
                result = cursor.fetchone()
                if result:
                    cursor.execute('SELECT COUNT(*) FROM user_roles')
                    count = cursor.fetchone()[0]
                    print(f'  {db_name}: user_roles exists with {count} entries')
                else:
                    print(f'  {db_name}: user_roles table NOT FOUND')
        except Exception as e:
            print(f'  {db_name}: Error - {e}')
            
    print('\nChecking scouting.db tables:')
    for db_name, db_path in sync.database_paths.items():
        if db_name == 'scouting':
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    tables = [row[0] for row in cursor.fetchall()]
                    print(f'  Scouting DB has {len(tables)} tables: {tables}')
            except Exception as e:
                print(f'  Error reading scouting.db: {e}')
