#!/usr/bin/env python3
"""
Comprehensive Server Configuration Test
"""

def test_all_configs():
    """Test all possible server configurations"""
    print(" COMPREHENSIVE SERVER CONFIG TEST")
    print("=" * 50)
    
    import requests
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
    host = "192.168.1.187"
    test_configs = [
        ("http", 5000),
        ("https", 5000), 
        ("http", 8080),
        ("https", 8080),
        ("http", 8081),
        ("https", 8081),
        ("http", 80),
        ("https", 443),
        ("http", 443),  # The one that was found
    ]
    
    working_configs = []
    
    print(f"Testing {host} on different ports and protocols...\n")
    
    for protocol, port in test_configs:
        try:
            url = f"{protocol}://{host}:{port}/api/sync/ping"
            print(f"Testing {protocol}://{host}:{port}...")
            
            response = requests.get(url, timeout=5, verify=False)
            if response.status_code == 200:
                data = response.json()
                print(f"   SUCCESS - Status: {data.get('status', 'unknown')}")
                working_configs.append((protocol, port, data))
            else:
                print(f"   HTTP {response.status_code}")
                
        except requests.exceptions.ConnectTimeout:
            print(f"  ⏰ Connection timeout")
        except requests.exceptions.ConnectionError as e:
            if "Connection refused" in str(e):
                print(f"   Connection refused")
            else:
                print(f"   Connection error")
        except Exception as e:
            print(f"   Error: {type(e).__name__}")
    
    print(f"\n SUMMARY:")
    print(f"Found {len(working_configs)} working configurations:")
    
    for protocol, port, data in working_configs:
        print(f"   {protocol}://{host}:{port}")
        print(f"     Server ID: {data.get('server_id', 'unknown')}")
        print(f"     Version: {data.get('version', 'unknown')}")
        print("")
    
    if working_configs:
        # Update the database with the best configuration
        try:
            from app import create_app, db
            from app.models import SyncServer
            
            app = create_app()
            
            with app.app_context():
                server = SyncServer.query.first()
                if server:
                    # Use the first working config (usually the most standard)
                    protocol, port, data = working_configs[0]
                    
                    print(f" UPDATING DATABASE:")
                    print(f"   Setting server to {protocol}://{host}:{port}")
                    
                    server.protocol = protocol
                    server.port = port
                    server.error_count = 0
                    server.update_ping(success=True)
                    db.session.commit()
                    
                    print(f"    Database updated successfully")
                    
        except Exception as e:
            print(f" Failed to update database: {e}")
    else:
        print(" No working configurations found!")
        print(" Make sure the remote server is running and accessible")

if __name__ == "__main__":
    test_all_configs()
