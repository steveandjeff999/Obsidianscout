#!/usr/bin/env python
"""Manually track missing user deletions and sync them"""
from app import create_app
from app.models import DatabaseChange, SyncServer
from app.utils.simplified_sync import simplified_sync_manager
from datetime import datetime, timezone
import json

app = create_app()

def track_missing_user_deletions():
    with app.app_context():
        print("🔍 TRACKING MISSING USER DELETIONS")
        print("=" * 50)
        
        # Users that had recent changes but are no longer in the database
        missing_users = [
            {'id': 6, 'username': 'test5454', 'team': 5454},
            {'id': 7, 'username': 'sync_manual_cli', 'team': 4321},
            {'id': 8, 'username': 'sync_test_user_030653', 'team': 9999},
            {'id': 9, 'username': 'unknown_user', 'team': None}  # From change record ID:10
        ]
        
        print(f"Found {len(missing_users)} users that were deleted but not synced:")
        
        for user in missing_users:
            print(f"  - {user['username']} (ID:{user['id']}, Team:{user['team']})")
            
            # Create a delete change record
            try:
                delete_change = DatabaseChange(
                    table_name='user',
                    record_id=str(user['id']),
                    operation='delete',
                    change_data=None,
                    old_data=json.dumps({
                        'id': user['id'],
                        'username': user['username'],
                        'scouting_team_number': user['team'],
                        'is_active': False
                    }),
                    timestamp=datetime.now(timezone.utc),
                    sync_status='pending',
                    created_by_server='local'
                )
                
                from app import db
                db.session.add(delete_change)
                print(f"    ✅ Created delete change record")
                
            except Exception as e:
                print(f"    ❌ Failed to create delete change: {e}")
        
        db.session.commit()
        
        # Check pending changes
        pending_deletes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.operation == 'delete',
            DatabaseChange.sync_status == 'pending'
        ).count()
        
        print(f"\n📋 PENDING DELETE CHANGES: {pending_deletes}")
        
        if pending_deletes > 0:
            # Force sync
            server = SyncServer.query.filter_by(sync_enabled=True).first()
            if server:
                print(f"\n🚀 SYNCING DELETE CHANGES TO {server.name}...")
                
                result = simplified_sync_manager.perform_bidirectional_sync(server.id)
                
                if result.get('success'):
                    print("✅ DELETE SYNC COMPLETED!")
                    print(f"   Sent to remote: {result['stats']['sent_to_remote']}")
                    print(f"   Received from remote: {result['stats']['received_from_remote']}")
                    
                    remaining = DatabaseChange.query.filter(
                        DatabaseChange.table_name == 'user',
                        DatabaseChange.operation == 'delete',
                        DatabaseChange.sync_status == 'pending'
                    ).count()
                    
                    if remaining == 0:
                        print("🎉 All delete changes synced successfully!")
                    else:
                        print(f"⚠️ {remaining} delete changes still pending")
                        
                else:
                    print(f"❌ DELETE SYNC FAILED: {result.get('error')}")
            else:
                print("❌ No sync server found")
        
        print(f"\n📋 VERIFICATION:")
        print(f"Check remote server user list - the deleted users should no longer appear")
        print(f"or should be marked as deleted/inactive")

if __name__ == "__main__":
    track_missing_user_deletions()
