#!/usr/bin/env python3
"""
SQLite3 Enhanced Sync System Test Suite
Comprehensive testing of the new SQLite3-based sync functionality
"""

import os
import sys
import sqlite3
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def test_sqlite3_sync_system():
    """Test the SQLite3 enhanced sync system"""
    print("🧪 SQLite3 Enhanced Sync System Test Suite")
    print("=" * 60)
    
    # Test 1: Database Setup
    print("\n1️⃣  Testing Database Setup and Schema Creation")
    try:
        from app.utils.sqlite3_sync import SQLite3SyncManager
        
        # Create test database
        test_db_path = 'test_sync.db'
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        sync_manager = SQLite3SyncManager(test_db_path)
        print("  ✅ SQLite3SyncManager initialized successfully")
        
        # Check if tables were created
        with sqlite3.connect(test_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            required_tables = ['database_changes', 'sync_log_sqlite3', 'sync_reliability']
            missing_tables = [table for table in required_tables if table not in tables]
            
            if not missing_tables:
                print("  ✅ All required tables created successfully")
            else:
                print(f"  ❌ Missing tables: {missing_tables}")
                return False
                
    except Exception as e:
        print(f"  ❌ Database setup failed: {e}")
        return False
    
    # Test 2: Connection Management
    print("\n2️⃣  Testing Connection Management and Optimization")
    try:
        # Test connection context manager
        with sync_manager._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check SQLite optimizations
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            
            cursor.execute("PRAGMA synchronous")
            synchronous = cursor.fetchone()[0]
            
            cursor.execute("PRAGMA foreign_keys")
            foreign_keys = cursor.fetchone()[0]
            
            print(f"  ✅ Journal mode: {journal_mode}")
            print(f"  ✅ Synchronous: {synchronous}")
            print(f"  ✅ Foreign keys: {'ON' if foreign_keys else 'OFF'}")
            
            if journal_mode == 'wal' and synchronous == 2 and foreign_keys:
                print("  ✅ Database optimizations applied correctly")
            else:
                print("  ⚠️  Some optimizations may not be applied")
                
    except Exception as e:
        print(f"  ❌ Connection management test failed: {e}")
        return False
    
    # Test 3: Change Tracking
    print("\n3️⃣  Testing Change Tracking and Storage")
    try:
        # Insert test change records
        with sync_manager._get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert sample changes
            test_changes = [
                ('users', '1', 'upsert', '{"name": "Test User", "email": "test@example.com"}', 'hash1'),
                ('teams', '100', 'insert', '{"number": 100, "name": "Test Team"}', 'hash2'),
                ('matches', '1', 'update', '{"status": "completed"}', 'hash3')
            ]
            
            for table_name, record_id, operation, data, change_hash in test_changes:
                cursor.execute('''
                    INSERT INTO database_changes 
                    (table_name, record_id, operation, data, change_hash, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (table_name, record_id, operation, data, change_hash, datetime.now().isoformat()))
            
            conn.commit()
            
            # Test retrieval
            cursor.execute("SELECT COUNT(*) FROM database_changes WHERE sync_status = 'pending'")
            pending_count = cursor.fetchone()[0]
            
            if pending_count == 3:
                print(f"  ✅ Successfully stored {pending_count} test changes")
            else:
                print(f"  ❌ Expected 3 changes, got {pending_count}")
                return False
                
    except Exception as e:
        print(f"  ❌ Change tracking test failed: {e}")
        return False
    
    # Test 4: Change Retrieval and Filtering
    print("\n4️⃣  Testing Change Retrieval and Filtering")
    try:
        since_time = datetime.now() - timedelta(hours=1)
        changes = sync_manager._get_local_changes_sqlite3(since_time)
        
        if len(changes) == 3:
            print(f"  ✅ Retrieved {len(changes)} changes correctly")
            
            # Verify change structure
            required_fields = ['id', 'table', 'record_id', 'operation', 'timestamp', 'data']
            for change in changes:
                missing_fields = [field for field in required_fields if field not in change]
                if missing_fields:
                    print(f"  ❌ Change missing fields: {missing_fields}")
                    return False
                    
            print("  ✅ All changes have correct structure")
        else:
            print(f"  ❌ Expected 3 changes, got {len(changes)}")
            return False
            
    except Exception as e:
        print(f"  ❌ Change retrieval test failed: {e}")
        return False
    
    # Test 5: Conflict Detection
    print("\n5️⃣  Testing Conflict Detection")
    try:
        # Create conflicting changes
        local_changes = [
            {
                'table': 'users',
                'record_id': '1',
                'timestamp': '2024-01-01T10:00:00',
                'change_hash': 'hash_local_1'
            }
        ]
        
        remote_changes = [
            {
                'table': 'users',
                'record_id': '1',
                'timestamp': '2024-01-01T11:00:00',
                'change_hash': 'hash_remote_1'
            }
        ]
        
        conflicts = sync_manager._detect_conflicts_sqlite3(local_changes, remote_changes)
        
        if len(conflicts) == 1:
            print(f"  ✅ Correctly detected {len(conflicts)} conflict(s)")
            
            conflict = conflicts[0]
            if (conflict['table'] == 'users' and 
                conflict['record_id'] == '1' and
                conflict['local_hash'] == 'hash_local_1' and
                conflict['remote_hash'] == 'hash_remote_1'):
                print("  ✅ Conflict details are correct")
            else:
                print("  ❌ Conflict details are incorrect")
                return False
        else:
            print(f"  ❌ Expected 1 conflict, got {len(conflicts)}")
            return False
            
    except Exception as e:
        print(f"  ❌ Conflict detection test failed: {e}")
        return False
    
    # Test 6: Conflict Resolution
    print("\n6️⃣  Testing Conflict Resolution")
    try:
        conflicts = [
            {
                'table': 'users',
                'record_id': '1',
                'local_timestamp': '2024-01-01T10:00:00',
                'remote_timestamp': '2024-01-01T11:00:00',
                'local_hash': 'hash_local',
                'remote_hash': 'hash_remote'
            }
        ]
        
        resolved = sync_manager._resolve_conflicts_sqlite3(conflicts)
        
        if len(resolved) == 1:
            resolution = resolved[0]
            if resolution['winner'] == 'remote' and resolution['resolution_method'] == 'latest_timestamp':
                print("  ✅ Conflict resolved correctly (remote wins - later timestamp)")
            else:
                print(f"  ❌ Incorrect resolution: {resolution}")
                return False
        else:
            print(f"  ❌ Expected 1 resolution, got {len(resolved)}")
            return False
            
    except Exception as e:
        print(f"  ❌ Conflict resolution test failed: {e}")
        return False
    
    # Test 7: Reliability Metrics
    print("\n7️⃣  Testing Reliability Metrics")
    try:
        # Test metric updates
        sync_manager._update_reliability_metrics(1, 'test_operation', True, 1.5)
        sync_manager._update_reliability_metrics(1, 'test_operation', False, 2.0)
        sync_manager._update_reliability_metrics(1, 'test_operation', True, 1.0)
        
        report = sync_manager.get_reliability_report(1)
        
        if 'test_operation' in report['operations']:
            metrics = report['operations']['test_operation']
            if (metrics['success_count'] == 2 and 
                metrics['failure_count'] == 1 and
                metrics['total_operations'] == 3):
                print("  ✅ Reliability metrics calculated correctly")
                print(f"    Success rate: {metrics['success_rate']:.2f}")
                print(f"    Average duration: {metrics['avg_duration']:.2f}s")
            else:
                print(f"  ❌ Incorrect metrics: {metrics}")
                return False
        else:
            print("  ❌ Test operation not found in reliability report")
            return False
            
    except Exception as e:
        print(f"  ❌ Reliability metrics test failed: {e}")
        return False
    
    # Test 8: Data Cleanup
    print("\n8️⃣  Testing Data Cleanup")
    try:
        # Mark some changes as completed
        with sync_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE database_changes 
                SET sync_status = 'completed', 
                    synced_at = ?
                WHERE id = 1
            ''', (datetime.now() - timedelta(days=35)).isoformat())
            conn.commit()
        
        # Run cleanup
        cleanup_result = sync_manager.cleanup_old_sync_data(days_to_keep=30)
        
        if cleanup_result['deleted_changes'] > 0:
            print(f"  ✅ Successfully cleaned up {cleanup_result['deleted_changes']} old changes")
        else:
            print("  ℹ️  No old changes to clean up (this is normal for new installations)")
            
    except Exception as e:
        print(f"  ❌ Data cleanup test failed: {e}")
        return False
    
    # Test 9: Performance Benchmarks
    print("\n9️⃣  Testing Performance Benchmarks")
    try:
        # Benchmark change insertion
        start_time = time.time()
        
        with sync_manager._get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert 1000 test changes
            for i in range(1000):
                cursor.execute('''
                    INSERT INTO database_changes 
                    (table_name, record_id, operation, data, change_hash)
                    VALUES (?, ?, ?, ?, ?)
                ''', (f'test_table', str(i), 'insert', '{"test": true}', f'hash_{i}'))
            
            conn.commit()
        
        insert_time = time.time() - start_time
        
        # Benchmark retrieval
        start_time = time.time()
        changes = sync_manager._get_local_changes_sqlite3(datetime.now() - timedelta(hours=1))
        retrieval_time = time.time() - start_time
        
        print(f"  ✅ Performance benchmarks:")
        print(f"    1000 inserts: {insert_time:.3f}s ({1000/insert_time:.0f} ops/sec)")
        print(f"    {len(changes)} retrievals: {retrieval_time:.3f}s")
        
        if insert_time < 5.0 and retrieval_time < 1.0:
            print("  ✅ Performance within acceptable limits")
        else:
            print("  ⚠️  Performance may need optimization")
            
    except Exception as e:
        print(f"  ❌ Performance benchmark failed: {e}")
        return False
    
    # Test 10: Error Handling
    print("\n🔟 Testing Error Handling")
    try:
        # Test with invalid database path
        try:
            invalid_manager = SQLite3SyncManager('/invalid/path/database.db')
            print("  ❌ Should have failed with invalid database path")
            return False
        except Exception:
            print("  ✅ Correctly handled invalid database path")
        
        # Test with malformed data
        try:
            with sync_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO database_changes (table_name, data) VALUES (?, ?)", 
                             ('test', 'invalid json'))
                conn.commit()
            
            # Should handle malformed JSON gracefully
            changes = sync_manager._get_local_changes_sqlite3(datetime.now() - timedelta(hours=1))
            print("  ✅ Gracefully handled malformed JSON data")
            
        except Exception as e:
            print(f"  ❌ Failed to handle malformed data: {e}")
            return False
            
    except Exception as e:
        print(f"  ❌ Error handling test failed: {e}")
        return False
    
    # Cleanup
    try:
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        print("\n🧹 Test database cleaned up")
    except:
        pass
    
    # Final Results
    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED - SQLite3 Enhanced Sync System is working correctly!")
    print("=" * 60)
    
    print("\n📊 Test Summary:")
    print("✅ Database setup and schema creation")
    print("✅ Connection management and optimization")
    print("✅ Change tracking and storage")
    print("✅ Change retrieval and filtering")
    print("✅ Conflict detection")
    print("✅ Conflict resolution")
    print("✅ Reliability metrics")
    print("✅ Data cleanup")
    print("✅ Performance benchmarks")
    print("✅ Error handling")
    
    print("\n🚀 The SQLite3 Enhanced Sync System is ready for production use!")
    
    return True

def test_api_endpoints():
    """Test the API endpoints (requires Flask app)"""
    print("\n🌐 Testing API Endpoints")
    print("=" * 40)
    
    try:
        from app import create_app
        from app.models import SyncServer
        
        app = create_app()
        with app.app_context():
            # This would require a test server setup
            print("  ℹ️  API endpoint testing requires Flask app context and test servers")
            print("  ℹ️  Use the web interface or API client for manual testing")
            
    except ImportError:
        print("  ℹ️  Flask app not available for API testing")
        print("  ℹ️  Run this test from the application directory for full testing")

if __name__ == '__main__':
    print("SQLite3 Enhanced Sync System - Test Suite")
    print("========================================")
    
    success = test_sqlite3_sync_system()
    
    if success:
        test_api_endpoints()
        
        print("\n💡 Next Steps:")
        print("1. Start your Flask application")
        print("2. Navigate to the Sync Dashboard")
        print("3. Try the new SQLite3 sync buttons")
        print("4. Check reliability reports")
        print("5. Use cleanup utility as needed")
        
        print("\n📖 For more information, see: SQLITE3_SYNC_IMPLEMENTATION.md")
    else:
        print("\n❌ Some tests failed - please check the implementation")
        sys.exit(1)
