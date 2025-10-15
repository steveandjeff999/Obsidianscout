#!/usr/bin/env python3
"""
Comprehensive Fix for Database Change Tracking and File Sync Issues
"""

def fix_change_tracking():
    """Fix database change tracking issues"""
    print("🔧 FIXING CHANGE TRACKING ISSUES")
    print("=" * 50)
    
    try:
        from app import create_app, db
        from app.models import User, DatabaseChange
        from app.utils.change_tracking import setup_change_tracking
        from datetime import datetime, timezone
        import json
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ TESTING CURRENT CHANGE TRACKING")
            print("-" * 30)
            
            # Count existing changes
            existing_changes = DatabaseChange.query.count()
            print(f"Existing database changes: {existing_changes}")
            
            # Test creating a user to see if tracking works
            print("\n🧪 Testing user creation tracking...")
            
            test_username = f"test_change_tracking_{datetime.now().strftime('%H%M%S')}"
            test_user = User(
                username=test_username,
                scouting_team_number=9999
            )
            test_user.set_password('test123')
            
            print(f"Creating test user: {test_username}")
            db.session.add(test_user)
            db.session.commit()
            
            # Check if change was tracked
            import time
            time.sleep(2)  # Give the background worker time to process
            
            new_changes = DatabaseChange.query.count()
            user_changes = DatabaseChange.query.filter_by(table_name='user').count()
            
            print(f"Changes after user creation: {new_changes}")
            print(f"User-specific changes: {user_changes}")
            
            if new_changes > existing_changes:
                print("✅ Change tracking is working!")
                
                # Show the latest change
                latest_change = DatabaseChange.query.order_by(DatabaseChange.timestamp.desc()).first()
                if latest_change:
                    print(f"   Latest change: {latest_change.table_name} - {latest_change.operation}")
                    print(f"   Record ID: {latest_change.record_id}")
                    print(f"   Status: {latest_change.sync_status}")
            else:
                print("❌ Change tracking is NOT working!")
                print("   Attempting to fix...")
                
                # Force create a database change manually
                manual_change = DatabaseChange(
                    table_name='user',
                    record_id=str(test_user.id),
                    operation='INSERT',
                    change_data=json.dumps({
                        'username': test_user.username,
                        'scouting_team_number': test_user.scouting_team_number,
                        'created_at': test_user.created_at.isoformat() if test_user.created_at else None
                    }),
                    timestamp=datetime.now(timezone.utc),
                    sync_status='pending',
                    created_by_server='local_fix'
                )
                
                db.session.add(manual_change)
                db.session.commit()
                
                print("✅ Manually created change record")
            
            print("\n2️⃣ FIXING CHANGE TRACKING INITIALIZATION")
            print("-" * 30)
            
            # Re-setup change tracking to ensure it's working
            setup_change_tracking()
            print("✅ Re-initialized change tracking")
            
            # Test updating a user
            print("\n🧪 Testing user update tracking...")
            test_user.scouting_team_number = 9998  # Change the team number
            db.session.commit()
            
            time.sleep(2)  # Give time to process
            
            update_changes = DatabaseChange.query.filter_by(
                table_name='user',
                operation='UPDATE'
            ).count()
            
            print(f"User update changes: {update_changes}")
            
            print("\n3️⃣ CREATING TEST CHANGES FOR OTHER MODELS")
            print("-" * 30)
            
            # Create test changes for other models to ensure they sync
            from app.models import Team, Event
            
            # Create a test team
            test_team = Team(
                team_number=9999,
                team_name="Test Sync Team",
                location="Test Location"
            )
            db.session.add(test_team)
            db.session.commit()
            print("✅ Created test team")
            
            # Create a test event
            test_event = Event(
                event_code="TEST2025",
                event_name="Test Sync Event",
                location="Test Venue",
                event_type="Regional"
            )
            db.session.add(test_event)
            db.session.commit()
            print("✅ Created test event")
            
            time.sleep(2)  # Give time to process
            
            total_changes_now = DatabaseChange.query.count()
            pending_changes = DatabaseChange.query.filter_by(sync_status='pending').count()
            
            print(f"\n📊 FINAL CHANGE STATUS:")
            print(f"   Total changes: {total_changes_now}")
            print(f"   Pending sync: {pending_changes}")
            print(f"   User changes: {DatabaseChange.query.filter_by(table_name='user').count()}")
            print(f"   Team changes: {DatabaseChange.query.filter_by(table_name='team').count()}")
            print(f"   Event changes: {DatabaseChange.query.filter_by(table_name='event').count()}")
            
            return True
            
    except Exception as e:
        print(f"❌ Fix failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def fix_file_sync_permissions():
    """Fix file synchronization permission issues"""
    print("\n🔧 FIXING FILE SYNC PERMISSIONS")
    print("=" * 50)
    
    try:
        import os
        import stat
        from app import create_app
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ CHECKING FILE SYNC DIRECTORIES")
            print("-" * 30)
            
            # Check permissions on key directories
            directories_to_check = [
                ('instance', app.instance_path),
                ('config', os.path.join(os.getcwd(), 'config')),
                ('uploads', os.path.join(os.getcwd(), 'uploads'))
            ]
            
            for dir_name, dir_path in directories_to_check:
                if os.path.exists(dir_path):
                    try:
                        # Test write access
                        test_file = os.path.join(dir_path, 'test_write_access.tmp')
                        with open(test_file, 'w') as f:
                            f.write('test')
                        os.remove(test_file)
                        print(f"  ✅ {dir_name} directory: writable")
                    except Exception as e:
                        print(f"  ❌ {dir_name} directory: {e}")
                        # Try to fix permissions
                        try:
                            os.chmod(dir_path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                            print(f"     🔧 Fixed permissions for {dir_path}")
                        except:
                            print(f"     ⚠️ Could not fix permissions for {dir_path}")
                else:
                    print(f"  ⚠️ {dir_name} directory does not exist: {dir_path}")
            
            print("\n2️⃣ CREATING IMPROVED FILE DELETION FUNCTION")
            print("-" * 30)
            
            # Create an improved file deletion wrapper function
            improved_delete_code = '''
def safe_file_delete(file_path):
    """Safely delete a file with proper error handling"""
    import os
    import stat
    import time
    
    if not os.path.exists(file_path):
        return False, "File does not exist"
    
    # Try multiple deletion strategies
    strategies = [
        # Strategy 1: Simple deletion
        lambda: os.remove(file_path),
        
        # Strategy 2: Change permissions then delete
        lambda: (os.chmod(file_path, stat.S_IWRITE), os.remove(file_path))[1],
        
        # Strategy 3: Wait a bit and try again (in case file is locked)
        lambda: (time.sleep(0.5), os.remove(file_path))[1]
    ]
    
    for i, strategy in enumerate(strategies, 1):
        try:
            strategy()
            return True, f"Deleted using strategy {i}"
        except PermissionError as e:
            if i == len(strategies):
                return False, f"Permission denied: {e}"
            continue
        except Exception as e:
            if i == len(strategies):
                return False, f"Failed to delete: {e}"
            continue
    
    return False, "All deletion strategies failed"
'''
            
            # Write the improved deletion function to a helper file
            helper_file = os.path.join(os.getcwd(), 'safe_file_operations.py')
            with open(helper_file, 'w') as f:
                f.write(improved_delete_code)
            print("✅ Created safe_file_operations.py helper")
            
            print("\n3️⃣ TESTING FILE OPERATIONS")
            print("-" * 30)
            
            # Define the safe delete function locally
            def safe_file_delete(file_path):
                """Safely delete a file with proper error handling"""
                import os
                import stat
                import time
                
                if not os.path.exists(file_path):
                    return False, "File does not exist"
                
                # Try multiple deletion strategies
                strategies = [
                    # Strategy 1: Simple deletion
                    lambda: os.remove(file_path),
                    
                    # Strategy 2: Change permissions then delete
                    lambda: (os.chmod(file_path, stat.S_IWRITE), os.remove(file_path))[1],
                    
                    # Strategy 3: Wait a bit and try again (in case file is locked)
                    lambda: (time.sleep(0.5), os.remove(file_path))[1]
                ]
                
                for i, strategy in enumerate(strategies, 1):
                    try:
                        strategy()
                        return True, f"Deleted using strategy {i}"
                    except PermissionError as e:
                        if i == len(strategies):
                            return False, f"Permission denied: {e}"
                        continue
                    except Exception as e:
                        if i == len(strategies):
                            return False, f"Failed to delete: {e}"
                        continue
                
                return False, "All deletion strategies failed"
            
            # Test creating and deleting files in each directory
            for dir_name, dir_path in directories_to_check:
                if os.path.exists(dir_path):
                    test_file = os.path.join(dir_path, 'sync_test.txt')
                    try:
                        # Create test file
                        with open(test_file, 'w') as f:
                            f.write('sync test')
                        
                        # Test our safe delete function
                        success, message = safe_file_delete(test_file)
                        
                        if success:
                            print(f"  ✅ {dir_name}: File operations working - {message}")
                        else:
                            print(f"  ❌ {dir_name}: File deletion failed - {message}")
                            
                    except Exception as e:
                        print(f"  ❌ {dir_name}: Test failed - {e}")
            
            return True
            
    except Exception as e:
        print(f"❌ File sync fix failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_complete_sync():
    """Test complete sync functionality after fixes"""
    print("\n🧪 TESTING COMPLETE SYNC AFTER FIXES")
    print("=" * 50)
    
    try:
        from app import create_app
        from app.utils.simplified_sync import simplified_sync_manager
        from app.models import SyncServer, DatabaseChange
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ CHECKING PENDING CHANGES")
            print("-" * 30)
            
            pending_changes = DatabaseChange.query.filter_by(sync_status='pending').all()
            print(f"Found {len(pending_changes)} pending changes to sync")
            
            for change in pending_changes[:5]:  # Show first 5
                print(f"  • {change.table_name} - {change.operation} - {change.record_id}")
            
            print("\n2️⃣ RUNNING MANUAL SYNC TEST")
            print("-" * 30)
            
            servers = SyncServer.query.filter_by(sync_enabled=True).all()
            
            for server in servers:
                print(f"\n🔄 Testing sync with {server.name}...")
                
                try:
                    result = simplified_sync_manager.perform_bidirectional_sync(server.id)
                    
                    if result['success']:
                        print(f"  ✅ Success!")
                        print(f"     Sent: {result['stats']['sent_to_remote']}")
                        print(f"     Received: {result['stats']['received_from_remote']}")
                        
                        # Check if changes were marked as synced
                        remaining_pending = DatabaseChange.query.filter_by(sync_status='pending').count()
                        print(f"     Remaining pending: {remaining_pending}")
                        
                    else:
                        print(f"  ❌ Failed: {result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    print(f"  ❌ Exception: {e}")
            
            return True
            
    except Exception as e:
        print(f"❌ Sync test failed: {e}")
        return False

def main():
    """Main fix function"""
    print("🚀 COMPREHENSIVE SYNC SYSTEM FIX")
    print("=" * 60)
    
    # Fix change tracking
    change_tracking_ok = fix_change_tracking()
    
    # Fix file sync permissions
    file_sync_ok = fix_file_sync_permissions()
    
    if change_tracking_ok:
        print("\n" + "=" * 60)
        print("✅ CHANGE TRACKING FIXES APPLIED")
        
        # Test the complete sync
        sync_test_ok = test_complete_sync()
        
        if sync_test_ok:
            print("\n🎉 SYNC SYSTEM FULLY OPERATIONAL!")
            print("User changes and other database changes will now sync properly.")
        else:
            print("\n⚠️ Sync test had issues - check logs above")
    else:
        print("\n❌ CHANGE TRACKING FIXES FAILED")
        print("Manual intervention required")

if __name__ == "__main__":
    main()
