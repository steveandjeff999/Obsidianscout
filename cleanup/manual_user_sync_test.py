#!/usr/bin/env python
"""Create a test user and perform a manual sync.
Safe to re-run; generates unique username each execution.
"""
from app import create_app, db
from app.models import User, DatabaseChange, SyncServer
from app.utils.simplified_sync import simplified_sync_manager
from datetime import datetime, timezone
import json

app = create_app()

USERNAME_PREFIX = "sync_test_user"

def create_test_user():
    ts = datetime.now(timezone.utc).strftime('%H%M%S')
    username = f"{USERNAME_PREFIX}_{ts}"
    user = User(username=username, scouting_team_number=9999)
    user.set_password('TempPass123!')
    db.session.add(user)
    db.session.flush()  # get id
    # Manual change log to guarantee tracking
    try:
        DatabaseChange.log_change(
            table_name='user',
            record_id=user.id,
            operation='insert',
            new_data={
                'id': user.id,
                'username': user.username,
                'scouting_team_number': user.scouting_team_number,
                'is_active': user.is_active
            },
            server_id='local'
        )
    except Exception as e:
        print(f"[WARN] Failed to log change manually: {e}")
    db.session.commit()
    return user

def pick_sync_server():
    server = SyncServer.query.filter_by(sync_enabled=True).first()
    return server

with app.app_context():
    pending_before = DatabaseChange.query.filter_by(sync_status='pending').count()
    print(f"Pending changes before: {pending_before}")

    server = pick_sync_server()
    if not server:
        print("❌ No sync server configured (sync_enabled=True). Aborting.")
    else:
        print(f"Using sync server: {server.id} {server.name} {server.base_url}")
        user = create_test_user()
        print(f"Created test user: {user.username} (id={user.id})")
        pending_after_create = DatabaseChange.query.filter_by(sync_status='pending').count()
        print(f"Pending changes after user create: {pending_after_create}")

        # Perform manual bidirectional sync
        print("\n🔄 Performing bidirectional sync...")
        result = simplified_sync_manager.perform_bidirectional_sync(server.id)
        if result.get('success'):
            print("✅ Sync succeeded")
            print(json.dumps(result['stats'], indent=2))
        else:
            print("❌ Sync failed:", result.get('error'))
            if 'stats' in result:
                print(json.dumps(result['stats'], indent=2))
        pending_after_sync = DatabaseChange.query.filter_by(sync_status='pending').count()
        print(f"Pending changes after sync: {pending_after_sync}")

        # Show last few change rows for confirmation
        last_changes = DatabaseChange.query.order_by(DatabaseChange.timestamp.desc()).limit(5).all()
        print("\nRecent change records:")
        for ch in last_changes:
            print(f"  - {ch.id} {ch.table_name} {ch.operation} rec:{ch.record_id} status:{ch.sync_status}")

        print("\nDone.")
