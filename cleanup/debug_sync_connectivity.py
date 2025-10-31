#!/usr/bin/env python
"""Debug sync connectivity and remote server status"""
from app import create_app
from app.models import SyncServer, DatabaseChange
import requests
import json
from datetime import datetime, timezone, timedelta

app = create_app()

def test_remote_connectivity():
    with app.app_context():
        servers = SyncServer.query.filter_by(sync_enabled=True).all()
        print(f"Found {len(servers)} sync-enabled servers:")
        
        for server in servers:
            print(f"\n Testing server: {server.name}")
            print(f"   URL: {server.base_url}")
            print(f"   Sync enabled: {server.sync_enabled}")
            print(f"   Sync database: {server.sync_database}")
            print(f"   Last sync: {server.last_sync}")
            print(f"   Last ping: {server.last_ping}")
            
            # Test ping endpoint
            try:
                ping_url = f"{server.base_url}/api/sync/ping"
                print(f"   Testing ping: {ping_url}")
                response = requests.get(ping_url, timeout=10, verify=False)
                print(f"   Ping response: {response.status_code}")
                if response.status_code == 200:
                    print(f"   Ping data: {response.json()}")
                else:
                    print(f"   Ping failed: {response.text}")
            except Exception as e:
                print(f"    Ping error: {e}")
                
            # Test changes endpoint
            try:
                changes_url = f"{server.base_url}/api/sync/changes"
                since_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                params = {'since': since_time, 'server_id': 'local'}
                print(f"   Testing changes: {changes_url}")
                response = requests.get(changes_url, params=params, timeout=10, verify=False)
                print(f"   Changes response: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    print(f"   Remote changes count: {data.get('count', 0)}")
                    changes = data.get('changes', [])
                    for change in changes[:3]:  # Show first 3
                        print(f"     - {change.get('table')} {change.get('operation')} ID:{change.get('record_id')}")
                else:
                    print(f"   Changes failed: {response.text}")
            except Exception as e:
                print(f"    Changes error: {e}")
                
            # Test receive-changes endpoint
            try:
                receive_url = f"{server.base_url}/api/sync/receive-changes"
                test_payload = {
                    'changes': [],
                    'server_id': 'local',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                print(f"   Testing receive-changes: {receive_url}")
                response = requests.post(receive_url, json=test_payload, timeout=10, verify=False)
                print(f"   Receive response: {response.status_code}")
                if response.status_code == 200:
                    print(f"   Receive data: {response.json()}")
                else:
                    print(f"   Receive failed: {response.text}")
            except Exception as e:
                print(f"    Receive error: {e}")
                
        # Check local pending changes
        pending_changes = DatabaseChange.query.filter_by(sync_status='pending').all()
        print(f"\n Local pending changes: {len(pending_changes)}")
        for change in pending_changes:
            print(f"   - ID:{change.id} {change.table_name} {change.operation} rec:{change.record_id} created:{change.timestamp}")
            
        # Check recently synced changes
        synced_changes = DatabaseChange.query.filter_by(sync_status='synced').order_by(DatabaseChange.timestamp.desc()).limit(10).all()
        print(f"\n Recently synced changes: {len(synced_changes)}")
        for change in synced_changes:
            print(f"   - ID:{change.id} {change.table_name} {change.operation} rec:{change.record_id} synced")

if __name__ == "__main__":
    test_remote_connectivity()
