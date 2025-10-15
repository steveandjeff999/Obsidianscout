#!/usr/bin/env python
"""Check current sync status and force a fresh sync"""
from app import create_app
from app.models import DatabaseChange, SyncServer, User
from app.utils.simplified_sync import simplified_sync_manager
from datetime import datetime, timezone, timedelta
import json

app = create_app()

def check_and_sync_recent_changes():
    with app.app_context():
        print("🔍 CHECKING RECENT USER CHANGES")
        print("=" * 50)
        
        # Check recent user changes (last 2 hours)
        since_time = datetime.now(timezone.utc) - timedelta(hours=2)
        recent_changes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.timestamp > since_time
        ).order_by(DatabaseChange.timestamp.desc()).all()
        
        print(f"Recent user changes in last 2 hours: {len(recent_changes)}")
        
        for change in recent_changes:
            status_emoji = "✅" if change.sync_status == 'synced' else "⏳" if change.sync_status == 'pending' else "❌"
            print(f"  {status_emoji} ID:{change.id} {change.operation} user:{change.record_id} - {change.sync_status} ({change.timestamp})")
        
        # Check pending changes specifically
        pending_changes = DatabaseChange.query.filter_by(
            table_name='user',
            sync_status='pending'
        ).all()
        
        print(f"\n📋 PENDING USER CHANGES: {len(pending_changes)}")
        for change in pending_changes:
            print(f"  ⏳ ID:{change.id} {change.operation} user:{change.record_id} - created: {change.timestamp}")
            if change.change_data:
                try:
                    data = json.loads(change.change_data)
                    username = data.get('username', 'Unknown')
                    is_active = data.get('is_active', True)
                    print(f"      Username: {username}, Active: {is_active}")
                except:
                    pass
        
        # Check current users
        print(f"\n👥 CURRENT LOCAL USERS:")
        users = User.query.all()
        for user in users:
            status = "ACTIVE" if user.is_active else "DELETED/INACTIVE"
            print(f"  - {user.username} (ID:{user.id}) [{status}]")
        
        # Get sync server
        server = SyncServer.query.filter_by(sync_enabled=True).first()
        if not server:
            print("❌ No sync server configured")
            return
        
        print(f"\n🔄 SYNC SERVER STATUS")
        print(f"Server: {server.name} ({server.base_url})")
        print(f"Last sync: {server.last_sync}")
        print(f"Sync enabled: {server.sync_enabled}")
        print(f"Database sync: {server.sync_database}")
        
        # Force a manual sync
        if pending_changes or input("\n🔄 Force sync now? (y/n): ").lower().startswith('y'):
            print(f"\n🚀 FORCING MANUAL SYNC...")
            print("=" * 30)
            
            result = simplified_sync_manager.perform_bidirectional_sync(server.id)
            
            if result.get('success'):
                print("✅ SYNC COMPLETED SUCCESSFULLY!")
                print(f"   Sent to remote: {result['stats']['sent_to_remote']}")
                print(f"   Received from remote: {result['stats']['received_from_remote']}")
                if result['stats']['errors']:
                    print(f"   Errors: {result['stats']['errors']}")
            else:
                print(f"❌ SYNC FAILED: {result.get('error')}")
                if 'stats' in result and result['stats']['errors']:
                    print("Errors:")
                    for error in result['stats']['errors']:
                        print(f"  - {error}")
            
            # Check pending changes after sync
            remaining_pending = DatabaseChange.query.filter_by(
                table_name='user',
                sync_status='pending'
            ).count()
            print(f"\n📊 REMAINING PENDING CHANGES: {remaining_pending}")
            
            if remaining_pending == 0:
                print("🎉 All user changes have been synced!")
            else:
                print(f"⚠️ {remaining_pending} changes are still pending")
        
        print(f"\n📋 INSTRUCTIONS TO VERIFY:")
        print(f"1. Go to remote server: {server.base_url}/auth/manage_users")
        print(f"2. Look for users you added/deleted")
        print(f"3. Check if deleted users are marked as inactive")
        print(f"4. Create a user on remote server to test reverse sync")

if __name__ == "__main__":
    check_and_sync_recent_changes()
