#!/usr/bin/env python
"""Check what users exist on the remote server"""
from app import create_app
from app.models import SyncServer
import requests
import json

app = create_app()

def check_remote_users():
    with app.app_context():
        server = SyncServer.query.filter_by(sync_enabled=True).first()
        if not server:
            print("❌ No sync server found")
            return
            
        print(f"🔍 Checking users on remote server: {server.base_url}")
        
        # Try to get users from remote server
        # This would require an API endpoint on the remote server
        # Let's first check what endpoints are available
        
        # Check if there's a users API endpoint
        try:
            users_url = f"{server.base_url}/api/users"
            print(f"   Testing users endpoint: {users_url}")
            response = requests.get(users_url, timeout=10, verify=False)
            print(f"   Users response: {response.status_code}")
            if response.status_code == 200:
                users_data = response.json()
                print(f"   Found users: {len(users_data.get('users', []))}")
                for user in users_data.get('users', [])[:10]:
                    print(f"     - {user.get('username')} (id:{user.get('id')}, team:{user.get('scouting_team_number')})")
            else:
                print(f"   Users endpoint not available: {response.text}")
        except Exception as e:
            print(f"   ❌ Users endpoint error: {e}")
            
        # Check sync logs on remote server
        try:
            logs_url = f"{server.base_url}/api/sync/logs"
            print(f"   Testing sync logs: {logs_url}")
            response = requests.get(logs_url, timeout=10, verify=False)
            print(f"   Logs response: {response.status_code}")
            if response.status_code == 200:
                logs_data = response.json()
                print(f"   Recent sync logs:")
                for log in logs_data.get('logs', [])[:5]:
                    print(f"     - {log.get('timestamp')} {log.get('status')} items:{log.get('items_synced', 0)}")
            else:
                print(f"   Logs endpoint: {response.text}")
        except Exception as e:
            print(f"   ❌ Logs endpoint error: {e}")
            
        # Let's manually send our user changes again to see what happens
        from app.models import DatabaseChange
        from datetime import datetime, timedelta
        
        # Get recent user changes
        user_changes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.timestamp > datetime.utcnow() - timedelta(hours=1)
        ).all()
        
        if user_changes:
            print(f"\n📤 Sending {len(user_changes)} user changes to remote:")
            changes_data = [change.to_dict() for change in user_changes]
            
            for change in changes_data:
                print(f"   - {change['table']} {change['operation']} ID:{change['record_id']}")
                
            try:
                send_url = f"{server.base_url}/api/sync/receive-changes"
                payload = {
                    'changes': changes_data,
                    'server_id': 'local',
                    'timestamp': datetime.utcnow().isoformat()
                }
                response = requests.post(send_url, json=payload, timeout=30, verify=False)
                print(f"   Send response: {response.status_code}")
                if response.status_code == 200:
                    result = response.json()
                    print(f"   Applied: {result.get('applied_count', 0)}")
                    print(f"   Success: {result.get('success', False)}")
                    if 'warnings' in result:
                        print(f"   Warnings: {result['warnings']}")
                else:
                    print(f"   Send failed: {response.text}")
            except Exception as e:
                print(f"   ❌ Send error: {e}")

if __name__ == "__main__":
    check_remote_users()
