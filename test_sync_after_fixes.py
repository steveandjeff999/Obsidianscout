#!/usr/bin/env python3
"""
Test Manual Sync After Fixes
"""

def test_sync_after_fixes():
    """Test sync functionality after applying all fixes"""
    print("🧪 TESTING SYNC AFTER FIXES")
    print("=" * 50)
    
    try:
        from app import create_app, db
        from app.models import SyncServer, DatabaseChange
        from app.utils.simplified_sync import simplified_sync_manager
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ CHECKING SERVER STATUS")
            print("-" * 30)
            
            servers = SyncServer.query.all()
            for server in servers:
                print(f"Server: {server.name}")
                print(f"  URL: {server.protocol}://{server.host}:{server.port}")
                print(f"  Healthy: {server.is_healthy}")
                print(f"  Last ping: {server.last_ping}")
                print(f"  Error count: {server.error_count}")
            
            print("\n2️⃣ CREATING TEST DATABASE CHANGES")
            print("-" * 30)
            
            # Create test changes to sync
            from datetime import datetime
            import json
            
            test_changes = []
            for i in range(3):
                change_data = {
                    'test_field': f'test_value_{i}',
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                change = DatabaseChange(
                    table_name='test_sync',
                    record_id=f'test_record_{i}',
                    operation=f'test_operation_{i}',
                    change_data=json.dumps(change_data),
                    timestamp=datetime.utcnow(),
                    sync_status='pending',
                    created_by_server='local'
                )
                test_changes.append(change)
                db.session.add(change)
            
            db.session.commit()
            print(f"✅ Created {len(test_changes)} test database changes")
            
            print("\n3️⃣ TESTING MANUAL SYNC")
            print("-" * 30)
            
            for server in servers:
                if server.sync_enabled:
                    print(f"\n🔄 Testing sync with {server.name}...")
                    
                    try:
                        result = simplified_sync_manager.perform_bidirectional_sync(server.id)
                        
                        print(f"Success: {result['success']}")
                        if result['success']:
                            print(f"  ✅ Operations: {len(result['operations'])}")
                            print(f"  📤 Sent to remote: {result['stats']['sent_to_remote']}")
                            print(f"  📥 Received from remote: {result['stats']['received_from_remote']}")
                            print(f"  ⚠️  Conflicts resolved: {result['stats']['conflicts_resolved']}")
                            
                            for op in result['operations'][:5]:  # Show first 5 operations
                                print(f"     • {op}")
                        else:
                            print(f"  ❌ Error: {result.get('error', 'Unknown error')}")
                            
                    except Exception as e:
                        print(f"  ❌ Exception: {e}")
                        import traceback
                        traceback.print_exc()
            
            print("\n4️⃣ CHECKING SYNC RESULTS")
            print("-" * 30)
            
            # Check if changes were marked as synced
            synced_changes = DatabaseChange.query.filter_by(sync_status='synced').count()
            pending_changes = DatabaseChange.query.filter_by(sync_status='pending').count()
            
            print(f"Synced changes: {synced_changes}")
            print(f"Pending changes: {pending_changes}")
            
            # Show recent sync logs
            from app.models import SyncLog
            recent_logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(3).all()
            
            print(f"\n📋 Recent sync logs ({len(recent_logs)}):")
            for log in recent_logs:
                print(f"  • {log.sync_type} - {log.status} - {log.started_at}")
                if log.error_message:
                    print(f"    Error: {log.error_message}")
            
            print("\n" + "=" * 50)
            if synced_changes > 0:
                print("🎉 SYNC IS WORKING! Changes are being synchronized.")
            elif pending_changes > 0:
                print("⚠️  SYNC PARTIAL: Some changes pending, check connectivity.")
            else:
                print("❓ SYNC STATUS UNCLEAR: No test changes found.")
            print("=" * 50)
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sync_after_fixes()
