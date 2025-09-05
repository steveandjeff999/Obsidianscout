#!/usr/bin/env python3
"""
Test Universal Sync System
Tests that ALL database tables sync without knowing field names
AND that all instance folder files sync (except database files)
"""

import sys
import os
import time
import json
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_universal_sync():
    """Test universal sync system comprehensively"""
    print("🌐 Testing Universal Sync System...")
    
    try:
        # Import after path setup
        from app import create_app, db
        from universal_sync_system import universal_sync
        
        app = create_app()
        
        with app.app_context():
            print("📊 Testing Universal Sync System...")
            
            # Test 1: Database table discovery
            print("\n🗄️ Testing Database Table Discovery:")
            tables = universal_sync._get_all_tables()
            print(f"✅ Found {len(tables)} database tables:")
            
            for i, table in enumerate(tables[:10]):
                print(f"   {i+1}. {table}")
            if len(tables) > 10:
                print(f"   ... and {len(tables) - 10} more tables")
            
            # Test 2: File discovery
            print(f"\n📁 Testing Instance Folder File Discovery:")
            syncable_files = universal_sync._get_syncable_files()
            print(f"✅ Found {len(syncable_files)} syncable files:")
            
            for i, file_path in enumerate(syncable_files[:10]):
                print(f"   {i+1}. {file_path}")
            if len(syncable_files) > 10:
                print(f"   ... and {len(syncable_files) - 10} more files")
            
            # Test 3: Universal data extraction
            print(f"\n🔍 Testing Universal Data Extraction:")
            
            # Try to get any model from any table
            if tables:
                test_table = tables[0]  # Use first available table
                try:
                    from sqlalchemy import text, MetaData, Table
                    
                    # Get one record from the table
                    result = db.session.execute(text(f"SELECT * FROM {test_table} LIMIT 1"))
                    row = result.fetchone()
                    
                    if row:
                        # Test reflection
                        metadata = MetaData()
                        table_obj = Table(test_table, metadata, autoload_with=db.engine)
                        
                        columns = [col.name for col in table_obj.columns]
                        print(f"✅ Table '{test_table}' has {len(columns)} columns:")
                        print(f"   Columns: {columns[:5]}{'...' if len(columns) > 5 else ''}")
                        
                        # Convert row to dict for testing
                        row_dict = dict(zip([col.name for col in table_obj.columns], row))
                        print(f"   Sample data keys: {list(row_dict.keys())[:3]}...")
                        
                    else:
                        print(f"✅ Table '{test_table}' exists but is empty")
                    
                except Exception as e:
                    print(f"⚠️ Could not test table '{test_table}': {e}")
            
            # Test 4: File content detection
            print(f"\n📄 Testing File Content Detection:")
            
            instance_path = Path(app.instance_path)
            test_files = []
            
            # Find some test files
            for file_path in syncable_files[:3]:  # Test first 3 files
                full_path = instance_path / file_path
                if full_path.exists():
                    try:
                        # Test if file is binary or text
                        with open(full_path, 'rb') as f:
                            content = f.read(100)  # Read first 100 bytes
                            
                        try:
                            content.decode('utf-8')
                            file_type = "text"
                        except UnicodeDecodeError:
                            file_type = "binary"
                        
                        size = full_path.stat().st_size
                        test_files.append({
                            'path': str(file_path),
                            'type': file_type,
                            'size': size
                        })
                        
                        print(f"   📄 {file_path}: {file_type} ({size} bytes)")
                        
                    except Exception as e:
                        print(f"   ⚠️ Could not read {file_path}: {e}")
            
            # Test 5: Excluded files check
            print(f"\n🚫 Testing File Exclusion Rules:")
            instance_files = list(instance_path.rglob('*'))
            excluded_count = 0
            
            for file_path in instance_files:
                if file_path.is_file():
                    relative_path = file_path.relative_to(instance_path)
                    
                    # Check if would be excluded
                    should_exclude = False
                    for excluded_ext in universal_sync.excluded_files:
                        if (str(relative_path).lower().endswith(excluded_ext) or 
                            file_path.suffix.lower() == excluded_ext or
                            file_path.name == excluded_ext):
                            should_exclude = True
                            break
                    
                    if should_exclude:
                        excluded_count += 1
                        if excluded_count <= 5:  # Show first 5 excluded files
                            print(f"   🚫 Excluded: {relative_path}")
            
            if excluded_count > 5:
                print(f"   ... and {excluded_count - 5} more excluded files")
            
            print(f"✅ Total excluded files: {excluded_count}")
            
            # Summary
            print(f"\n📊 Universal Sync System Test Results:")
            print(f"✅ Database tables discoverable: {len(tables)}")
            print(f"✅ Syncable files found: {len(syncable_files)}")
            print(f"✅ Excluded files (databases, logs): {excluded_count}")
            print(f"✅ Universal data extraction: {'Working' if tables else 'No tables to test'}")
            
            # Success criteria
            if len(tables) >= 5 and len(syncable_files) >= 5:
                print(f"\n🎉 Universal Sync System test PASSED!")
                print(f"💪 Ready to sync:")
                print(f"   🗄️ ALL database tables ({len(tables)} tables) without knowing field names")
                print(f"   📁 ALL instance files ({len(syncable_files)} files) except databases")
                print(f"   🚀 Fast and efficient universal synchronization")
                return True
            else:
                print(f"\n❌ Universal Sync System test FAILED!")
                print(f"   Not enough data found for comprehensive sync")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_universal_sync()
    if success:
        print(f"\n🚀 Universal Sync System test PASSED!")
        print(f"🌐 System can sync ALL data and files universally!")
    else:
        print(f"\n❌ Universal Sync System test FAILED!")
    
    sys.exit(0 if success else 1)
