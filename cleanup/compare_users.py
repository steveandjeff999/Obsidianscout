#!/usr/bin/env python
"""Check users on both local and remote servers"""
from app import create_app
from app.models import SyncServer, User
import requests
import json

app = create_app()

def compare_users():
    with app.app_context():
        print("=== LOCAL USERS ===")
        local_users = User.query.all()
        print(f"Total local users: {len(local_users)}")
        
        for user in local_users:
            status = "ACTIVE" if user.is_active else "INACTIVE"
            print(f"  - {user.username} (ID:{user.id}, Team:{user.scouting_team_number}) [{status}]")
        
        # Get remote server info
        server = SyncServer.query.filter_by(sync_enabled=True).first()
        if not server:
            print("❌ No sync server configured")
            return
            
        print(f"\n=== REMOTE USERS ON {server.name} ===")
        print(f"Remote server: {server.base_url}")
        
        # Try to get users from remote via a custom API call
        # Since there might not be a standard users API, let's send a request to get database info
        try:
            # Try the sync changes endpoint to see what user records exist on remote
            from datetime import datetime, timezone, timedelta
            since_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()  # Last 30 days
            
            changes_url = f"{server.base_url}/api/sync/changes"
            params = {'since': since_time, 'server_id': 'local'}
            response = requests.get(changes_url, params=params, timeout=10, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                changes = data.get('changes', [])
                user_changes = [c for c in changes if c.get('table') == 'user']
                
                print(f"Found {len(user_changes)} user-related changes on remote:")
                
                # Extract user info from changes
                remote_users = {}
                for change in user_changes:
                    record_id = change.get('record_id')
                    operation = change.get('operation')
                    change_data = change.get('data', {})
                    
                    if record_id not in remote_users:
                        remote_users[record_id] = {
                            'id': record_id,
                            'username': 'Unknown',
                            'team': 'Unknown',
                            'is_active': True,
                            'operations': []
                        }
                    
                    remote_users[record_id]['operations'].append(operation)
                    
                    if change_data:
                        remote_users[record_id]['username'] = change_data.get('username', remote_users[record_id]['username'])
                        remote_users[record_id]['team'] = change_data.get('scouting_team_number', remote_users[record_id]['team'])
                        if 'is_active' in change_data:
                            remote_users[record_id]['is_active'] = change_data['is_active']
                
                for user_id, user_info in remote_users.items():
                    status = "ACTIVE" if user_info['is_active'] else "INACTIVE"
                    ops = ", ".join(user_info['operations'])
                    print(f"  - {user_info['username']} (ID:{user_id}, Team:{user_info['team']}) [{status}] - Ops: {ops}")
                    
            else:
                print(f"❌ Could not get remote changes: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error checking remote: {e}")
            
        print(f"\n=== COMPARISON ===")
        print("If sync is working, you should see the same users on both servers.")
        print("Note: Remote users are inferred from sync changes, not direct user queries.")
        print("\nTo verify sync is working:")
        print("1. Check the user management page on the remote server")
        print("2. Look for test users like 'sync_test_user_*'")
        print("3. Verify inactive/deleted users show up correctly")

if __name__ == "__main__":
    compare_users()
