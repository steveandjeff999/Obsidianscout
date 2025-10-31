#!/usr/bin/env python
"""Complete test: Add user, sync, delete user, sync"""
from app import create_app
from app.models import DatabaseChange, SyncServer, User
from app.utils.simplified_sync import simplified_sync_manager
from datetime import datetime, timezone
import json

app = create_app()

def complete_sync_test():
    with app.app_context():
        print(" COMPLETE USER SYNC TEST")
        print("=" * 60)
        
        server = SyncServer.query.filter_by(sync_enabled=True).first()
        if not server:
            print(" No sync server configured")
            return
        
        print(f"Testing with server: {server.name} ({server.base_url})")
        
        # Step 1: Create a new test user
        print(f"\n1. CREATING TEST USER")
        print("-" * 30)
        
        test_username = f"complete_sync_test_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        test_user = User(username=test_username, scouting_team_number=7777)
        test_user.set_password('TestSync123!')
        
        from app import db
        db.session.add(test_user)
        db.session.flush()  # Get ID
        
        # Manual change tracking
        try:
            DatabaseChange.log_change(
                table_name='user',
                record_id=test_user.id,
                operation='insert',
                new_data={
                    'id': test_user.id,
                    'username': test_user.username,
                    'scouting_team_number': test_user.scouting_team_number,
                    'is_active': test_user.is_active
                },
                server_id='local'
            )
        except Exception as e:
            print(f" Manual change tracking failed: {e}")
            
        db.session.commit()
        
        print(f" Created user: {test_user.username} (ID:{test_user.id})")
        
        # Step 2: Sync the new user
        print(f"\n2. SYNCING NEW USER TO REMOTE")
        print("-" * 30)
        
        result = simplified_sync_manager.perform_bidirectional_sync(server.id)
        
        if result.get('success'):
            print(f" Sync successful - Sent: {result['stats']['sent_to_remote']}")
        else:
            print(f" Sync failed: {result.get('error')}")
            return
        
        # Step 3: Wait a moment then delete the user
        print(f"\n3. DELETING TEST USER")
        print("-" * 30)
        
        user_id = test_user.id
        username = test_user.username
        
        # Hard delete the user
        db.session.delete(test_user)
        
        # Manual delete change tracking
        try:
            DatabaseChange.log_change(
                table_name='user',
                record_id=user_id,
                operation='delete',
                old_data={
                    'id': user_id,
                    'username': username,
                    'scouting_team_number': 7777,
                    'is_active': False
                },
                server_id='local'
            )
        except Exception as e:
            print(f" Manual delete change tracking failed: {e}")
            
        db.session.commit()
        
        print(f" Deleted user: {username} (ID:{user_id})")
        
        # Step 4: Sync the deletion
        print(f"\n4. SYNCING USER DELETION TO REMOTE")
        print("-" * 30)
        
        result = simplified_sync_manager.perform_bidirectional_sync(server.id)
        
        if result.get('success'):
            print(f" Delete sync successful - Sent: {result['stats']['sent_to_remote']}")
        else:
            print(f" Delete sync failed: {result.get('error')}")
            return
        
        # Step 5: Verify sync status
        print(f"\n5. VERIFICATION")
        print("-" * 30)
        
        pending_changes = DatabaseChange.query.filter_by(sync_status='pending').count()
        print(f"Remaining pending changes: {pending_changes}")
        
        if pending_changes == 0:
            print(" All changes synced successfully!")
        else:
            print(f"️ {pending_changes} changes still pending")
        
        # Show recent changes for this test
        recent_changes = DatabaseChange.query.filter(
            DatabaseChange.record_id == str(user_id)
        ).order_by(DatabaseChange.timestamp.desc()).all()
        
        print(f"\nChanges for test user {username}:")
        for change in recent_changes:
            status_emoji = "" if change.sync_status == 'synced' else "⏳" if change.sync_status == 'pending' else ""
            print(f"  {status_emoji} {change.operation.upper()} - {change.sync_status}")
        
        print(f"\n FINAL VERIFICATION STEPS:")
        print(f"1. Go to: {server.base_url}/auth/manage_users")
        print(f"2. User '{username}' should have appeared, then disappeared")
        print(f"3. Check that user is no longer in the remote user list")
        print(f"4. This confirms both ADD and DELETE operations are syncing properly")
        
        print(f"\n COMPLETE SYNC TEST FINISHED")
        print("The user addition and deletion should now be synced to the remote server!")

if __name__ == "__main__":
    complete_sync_test()
