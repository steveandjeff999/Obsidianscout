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
from datetime import datetime, timezone

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def backup_sync_server_config():
    """Backup sync server configuration before update using direct DB access"""
    try:
        # Use direct SQLite connection to avoid Flask app circular imports
        db_path = Path('instance/database.db')
        if not db_path.exists():
            print("Database not found - no sync config to backup")
            return
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if sync_servers table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_servers'")
        if not cursor.fetchone():
            print("No sync_servers table found - no sync config to backup")
            conn.close()
            return
        
        # Get all sync servers
        cursor.execute("SELECT * FROM sync_servers")
        server_rows = cursor.fetchall()
        
        # Get column names
        cursor.execute("PRAGMA table_info(sync_servers)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Convert to dictionaries
        server_data = []
        for row in server_rows:
            server_dict = dict(zip(columns, row))
            server_data.append(server_dict)
        
        # Get sync configuration if table exists
        config_data = {}
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_config'")
        if cursor.fetchone():
            cursor.execute("SELECT * FROM sync_config")
            config_rows = cursor.fetchall()
            
            cursor.execute("PRAGMA table_info(sync_config)")
            config_columns = [row[1] for row in cursor.fetchall()]
            
            for row in config_rows:
                config_dict = dict(zip(config_columns, row))
                config_data[config_dict.get('key', 'unknown')] = config_dict.get('value', '')
        
        conn.close()
        
        backup_data = {
            'servers': server_data,
            'config': config_data,
            'backup_time': datetime.now(timezone.utc).isoformat()
        }
        
        # Save to instance folder
        instance_dir = Path('instance')
        instance_dir.mkdir(exist_ok=True)
        
        backup_file = instance_dir / 'sync_config_backup.json'
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=2)
        
        print(f"SUCCESS: Sync server configuration backed up to {backup_file}")
        print(f"   - {len(server_data)} servers backed up")
        print(f"   - {len(config_data)} config items backed up")
        return str(backup_file)
            
    except Exception as e:
        print(f"Error backing up sync server config: {e}")
        return None

def verify_sync_server_preservation():
    """Verify that sync server configuration is preserved using direct DB access"""
    try:
        # Use direct SQLite connection to avoid Flask app circular imports
        db_path = Path('instance/database.db')
        if not db_path.exists():
            print("Database not found - cannot verify sync config")
            return False
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if sync_servers table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_servers'")
        if not cursor.fetchone():
            print("No sync_servers table found")
            conn.close()
            return False
        
        # Get all sync servers
        cursor.execute("SELECT * FROM sync_servers")
        server_rows = cursor.fetchall()
        
        # Get column names
        cursor.execute("PRAGMA table_info(sync_servers)")
        columns = [row[1] for row in cursor.fetchall()]
        
        conn.close()
        
        if server_rows:
            print(f"SUCCESS: Sync server configuration preserved:")
            for row in server_rows:
                server_dict = dict(zip(columns, row))
                name = server_dict.get('name', 'Unknown')
                host = server_dict.get('host', 'Unknown')
                port = server_dict.get('port', 'Unknown')
                is_healthy = server_dict.get('is_healthy', False)
                status = "Healthy" if is_healthy else "Unhealthy"
                print(f"   - {name} ({host}:{port}) - {status}")
            return True
        else:
            print("No sync servers found after update")
            
            # Check if backup exists
            backup_file = Path('instance') / 'sync_config_backup.json'
            if backup_file.exists():
                print("Sync config backup found - servers can be restored if needed")
            else:
                print("No sync config backup found")
            
            return False
                
    except Exception as e:
        print(f"Error verifying sync server preservation: {e}")
        return False

def restore_sync_server_config():
    """Restore sync server configuration from backup if needed using direct DB access"""
    try:
        backup_file = Path('instance') / 'sync_config_backup.json'
        if not backup_file.exists():
            print("No sync config backup found")
            return False
        
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
        
        # Use direct SQLite connection to avoid Flask app circular imports
        db_path = Path('instance/database.db')
        if not db_path.exists():
            print("Database not found - cannot restore sync config")
            return False
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Restore servers
        servers_restored = 0
        for server_dict in backup_data.get('servers', []):
            # Check if server already exists
            cursor.execute("SELECT id FROM sync_servers WHERE host = ? AND port = ?", 
                         (server_dict['host'], server_dict['port']))
            existing = cursor.fetchone()
            
            if not existing:
                # Create new server (excluding the ID)
                columns = [k for k in server_dict.keys() if k not in ['id', 'base_url', 'is_healthy']]
                values = [server_dict[k] for k in columns]
                placeholders = ', '.join(['?' for _ in columns])
                column_names = ', '.join(columns)
                
                cursor.execute(f"INSERT INTO sync_servers ({column_names}) VALUES ({placeholders})", 
                             values)
                servers_restored += 1
        
        # Restore config if table exists
        configs_restored = 0
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_config'")
        if cursor.fetchone():
            for key, value in backup_data.get('config', {}).items():
                # Check if config already exists
                cursor.execute("SELECT id FROM sync_config WHERE key = ?", (key,))
                existing = cursor.fetchone()
                
                if not existing:
                    cursor.execute("INSERT INTO sync_config (key, value) VALUES (?, ?)", 
                                 (key, value))
                    configs_restored += 1
        
        conn.commit()
        conn.close()
        
        print(f"SUCCESS: Sync server configuration restored:")
        print(f"   - {servers_restored} servers restored")
        print(f"   - {configs_restored} config items restored")
        return True
            
    except Exception as e:
        print(f"Error restoring sync server config: {e}")
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
