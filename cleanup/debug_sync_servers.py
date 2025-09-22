#!/usr/bin/env python3
"""
Debug sync server configuration
"""
import os
import sys
from pathlib import Path

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

try:
    from app import create_app, db
    from app.models import SyncServer
    
    app = create_app()
    with app.app_context():
        servers = SyncServer.query.all()
        
        if servers:
            print(f"🔍 Current Sync Server Configuration:")
            for server in servers:
                print(f"")
                print(f"Server: {server.name}")
                print(f"  Host: {server.host}")
                print(f"  Port: {server.port}")
                print(f"  Protocol: {server.protocol}")
                print(f"  Base URL: {server.base_url}")
                print(f"  Update URL: {server.base_url}/api/sync/update")
                print(f"  Is Active: {server.is_active}")
                print(f"  Sync Enabled: {server.sync_enabled}")
                print(f"  Last Error: {server.last_error}")
                print(f"  Error Count: {server.error_count}")
        else:
            print("❌ No sync servers found")
            
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
