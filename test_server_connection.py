#!/usr/bin/env python3
"""
Test connection to sync servers
"""
import os
import sys
import requests
import urllib3
from pathlib import Path

# Disable SSL warnings for testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def test_server_connection(server):
    """Test various endpoints on a server"""
    print(f"\n🔍 Testing connection to {server.name} ({server.base_url})")
    
    # Test basic ping endpoint
    try:
        ping_url = f"{server.base_url}/api/sync/ping"
        print(f"Testing ping: {ping_url}")
        resp = requests.get(ping_url, timeout=10, verify=False)
        print(f"  ✅ Ping successful: HTTP {resp.status_code}")
        if resp.headers.get('content-type', '').startswith('application/json'):
            print(f"  📄 Response: {resp.json()}")
        else:
            print(f"  📄 Response (text): {resp.text[:200]}...")
    except Exception as e:
        print(f"  ❌ Ping failed: {e}")
    
    # Test update endpoint with test payload
    try:
        update_url = f"{server.base_url}/api/sync/update"
        print(f"Testing update endpoint: {update_url}")
        test_payload = {
            'zip_url': 'https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip',
            'use_waitress': True,
            'port': server.port
        }
        resp = requests.post(update_url, json=test_payload, timeout=10, verify=False)
        print(f"  ✅ Update endpoint accessible: HTTP {resp.status_code}")
        if resp.headers.get('content-type', '').startswith('application/json'):
            print(f"  📄 Response: {resp.json()}")
        else:
            print(f"  📄 Response (text): {resp.text[:200]}...")
    except Exception as e:
        print(f"  ❌ Update endpoint failed: {e}")

try:
    from app import create_app, db
    from app.models import SyncServer
    
    app = create_app()
    with app.app_context():
        servers = SyncServer.query.all()
        
        if servers:
            print(f"🔗 Testing connections to {len(servers)} server(s):")
            for server in servers:
                test_server_connection(server)
        else:
            print("❌ No sync servers found")
            
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
