#!/usr/bin/env python3
"""
Enhanced sync server update utility
Ensures sync server lists are preserved during updates
"""
import os
import sys
from pathlib import Path
import json
import sqlite3
from datetime import datetime

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def backup_sync_server_config():
    """Backup sync server configuration before update"""
    try:
        from app import create_app, db
        from app.models import SyncServer, SyncConfig
        
        app = create_app()
        with app.app_context():
            # Get all sync servers
            servers = SyncServer.query.all()
            server_data = [server.to_dict() for server in servers]
            
            # Get sync configuration
            config_data = {}
            configs = SyncConfig.query.all()
            for config in configs:
                config_data[config.key] = {
                    'value': config.value,
                    'data_type': config.data_type,
                    'description': config.description
                }
            
            backup_data = {
                'servers': server_data,
                'config': config_data,
                'backup_time': datetime.utcnow().isoformat()
            }
            
            # Save to instance folder
            instance_dir = Path('instance')
            instance_dir.mkdir(exist_ok=True)
            
            backup_file = instance_dir / 'sync_config_backup.json'
            with open(backup_file, 'w') as f:
                json.dump(backup_data, f, indent=2)
            
            print(f"✅ Sync server configuration backed up to {backup_file}")
            print(f"   - {len(server_data)} servers backed up")
            print(f"   - {len(config_data)} config items backed up")
            return str(backup_file)
            
    except Exception as e:
        print(f"❌ Error backing up sync server config: {e}")
        return None

def verify_sync_server_preservation():
    """Verify that sync server configuration is preserved"""
    try:
        from app import create_app, db
        from app.models import SyncServer
        
        app = create_app()
        with app.app_context():
            servers = SyncServer.query.all()
            
            if servers:
                print(f"✅ Sync server configuration preserved:")
                for server in servers:
                    status = "🟢 Healthy" if server.is_healthy else "🟡 Unhealthy"
                    print(f"   - {server.name} ({server.host}:{server.port}) - {status}")
                return True
            else:
                print("⚠️  No sync servers found after update")
                
                # Check if backup exists
                backup_file = Path('instance') / 'sync_config_backup.json'
                if backup_file.exists():
                    print("📁 Sync config backup found - servers can be restored if needed")
                
                return False
                
    except Exception as e:
        print(f"❌ Error verifying sync server preservation: {e}")
        return False

def restore_sync_server_config():
    """Restore sync server configuration from backup if needed"""
    try:
        backup_file = Path('instance') / 'sync_config_backup.json'
        if not backup_file.exists():
            print("❌ No sync config backup found")
            return False
        
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
        
        from app import create_app, db
        from app.models import SyncServer, SyncConfig
        
        app = create_app()
        with app.app_context():
            # Restore servers
            servers_restored = 0
            for server_dict in backup_data.get('servers', []):
                # Check if server already exists
                existing = SyncServer.query.filter_by(
                    host=server_dict['host'],
                    port=server_dict['port']
                ).first()
                
                if not existing:
                    # Create new server (excluding the ID)
                    server_data = {k: v for k, v in server_dict.items() 
                                 if k not in ['id', 'base_url', 'is_healthy']}
                    server = SyncServer(**server_data)
                    db.session.add(server)
                    servers_restored += 1
            
            # Restore config
            configs_restored = 0
            for key, config_dict in backup_data.get('config', {}).items():
                SyncConfig.set_value(
                    key=key,
                    value=config_dict['value'],
                    data_type=config_dict['data_type'],
                    description=config_dict.get('description')
                )
                configs_restored += 1
            
            db.session.commit()
            
            print(f"✅ Sync server configuration restored:")
            print(f"   - {servers_restored} servers restored")
            print(f"   - {configs_restored} config items restored")
            return True
            
    except Exception as e:
        print(f"❌ Error restoring sync server config: {e}")
        return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Manage sync server configuration during updates')
    parser.add_argument('--backup', action='store_true', help='Backup sync server configuration')
    parser.add_argument('--verify', action='store_true', help='Verify sync server preservation')
    parser.add_argument('--restore', action='store_true', help='Restore sync server configuration')
    
    args = parser.parse_args()
    
    if args.backup:
        backup_sync_server_config()
    elif args.verify:
        verify_sync_server_preservation()
    elif args.restore:
        restore_sync_server_config()
    else:
        print("Usage:")
        print("  python sync_config_manager.py --backup   # Backup sync config")
        print("  python sync_config_manager.py --verify   # Verify preservation")
        print("  python sync_config_manager.py --restore  # Restore from backup")
