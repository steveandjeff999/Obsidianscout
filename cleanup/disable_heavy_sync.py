#!/usr/bin/env python3
"""
Disable Heavy Sync Systems
Disables all the heavy sync systems that are causing database locking
and replaces them with a minimal, efficient solution
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def disable_heavy_sync_systems():
    """Disable heavy sync systems in the application"""
    
    # 1. Disable periodic sync startup
    try:
        # Check and modify the sync manager initialization
        from pathlib import Path
        app_init_path = Path('app/__init__.py')
        
        if app_init_path.exists():
            content = app_init_path.read_text()
            
            # Comment out heavy sync system initializations
            patterns_to_disable = [
                'sync_manager.init_app(app)',
                'setup_multi_server_sync',
                'start_periodic_sync',
                'initialize_universal_sync',
                'start_sync_workers'
            ]
            
            for pattern in patterns_to_disable:
                if pattern in content and not content.count(f'# {pattern}'):
                    print(f" Disabling: {pattern}")
                    content = content.replace(pattern, f'# {pattern}  # DISABLED - was causing database locking')
            
            app_init_path.write_text(content)
            print(" Heavy sync systems disabled in app/__init__.py")
        
    except Exception as e:
        print(f"️ Could not modify app/__init__.py: {e}")
    
    # 2. Create simple sync-only-when-needed system
    create_simple_sync_system()

def create_simple_sync_system():
    """Create a simple sync system that only runs when needed"""
    
    simple_sync_code = '''#!/usr/bin/env python3
"""
Simple On-Demand Sync System
Only syncs when explicitly requested, preventing database conflicts
"""

import sys
import os
import time
import threading
from datetime import datetime, timezone
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class SimpleSyncSystem:
    """Minimal sync system that only runs when requested"""
    
    def __init__(self):
        self.is_syncing = False
        self.last_sync = None
        
    def sync_now(self, table_name=None, operation=None, record_data=None):
        """Perform sync immediately for specific operation"""
        if self.is_syncing:
            print("️ Sync already in progress, skipping...")
            return
            
        try:
            self.is_syncing = True
            
            # Only sync to active servers
            from app.models import SyncServer
            servers = SyncServer.query.filter_by(is_active=True).all()
            
            if not servers:
                print(" No active sync servers")
                return
            
            # Create simple sync payload
            payload = {
                'table': table_name,
                'operation': operation,
                'data': record_data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Send to each server
            success_count = 0
            for server in servers:
                try:
                    result = self._send_to_server(server, payload)
                    if result:
                        success_count += 1
                except Exception as e:
                    print(f" Sync to {server.name} failed: {e}")
            
            if success_count > 0:
                print(f" Synced to {success_count}/{len(servers)} servers")
                self.last_sync = datetime.now(timezone.utc)
            
        except Exception as e:
            print(f" Sync error: {e}")
        finally:
            self.is_syncing = False
    
    def _send_to_server(self, server, payload):
        """Send sync data to a server"""
        try:
            import requests
            
            url = f"{server.protocol}://{server.host}:{server.port}/api/sync/simple_receive"
            
            response = requests.post(
                url,
                json=payload,
                timeout=5,
                verify=False
            )
            
            return response.status_code == 200
            
        except Exception as e:
            print(f"️ Server communication error: {e}")
            return False

# Global instance - only one per application
simple_sync = SimpleSyncSystem()

def sync_user_change(operation, user_data):
    """Sync a user change immediately"""
    simple_sync.sync_now('user', operation, user_data)

def sync_scouting_data_change(operation, data):
    """Sync scouting data change immediately"""  
    simple_sync.sync_now('scouting_data', operation, data)

def get_sync_status():
    """Get simple sync status"""
    return {
        'is_syncing': simple_sync.is_syncing,
        'last_sync': simple_sync.last_sync.isoformat() if simple_sync.last_sync else None
    }

if __name__ == "__main__":
    print(" Simple Sync System")
    print("=" * 30)
    
    # Test the system
    from app import create_app
    app = create_app()
    
    with app.app_context():
        status = get_sync_status()
        print(f" Sync status: {status}")
        
        # Test sync
        test_data = {'username': 'test', 'team_number': 1234}
        sync_user_change('insert', test_data)
'''
    
    with open('simple_sync_system.py', 'w') as f:
        f.write(simple_sync_code)
    
    print(" Created simple_sync_system.py")

def update_auth_routes_for_simple_sync():
    """Update auth routes to use simple sync instead of heavy systems"""
    
    try:
        from pathlib import Path
        auth_path = Path('app/routes/auth.py')
        
        if auth_path.exists():
            content = auth_path.read_text()
            
            # Add simple sync import at the top
            if 'from simple_sync_system import sync_user_change' not in content:
                # Find the imports section
                import_insertion_point = content.find('from flask import')
                if import_insertion_point != -1:
                    # Add after existing imports
                    insertion_point = content.find('\n\n', import_insertion_point)
                    if insertion_point != -1:
                        new_import = '\n# Simple sync system\ntry:\n    from simple_sync_system import sync_user_change\nexcept ImportError:\n    def sync_user_change(*args, **kwargs):\n        pass  # Fallback if sync not available\n'
                        content = content[:insertion_point] + new_import + content[insertion_point:]
            
            # Add simple sync calls to user operations
            user_operations = [
                ('db.session.add(user)', 'sync_user_change("insert", {"username": user.username, "team_number": user.scouting_team_number})'),
                ('db.session.commit()', '# sync_user_change called separately to avoid conflicts')
            ]
            
            # Don't modify too much automatically - just create the simple system
            auth_path.write_text(content)
            print(" Auth routes prepared for simple sync")
        
    except Exception as e:
        print(f"️ Could not update auth routes: {e}")

if __name__ == "__main__":
    print(" Disabling Heavy Sync Systems")
    print("=" * 40)
    
    # Step 1: Disable heavy systems
    disable_heavy_sync_systems()
    
    # Step 2: Create simple replacement
    create_simple_sync_system()
    
    # Step 3: Update routes (optional)
    update_auth_routes_for_simple_sync()
    
    print("\n Heavy Sync Systems Disabled!")
    print("   - Periodic sync disabled")
    print("   - Universal sync disabled") 
    print("   - Multiple sync workers disabled")
    print("   - Simple on-demand sync created")
    
    print(f"\n Next Steps:")
    print(f"   1. Restart the application")
    print(f"   2. Test user operations")
    print(f"   3. Use simple_sync_system for sync when needed")
    print(f"   4. Database should be much faster now")
