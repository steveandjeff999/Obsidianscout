#!/usr/bin/env python3
"""Test actual sync with full synchronization"""

from app import create_app, db
from app.models import User, Role, SyncServer
from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
from datetime import datetime

def test_full_sync_now():
    """Test the full sync functionality"""
    app = create_app()
    
    with app.app_context():
        print("🚀 Testing full sync functionality...")
        
        # Get the sync server
        server = SyncServer.query.filter_by(sync_enabled=True).first()
        if not server:
            print("❌ No sync server configured")
            return
            
        print(f"📡 Using sync server: {server.name} ({server.protocol}://{server.host}:{server.port})")
        
        # Create a test user with roles
        print("\n1️⃣ Creating test user with roles...")
        test_username = f"sync_test_{datetime.now().strftime('%M%S')}"
        test_user = User(username=test_username, scouting_team_number=9999)
        test_user.set_password('test123')
        
        # Assign multiple roles
        admin_role = Role.query.filter_by(name='admin').first()
        scout_role = Role.query.filter_by(name='scout').first()
        
        if admin_role:
            test_user.roles.append(admin_role)
            print(f"  ✅ Assigned admin role to {test_user.username}")
        if scout_role:
            test_user.roles.append(scout_role)
            print(f"  ✅ Assigned scout role to {test_user.username}")
            
        db.session.add(test_user)
        db.session.commit()
        
        user_id = test_user.id
        print(f"  ✅ Created user ID: {user_id}")
        
        # Initialize sync system
        print("\n2️⃣ Performing full sync...")
        sync_system = AutomaticSQLite3Sync()
        
        try:
            # Test the full sync
            result = sync_system.perform_full_sync_all_tables(server.id)
            
            print(f"\n📊 Sync Results:")
            print(f"  Success: {result['success']}")
            
            if result['success']:
                print(f"  Local changes sent: {result['local_changes_sent']}")
                print(f"  Remote changes received: {result['remote_changes_received']}")
                print(f"  Tables synced: {result['total_tables_synced']}")
                
                print(f"\n📋 Operations performed:")
                for operation in result['operations']:
                    print(f"    {operation}")
                    
            else:
                print(f"  ❌ Error: {result.get('error', 'Unknown error')}")
                for operation in result.get('operations', []):
                    if operation.startswith('❌'):
                        print(f"    {operation}")
                        
        except Exception as e:
            print(f"❌ Sync failed with exception: {e}")
            import traceback
            traceback.print_exc()
            
        print(f"\n✅ Test completed!")
        print(f"Check the remote server to see if user '{test_username}' was created with roles.")

if __name__ == "__main__":
    test_full_sync_now()
