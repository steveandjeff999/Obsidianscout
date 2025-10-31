#!/usr/bin/env python3
"""
Sync System Repair Script
Fixes critical sync issues and database problems
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

def repair_sync_system():
    """Main repair function"""
    print(" SYNC SYSTEM REPAIR UTILITY")
    print("=" * 50)
    
    try:
        # Import Flask app and models
        from app import create_app, db
        from app.models import SyncServer, SyncLog, DatabaseChange
        
        app = create_app()
        
        with app.app_context():
            
            print("\n1️⃣ TESTING DATABASE CONNECTION")
            print("-" * 30)
            try:
                # Test basic database connection
                server_count = SyncServer.query.count()
                print(f" Database connected - {server_count} sync servers configured")
                
                # Test DatabaseChange table
                change_count = DatabaseChange.query.count()
                print(f" DatabaseChange table accessible - {change_count} changes recorded")
                
            except Exception as e:
                print(f" Database connection failed: {e}")
                return False
                
            print("\n2️⃣ CHECKING SYNC SERVERS")
            print("-" * 30)
            servers = SyncServer.query.filter_by(sync_enabled=True).all()
            
            for server in servers:
                print(f"\n️  Server: {server.name} ({server.host}:{server.port})")
                print(f"   Protocol: {server.protocol}")
                print(f"   Active: {server.is_active}")
                print(f"   Last Ping: {server.last_ping}")
                print(f"   Error Count: {server.error_count}")
                print(f"   Healthy: {server.is_healthy}")
                
                # Test connectivity
                try:
                    url = f"{server.protocol}://{server.host}:{server.port}/api/sync/ping"
                    response = requests.get(url, timeout=5, verify=False)
                    if response.status_code == 200:
                        print(f"   OK Connection: SUCCESS")
                        # Update ping status
                        server.update_ping(success=True)
                    else:
                        print(f"    Connection: FAILED (HTTP {response.status_code})")
                        server.update_ping(success=False, error_message=f"HTTP {response.status_code}")
                except Exception as e:
                    print(f"    Connection: FAILED ({str(e)})")
                    server.update_ping(success=False, error_message=str(e))
            
            # Commit ping updates
            db.session.commit()
            
            print("\n3. CLEANING SYNC LOGS")
            print("-" * 30)
            
            # Clean up old malformed sync logs
            problematic_logs = SyncLog.query.filter(
                SyncLog.sync_details.like('File: %')
            ).all()
            
            print(f"Found {len(problematic_logs)} sync logs with malformed JSON")
            
            for log in problematic_logs:
                if log.sync_details and log.sync_details.startswith('File: '):
                    # Extract file path and convert to proper JSON
                    file_path = log.sync_details.replace('File: ', '')
                    log.sync_details = json.dumps({
                        'file_path': file_path,
                        'repaired': True,
                        'repair_date': datetime.now(timezone.utc).isoformat()
                    })
            
            db.session.commit()
            print(f" Repaired {len(problematic_logs)} sync log entries")
            
            print("\n4. TESTING SYNC API ENDPOINTS")
            print("-" * 30)
            
            for server in servers:
                if server.is_active:
                    print(f"\n Testing {server.name}...")
                    
                    # Test ping endpoint
                    try:
                        url = f"{server.protocol}://{server.host}:{server.port}/api/sync/ping"
                        response = requests.get(url, timeout=5, verify=False)
                        print(f"   Ping: {response.status_code}")
                    except Exception as e:
                        print(f"   Ping: FAILED - {e}")
                    
                    # Test changes endpoint
                    try:
                        since_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                        url = f"{server.protocol}://{server.host}:{server.port}/api/sync/changes"
                        params = {'since': since_time, 'server_id': 'repair_test'}
                        response = requests.get(url, params=params, timeout=10, verify=False)
                        print(f"   Changes: {response.status_code}")
                        if response.status_code == 200:
                            data = response.json()
                            print(f"   Available changes: {data.get('count', 0)}")
                    except Exception as e:
                        print(f"   Changes: FAILED - {e}")
            
            print("\n5. CREATING TEST DATABASE CHANGES")
            print("-" * 30)
            
            # Create some test database changes to ensure sync has data
            try:
                from app.utils.change_tracking import track_change
                
                # Create a test change
                test_change = DatabaseChange(
                    table_name='sync_test',
                    operation='test_repair',
                    timestamp=datetime.now(timezone.utc),
                    sync_status='pending',
                    data_hash='repair_test_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                )
                db.session.add(test_change)
                db.session.commit()
                
                print(" Created test database change for sync")
                
            except Exception as e:
                print(f"ERROR Could not create test change: {e}")
            
            print("\n6. SUMMARY AND RECOMMENDATIONS")
            print("-" * 30)
            
            healthy_servers = [s for s in servers if s.is_healthy]
            print(f" {len(healthy_servers)}/{len(servers)} servers are healthy")
            
            if len(healthy_servers) == 0:
                print(" NO HEALTHY SERVERS - Sync will not work")
                print("   Check network connectivity and server status")
            elif len(healthy_servers) < len(servers):
                print("🟡 Some servers are unhealthy - partial sync only")
                unhealthy = [s for s in servers if not s.is_healthy]
                for server in unhealthy:
                    print(f"   - {server.name}: {server.last_error or 'Unknown error'}")
            else:
                print("🟢 All servers healthy - sync should work normally")
            
            return True
            
    except Exception as e:
        print(f" Repair failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_manual_sync():
    """Test a manual sync operation"""
    print("\n TESTING MANUAL SYNC")
    print("=" * 50)
    
    try:
        from app import create_app
        from app.utils.simplified_sync import simplified_sync_manager
        from app.models import SyncServer
        
        app = create_app()
        
        with app.app_context():
            servers = SyncServer.query.filter_by(sync_enabled=True, is_active=True).all()
            
            if not servers:
                print(" No active sync servers found")
                return False
            
            for server in servers:
                print(f"\n Testing sync with {server.name}...")
                
                try:
                    result = simplified_sync_manager.perform_bidirectional_sync(server.id)
                    
                    if result['success']:
                        print(f" Sync successful!")
                        print(f"   Sent: {result['stats']['sent_to_remote']}")
                        print(f"   Received: {result['stats']['received_from_remote']}")
                        print(f"   Operations: {len(result['operations'])}")
                    else:
                        print(f" Sync failed: {result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    print(f" Sync exception: {e}")
            
            return True
            
    except Exception as e:
        print(f" Manual sync test failed: {e}")
        return False

def main():
    """Main function"""
    print(" STARTING SYNC SYSTEM REPAIR")
    print("=" * 60)
    
    # Run repairs
    repair_success = repair_sync_system()
    
    if repair_success:
        print("\n" + "=" * 60)
        print(" REPAIR COMPLETED SUCCESSFULLY")
        print("=" * 60)
        
        # Test sync functionality
        test_manual_sync()
        
        print("\n NEXT STEPS:")
        print("1. Restart the application: python run.py")
        print("2. Check console for auto-sync messages")
        print("3. Try manual sync from web interface")
        print("4. Monitor sync logs for errors")
        
    else:
        print("\n REPAIR FAILED")
        print("Check the error messages above and fix issues manually")

if __name__ == "__main__":
    main()
