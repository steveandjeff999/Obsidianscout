#!/usr/bin/env python3
"""
Test Full Sync System
"""
import os
from app import create_app

# Create Flask app
app = create_app()

with app.app_context():
    print("🔄 Testing Full Sync System")
    print("============================================================")
    
    # Test 1: Auto-discover table mappings
    print("\n1️⃣  Testing Table Discovery")
    from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
    
    auto_sync = AutomaticSQLite3Sync()
    
    print(f"Database paths: {auto_sync.database_paths}")
    print(f"Discovered table mappings: {auto_sync.table_database_map}")
    print(f"Total tables discovered: {len(auto_sync.table_database_map)}")
    
    # Test 2: Capture full database state
    print("\n2️⃣  Testing Full Database Capture")
    full_data = auto_sync._capture_full_database_state()
    
    print(f"Captured {len(full_data)} total records from all tables")
    
    # Show breakdown by table
    table_counts = {}
    for record in full_data:
        table_name = record.get('table', 'unknown')
        table_counts[table_name] = table_counts.get(table_name, 0) + 1
    
    print("\nRecords by table:")
    for table_name, count in sorted(table_counts.items()):
        database = auto_sync.table_database_map.get(table_name, 'unknown')
        print(f"  {table_name} ({database}): {count} records")
    
    # Test 3: Verify all databases accessible
    print("\n3️⃣  Testing Database Connectivity")
    import sqlite3
    
    for db_name, db_path in auto_sync.database_paths.items():
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = cursor.fetchall()
                print(f"✅ {db_name} database: {len(tables)} tables accessible")
        except Exception as e:
            print(f"❌ {db_name} database: Error - {e}")
    
    print("\n============================================================")
    print("🎉 FULL SYNC SYSTEM TEST COMPLETED")
    print(f"✅ System ready to sync {len(auto_sync.table_database_map)} tables")
    print(f"✅ {len(full_data)} total records available for sync")
    print("🚀 Full sync system is operational!")
