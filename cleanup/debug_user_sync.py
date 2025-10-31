#!/usr/bin/env python3
"""
Debug User Sync Issue
Check why user changes aren't syncing between servers
"""

def debug_user_sync():
    """Debug user synchronization issues"""
    print(" DEBUGGING USER SYNC ISSUE")
    print("=" * 50)
    
    try:
        from app import create_app, db
        from app.models import User, DatabaseChange, SyncServer, SyncLog
        from app.utils.simplified_sync import simplified_sync_manager
        from datetime import datetime, timezone, timedelta
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ CHECKING USER TABLE")
            print("-" * 30)
            
            users = User.query.all()
            print(f"Total users in database: {len(users)}")
            
            print("\nUsers:")
            for user in users[-10:]:  # Show last 10 users
                print(f"  • {user.username} (Team: {user.scouting_team_number}) - Created: {user.created_at}")
            
            print("\n2️⃣ CHECKING DATABASE CHANGES FOR USERS")
            print("-" * 30)
            
            # Check for user-related database changes
            user_changes = DatabaseChange.query.filter_by(table_name='user').order_by(DatabaseChange.timestamp.desc()).limit(10).all()
            
            print(f"Recent user changes in database: {len(user_changes)}")
            
            if user_changes:
                print("\nRecent user changes:")
                for change in user_changes:
                    print(f"  • {change.operation} - {change.record_id} - {change.timestamp} - Status: {change.sync_status}")
                    if change.change_data:
                        import json
                        try:
                            data = json.loads(change.change_data)
                            if 'username' in data:
                                print(f"    Username: {data['username']}")
                        except:
                            print(f"    Data: {change.change_data[:100]}...")
            else:
                print(" No user changes found in database_changes table!")
                print("This suggests change tracking may not be working for User model")
            
            print("\n3️⃣ TESTING CHANGE TRACKING")
            print("-" * 30)
            
            # Test if change tracking is enabled for User model
            try:
                from app.utils.change_tracking import track_change
                
                # Create a test user to verify change tracking
                test_user = User(
                    username=f'test_sync_user_{datetime.now().strftime("%H%M%S")}',
                    scouting_team_number=9999
                )
                test_user.set_password('test123')
                
                db.session.add(test_user)
                db.session.flush()  # Get the ID but don't commit yet
                
                print(f" Created test user: {test_user.username} (ID: {test_user.id})")
                
                # Check if a change was automatically tracked
                db.session.commit()
                
                # Wait a moment and check for the change
                import time
                time.sleep(1)
                
                new_change = DatabaseChange.query.filter_by(
                    table_name='user',
                    record_id=str(test_user.id)
                ).first()
                
                if new_change:
                    print(f" Change tracking is working - found change for new user")
                    print(f"   Change ID: {new_change.id}")
                    print(f"   Operation: {new_change.operation}")
                    print(f"   Status: {new_change.sync_status}")
                else:
                    print(" Change tracking is NOT working - no change recorded for new user")
                
            except Exception as e:
                print(f" Error testing change tracking: {e}")
            
            print("\n4️⃣ CHECKING SYNC SERVER STATUS")
            print("-" * 30)
            
            servers = SyncServer.query.all()
            for server in servers:
                print(f"Server: {server.name}")
                print(f"  URL: {server.protocol}://{server.host}:{server.port}")
                print(f"  Healthy: {server.is_healthy}")
                print(f"  Last sync: {server.last_sync}")
                print(f"  Sync enabled: {server.sync_enabled}")
            
            print("\n5️⃣ TESTING MANUAL SYNC")
            print("-" * 30)
            
            for server in servers:
                if server.sync_enabled:
                    print(f"\n Testing sync with {server.name}...")
                    
                    try:
                        result = simplified_sync_manager.perform_bidirectional_sync(server.id)
                        
                        print(f"  Success: {result['success']}")
                        if result['success']:
                            print(f"   Sent to remote: {result['stats']['sent_to_remote']}")
                            print(f"   Received from remote: {result['stats']['received_from_remote']}")
                            
                            # Check what was sent
                            for op in result['operations']:
                                if 'changes' in op.lower():
                                    print(f"    • {op}")
                        else:
                            print(f"   Error: {result.get('error', 'Unknown error')}")
                            
                    except Exception as e:
                        print(f"   Exception: {e}")
            
            print("\n6️⃣ CHECKING REMOTE SERVER USERS")
            print("-" * 30)
            
            # Try to get user list from remote server
            for server in servers:
                if server.sync_enabled and server.is_healthy:
                    try:
                        import requests
                        
                        # Try to ping the remote server API
                        url = f"{server.protocol}://{server.host}:{server.port}/api/sync/ping"
                        response = requests.get(url, timeout=5, verify=False)
                        
                        if response.status_code == 200:
                            print(f" Remote server {server.name} is responding")
                            
                            # Check if remote has changes to send back
                            since_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                            changes_url = f"{server.protocol}://{server.host}:{server.port}/api/sync/changes"
                            params = {'since': since_time, 'server_id': 'debug_test'}
                            
                            changes_response = requests.get(changes_url, params=params, timeout=10, verify=False)
                            if changes_response.status_code == 200:
                                changes_data = changes_response.json()
                                print(f"  Remote has {changes_data.get('count', 0)} changes available")
                                
                                # Show user changes specifically
                                user_changes_remote = [c for c in changes_data.get('changes', []) if c.get('table') == 'user']
                                print(f"  Remote has {len(user_changes_remote)} user changes")
                                
                                for change in user_changes_remote[:3]:
                                    print(f"    • {change.get('operation')} - {change.get('record_id')}")
                            else:
                                print(f"   Failed to get changes from remote: {changes_response.status_code}")
                        else:
                            print(f" Remote server {server.name} not responding: {response.status_code}")
                            
                    except Exception as e:
                        print(f" Error checking remote server {server.name}: {e}")
            
            print("\n7️⃣ RECOMMENDATIONS")
            print("-" * 30)
            
            user_changes_count = DatabaseChange.query.filter_by(table_name='user').count()
            pending_user_changes = DatabaseChange.query.filter_by(table_name='user', sync_status='pending').count()
            
            print(f"Total user changes in DB: {user_changes_count}")
            print(f"Pending user changes: {pending_user_changes}")
            
            if user_changes_count == 0:
                print("\n ISSUE: No user changes tracked")
                print("   Problem: Change tracking not working for User model")
                print("   Solution: Check change_tracking.py and User model setup")
            elif pending_user_changes == 0:
                print("\n️  ISSUE: All user changes marked as synced but not on remote")
                print("   Problem: Sync process not actually sending data")
                print("   Solution: Check sync API endpoints and data transmission")
            else:
                print("\n User changes are being tracked but not synced")
                print("   Problem: Sync process may be failing")
                print("   Solution: Check network connectivity and sync logs")
            
    except Exception as e:
        print(f" Debug failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_user_sync()
