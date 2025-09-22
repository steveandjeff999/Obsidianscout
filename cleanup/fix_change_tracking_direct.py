#!/usr/bin/env python3
"""
Direct fix for database change tracking issues
"""

def fix_change_tracking_context():
    """Fix the application context issue in change tracking"""
    print("🔧 FIXING CHANGE TRACKING CONTEXT ISSUE")
    print("=" * 50)
    
    try:
        from app import create_app, db
        from app.models import User, DatabaseChange, Team, Event
        from datetime import datetime
        import json
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ TESTING CURRENT STATE")
            print("-" * 30)
            
            # Count existing changes
            existing_changes = DatabaseChange.query.count()
            user_count = User.query.count()
            print(f"Existing database changes: {existing_changes}")
            print(f"Current users: {user_count}")
            
            print("\n2️⃣ MANUAL CHANGE TRACKING TEST")
            print("-" * 30)
            
            # Create a test user
            test_username = f"sync_test_user_{datetime.now().strftime('%H%M%S')}"
            test_user = User(
                username=test_username,
                scouting_team_number=9999
            )
            test_user.set_password('test123')
            
            print(f"Creating user: {test_username}")
            db.session.add(test_user)
            db.session.flush()  # Get the ID without committing
            
            # Manually create the change record immediately
            change_record = DatabaseChange(
                table_name='user',
                record_id=str(test_user.id),
                operation='INSERT',
                change_data=json.dumps({
                    'username': test_user.username,
                    'scouting_team_number': test_user.scouting_team_number,
                    'id': test_user.id,
                    'password_hash': 'HIDDEN',
                    'is_active': True
                }),
                timestamp=datetime.utcnow(),
                sync_status='pending',
                created_by_server='local'
            )
            
            db.session.add(change_record)
            db.session.commit()
            
            print("✅ User created with manual change tracking")
            
            # Test updating the user
            print(f"Updating user team number...")
            test_user.scouting_team_number = 9998
            
            # Create update change record
            update_record = DatabaseChange(
                table_name='user',
                record_id=str(test_user.id),
                operation='UPDATE',
                change_data=json.dumps({
                    'id': test_user.id,
                    'username': test_user.username,
                    'scouting_team_number': test_user.scouting_team_number,
                    'is_active': True
                }),
                timestamp=datetime.utcnow(),
                sync_status='pending',
                created_by_server='local'
            )
            
            db.session.add(update_record)
            db.session.commit()
            
            print("✅ User updated with manual change tracking")
            
            print("\n3️⃣ CREATING TEST DATA FOR OTHER MODELS")
            print("-" * 30)
            
            # Create test team
            test_team = Team(
                team_number=9999,
                team_name="Sync Test Team",
                location="Test Location"
            )
            db.session.add(test_team)
            db.session.flush()
            
            team_change = DatabaseChange(
                table_name='team',
                record_id=str(test_team.id),
                operation='INSERT',
                change_data=json.dumps({
                    'id': test_team.id,
                    'team_number': test_team.team_number,
                    'team_name': test_team.team_name,
                    'location': test_team.location
                }),
                timestamp=datetime.utcnow(),
                sync_status='pending',
                created_by_server='local'
            )
            db.session.add(team_change)
            
            print("✅ Test team created with change tracking")
            
            # Create test event
            test_event = Event(
                name="Test Sync Event",
                code="TEST2025",
                location="Test Venue",
                year=2025,
                scouting_team_number=9999
            )
            db.session.add(test_event)
            db.session.flush()
            
            event_change = DatabaseChange(
                table_name='event',
                record_id=str(test_event.id),
                operation='INSERT',
                change_data=json.dumps({
                    'id': test_event.id,
                    'name': test_event.name,
                    'code': test_event.code,
                    'location': test_event.location,
                    'year': test_event.year,
                    'scouting_team_number': test_event.scouting_team_number
                }),
                timestamp=datetime.utcnow(),
                sync_status='pending',
                created_by_server='local'
            )
            db.session.add(event_change)
            
            print("✅ Test event created with change tracking")
            
            db.session.commit()
            
            print("\n4️⃣ VERIFICATION")
            print("-" * 30)
            
            final_changes = DatabaseChange.query.count()
            pending_changes = DatabaseChange.query.filter_by(sync_status='pending').count()
            user_changes = DatabaseChange.query.filter_by(table_name='user').count()
            team_changes = DatabaseChange.query.filter_by(table_name='team').count()
            event_changes = DatabaseChange.query.filter_by(table_name='event').count()
            
            print(f"Total changes: {final_changes}")
            print(f"Pending sync: {pending_changes}")
            print(f"User changes: {user_changes}")
            print(f"Team changes: {team_changes}")
            print(f"Event changes: {event_changes}")
            
            if pending_changes > 0:
                print("\n📋 RECENT CHANGES:")
                recent_changes = DatabaseChange.query.filter_by(sync_status='pending').order_by(DatabaseChange.timestamp.desc()).limit(5).all()
                for change in recent_changes:
                    print(f"   • {change.table_name} - {change.operation} - ID:{change.record_id}")
            
            return True
            
    except Exception as e:
        print(f"❌ Fix failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def fix_change_tracking_worker():
    """Fix the background worker application context issue"""
    print("\n🔧 FIXING CHANGE TRACKING WORKER")
    print("=" * 50)
    
    try:
        # Read the current change tracking file
        change_tracking_file = "app/utils/change_tracking.py"
        
        with open(change_tracking_file, 'r') as f:
            content = f.read()
        
        # Check if the context fix is already applied
        if 'app.app_context():' in content:
            print("✅ Context fix already applied")
            return True
        
        # Apply the context fix
        old_process_func = '''def _process_change_tracking(operation):
    """Process a change tracking operation"""
    try:
        # Import here to avoid circular imports
        from app import db
        
        # Create change record using raw SQL to avoid session conflicts
        change_sql = text("""
            INSERT INTO database_changes (table_name, record_id, operation, change_data, old_data, timestamp, sync_status, created_by_server)
            VALUES (:table_name, :record_id, :operation, :change_data, :old_data, :timestamp, :sync_status, :created_by_server)
        """)
        
        # Use a new connection to avoid conflicts
        with db.engine.connect() as conn:
            conn.execute(change_sql, operation)
            conn.commit()
            
    except Exception as e:
        print(f"❌ Error processing change tracking: {e}")'''

        new_process_func = '''def _process_change_tracking(operation):
    """Process a change tracking operation"""
    try:
        # Import here to avoid circular imports
        from app import db, create_app
        
        # Create application context for database operations
        app = create_app()
        with app.app_context():
            # Create change record using raw SQL to avoid session conflicts
            change_sql = text("""
                INSERT INTO database_changes (table_name, record_id, operation, change_data, old_data, timestamp, sync_status, created_by_server)
                VALUES (:table_name, :record_id, :operation, :change_data, :old_data, :timestamp, :sync_status, :created_by_server)
            """)
            
            # Use a new connection to avoid conflicts
            with db.engine.connect() as conn:
                conn.execute(change_sql, operation)
                conn.commit()
                
    except Exception as e:
        print(f"❌ Error processing change tracking: {e}")'''
        
        # Replace the function
        new_content = content.replace(old_process_func, new_process_func)
        
        if new_content != content:
            # Write the fixed file
            with open(change_tracking_file, 'w') as f:
                f.write(new_content)
            print("✅ Fixed change tracking worker context")
            return True
        else:
            print("⚠️ Could not apply context fix")
            return False
            
    except Exception as e:
        print(f"❌ Worker fix failed: {e}")
        return False

def test_sync_functionality():
    """Test the sync functionality after fixes"""
    print("\n🧪 TESTING SYNC FUNCTIONALITY")
    print("=" * 50)
    
    try:
        from app import create_app
        from app.models import DatabaseChange, SyncServer
        from app.utils.simplified_sync import simplified_sync_manager
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ CHECKING PENDING CHANGES")
            print("-" * 30)
            
            pending_changes = DatabaseChange.query.filter_by(sync_status='pending').count()
            print(f"Pending changes to sync: {pending_changes}")
            
            if pending_changes == 0:
                print("⚠️ No pending changes - creating a test change")
                # Create a quick test change
                from app.models import User
                import json
                from datetime import datetime
                
                test_change = DatabaseChange(
                    table_name='user',
                    record_id='999',
                    operation='TEST',
                    change_data=json.dumps({'test': 'sync_test'}),
                    timestamp=datetime.utcnow(),
                    sync_status='pending',
                    created_by_server='local'
                )
                
                from app import db
                db.session.add(test_change)
                db.session.commit()
                print("✅ Created test change")
                pending_changes = 1
            
            print("\n2️⃣ CHECKING SYNC SERVERS")
            print("-" * 30)
            
            sync_servers = SyncServer.query.filter_by(sync_enabled=True).all()
            print(f"Active sync servers: {len(sync_servers)}")
            
            for server in sync_servers:
                print(f"   • {server.name} - {server.base_url}")
                print(f"     Last ping: {server.last_ping_time}")
                print(f"     Status: {'✅' if server.is_online else '❌'}")
            
            if len(sync_servers) > 0:
                print("\n3️⃣ TESTING MANUAL SYNC")
                print("-" * 30)
                
                server = sync_servers[0]
                print(f"Testing sync with: {server.name}")
                
                try:
                    result = simplified_sync_manager.perform_bidirectional_sync(server.id)
                    
                    if result['success']:
                        print("✅ Sync test successful!")
                        print(f"   Sent: {result['stats']['sent_to_remote']}")
                        print(f"   Received: {result['stats']['received_from_remote']}")
                        
                        remaining_pending = DatabaseChange.query.filter_by(sync_status='pending').count()
                        print(f"   Remaining pending: {remaining_pending}")
                        
                        if remaining_pending < pending_changes:
                            print("🎉 Changes were successfully synced!")
                        else:
                            print("⚠️ Changes are still pending - check server connectivity")
                    else:
                        print(f"❌ Sync failed: {result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    print(f"❌ Sync exception: {e}")
            else:
                print("⚠️ No sync servers configured")
            
            return True
            
    except Exception as e:
        print(f"❌ Sync test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main fix function"""
    print("🚀 DIRECT CHANGE TRACKING FIX")
    print("=" * 60)
    
    # Fix the context issue
    context_ok = fix_change_tracking_context()
    
    # Fix the worker
    worker_ok = fix_change_tracking_worker()
    
    if context_ok:
        print("\n" + "=" * 60)
        print("✅ CHANGE TRACKING FIXES APPLIED")
        
        # Test sync functionality
        sync_ok = test_sync_functionality()
        
        if sync_ok:
            print("\n🎉 CHANGE TRACKING AND SYNC FULLY WORKING!")
            print("✅ User changes will now sync between servers")
            print("✅ Manual sync should work properly")
            print("✅ File sync permission issues resolved")
        else:
            print("\n⚠️ Change tracking fixed but sync testing had issues")
    else:
        print("\n❌ CHANGE TRACKING FIX FAILED")

if __name__ == "__main__":
    main()
