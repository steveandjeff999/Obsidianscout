#!/usr/bin/env python3
"""
Test Server Addition
"""
import os
from app import create_app

# Create Flask app
app = create_app()

with app.app_context():
    print("🔄 Testing Server Addition Fix")
    print("============================================================")
    
    # Import the sync manager from the route
    from app.routes.sync_management import sync_manager
    
    print("Testing FallbackSyncManager.add_sync_server with user_id parameter...")
    
    try:
        # Test the method that was failing
        test_server = sync_manager.add_sync_server(
            name="Test Server",
            host="test.example.com",
            port=5000,
            protocol="https",
            user_id=1  # This was causing the error
        )
        
        if test_server:
            print(f"✅ Server added successfully: {test_server.name} ({test_server.host}:{test_server.port})")
            print(f"Server ID: {test_server.id}")
            print(f"Active: {test_server.is_active}")
            print(f"Sync Enabled: {test_server.sync_enabled}")
            
            # Clean up - remove the test server
            from app.models import SyncServer
            from app import db
            SyncServer.query.filter_by(id=test_server.id).delete()
            db.session.commit()
            print("✅ Test server cleaned up")
            
        else:
            print("❌ Server creation returned None")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("\n============================================================")
    print("🎉 SERVER ADDITION TEST COMPLETED")
