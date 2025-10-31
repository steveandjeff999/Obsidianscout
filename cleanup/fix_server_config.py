#!/usr/bin/env python3
"""
Quick Fix for Sync Server Configuration
"""

def fix_server_config():
    """Fix the sync server configuration"""
    print(" FIXING SYNC SERVER CONFIGURATION")
    print("=" * 50)
    
    try:
        from app import create_app, db
        from app.models import SyncServer
        
        app = create_app()
        
        with app.app_context():
            servers = SyncServer.query.all()
            
            for server in servers:
                print(f"\n️  Server: {server.name}")
                print(f"   Current: {server.protocol}://{server.host}:{server.port}")
                
                # Common port configurations for scouting apps
                common_ports = [5000, 8080, 8081, 80, 443]
                
                print(f"   Testing common ports...")
                
                import requests
                working_config = None
                
                for port in common_ports:
                    for protocol in ['http', 'https']:
                        try:
                            url = f"{protocol}://{server.host}:{port}/api/sync/ping"
                            response = requests.get(url, timeout=3, verify=False)
                            if response.status_code == 200:
                                working_config = (protocol, port)
                                print(f"    FOUND: {protocol}://{server.host}:{port}")
                                break
                        except:
                            continue
                    if working_config:
                        break
                
                if working_config:
                    protocol, port = working_config
                    print(f"    Updating server configuration...")
                    server.protocol = protocol  
                    server.port = port
                    server.error_count = 0
                    server.update_ping(success=True)
                    
                    db.session.commit()
                    print(f"    Updated to {protocol}://{server.host}:{port}")
                else:
                    print(f"    No working configuration found")
                    print(f"    Make sure the remote server is running and accessible")
            
    except Exception as e:
        print(f" Configuration fix failed: {e}")

if __name__ == "__main__":
    fix_server_config()
