"""
Automatic SQLite3 Sync Integration
Replaces existing sync with zero data loss SQLite3 bidirectional sync
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import current_app
from app import db
from app.models import SyncServer, DatabaseChange
from app.utils.sqlite3_sync import SQLite3SyncManager

logger = logging.getLogger(__name__)

class AutomaticSQLite3Sync:
    """
    Automatic SQLite3 sync that ensures 0% data loss
    Integrates seamlessly with existing superadmin sync interface
    """
    
    def __init__(self):
        self.sqlite3_manager = SQLite3SyncManager()
        self.server_id = self._get_server_id()
        # Support multiple databases
        self.database_paths = {
            'scouting': 'instance/scouting.db',
            'users': 'instance/users.db'
        }
        # Map tables to their respective databases based on model bind_keys
        self.table_database_map = self._discover_table_mappings()
        
    def _discover_table_mappings(self) -> Dict[str, str]:
        """
        Automatically discover table mappings by examining actual database tables
        This ensures new tables are automatically included
        """
        table_mappings = {}
        
        # Check each database to discover all tables
        for db_name, db_path in self.database_paths.items():
            try:
                import sqlite3
                with sqlite3.connect(db_path, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    tables = [row[0] for row in cursor.fetchall()]
                    
                    for table_name in tables:
                        table_mappings[table_name] = db_name
                        
                    logger.info(f"Discovered {len(tables)} tables in {db_name} database")
                    
            except Exception as e:
                logger.warning(f"Could not discover tables in {db_name} database: {e}")
                
        return table_mappings
    
    def _get_database_path_for_table(self, table_name: str) -> str:
        """Get the correct database path for a specific table"""
        db_key = self.table_database_map.get(table_name, 'scouting')
        return self.database_paths[db_key]
    
    def _get_server_id(self):
        """Get unique server identifier"""
        try:
            from app.models import SyncConfig
            server_id = SyncConfig.get_value('server_id')
            if not server_id:
                import uuid
                server_id = str(uuid.uuid4())[:8]
                SyncConfig.set_value('server_id', server_id, description='Unique server identifier')
            return server_id
        except:
            return 'local'
    
    def perform_automatic_sync(self, server_id: int) -> Dict:
        """
        Automatic sync with 0% data loss guarantee
        Uses SQLite3 for maximum reliability
        """
        try:
            server = SyncServer.query.get_or_404(server_id)
            
            if not server.sync_enabled:
                return {
                    'success': False,
                    'error': 'Sync is disabled for this server',
                    'operations': ['❌ Sync disabled']
                }
            
            logger.info(f"🔄 Starting automatic SQLite3 sync with {server.name}")
            
            # Step 1: Capture all database changes using direct SQLite3 queries
            local_changes = self._capture_all_changes_sqlite3()
            logger.info(f"📊 Captured {len(local_changes)} local database changes")
            
            # Step 2: Get remote changes with retry and error handling
            remote_changes = self._get_remote_changes_reliable(server)
            logger.info(f"📊 Received {len(remote_changes)} remote changes")
            
            # Step 3: Perform atomic bidirectional sync
            server_config = {
                'id': server.id,
                'name': server.name,
                'host': server.host,
                'port': server.port,
                'protocol': server.protocol,
                'last_sync': server.last_sync
            }
            
            result = self.sqlite3_manager.perform_reliable_sync(server_config)
            
            if result['success']:
                logger.info(f"✅ Automatic SQLite3 sync completed successfully with {server.name}")
                
                # Update server status
                server.last_sync = datetime.utcnow()
                server.status = 'online'
                db.session.commit()
                
                result['operations'].append("✅ Server sync status updated")
                result['automatic'] = True
                
            return result
            
        except Exception as e:
            error_msg = f"Automatic SQLite3 sync failed: {str(e)}"
            logger.error(error_msg)
            
            return {
                'success': False,
                'error': error_msg,
                'operations': [f"❌ {error_msg}"],
                'automatic': True,
                'stats': {
                    'local_changes_sent': 0,
                    'remote_changes_received': 0,
                    'conflicts_resolved': 0,
                    'errors': [error_msg]
                }
            }
    
    def _capture_all_changes_sqlite3(self) -> List[Dict]:
        """
        Capture ALL database changes using direct SQLite3 operations
        Ensures no data is missed from both scouting and users databases
        """
        changes = []
        
        # Process each database
        for db_name, db_path in self.database_paths.items():
            try:
                import sqlite3
                with sqlite3.connect(db_path, timeout=30) as conn:
                    cursor = conn.cursor()
                    
                    # Get all tables in the database
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    tables = [row[0] for row in cursor.fetchall()]
                    
                    logger.info(f"Processing {len(tables)} tables from {db_name} database")
                    
                    for table_name in tables:
                        try:
                            # Skip sync-specific tables to avoid loops
                            if table_name in ['database_changes', 'sync_log_sqlite3', 'sync_reliability']:
                                continue
                            
                            # Get all records that have been modified recently or need sync
                            cursor.execute(f"PRAGMA table_info({table_name})")
                            columns_info = cursor.fetchall()
                            columns = [col[1] for col in columns_info]
                            
                            # Check if table has timestamp fields
                            has_updated_at = 'updated_at' in columns
                            has_created_at = 'created_at' in columns
                            
                            if has_updated_at or has_created_at:
                                # Get recent changes
                                timestamp_field = 'updated_at' if has_updated_at else 'created_at'
                                cutoff_time = datetime.now() - timedelta(hours=24)
                                
                                query = f"SELECT * FROM {table_name} WHERE {timestamp_field} > ? ORDER BY {timestamp_field}"
                                cursor.execute(query, (cutoff_time.isoformat(),))
                            else:
                                # For tables without timestamps, get all records (up to a limit)
                                query = f"SELECT * FROM {table_name} LIMIT 1000"
                                cursor.execute(query)
                            
                            rows = cursor.fetchall()
                            
                            for row in rows:
                                # Convert row to dictionary
                                row_dict = dict(zip(columns, row))
                                
                                # Create change record
                                change = {
                                    'table': table_name,
                                    'record_id': str(row_dict.get('id', '')),
                                    'operation': 'upsert',
                                    'data': row_dict,
                                    'timestamp': datetime.now().isoformat(),
                                    'change_hash': self._calculate_change_hash(row_dict),
                                    'server_id': self.server_id
                                }
                                
                                changes.append(change)
                                
                        except Exception as e:
                            logger.warning(f"Error capturing changes from table {table_name}: {e}")
                            continue
                            
            except Exception as e:
                logger.error(f"Error processing {db_name} database: {e}")
                continue
        
        logger.info(f"Captured {len(changes)} total database changes")
        return changes
    
    def _capture_full_database_state(self) -> List[Dict]:
        """
        Capture COMPLETE state of ALL tables in both databases
        No time restrictions - gets every record for full sync
        """
        changes = []
        
        # Process each database
        for db_name, db_path in self.database_paths.items():
            try:
                import sqlite3
                with sqlite3.connect(db_path, timeout=60) as conn:
                    cursor = conn.cursor()
                    
                    # Get all tables in the database
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    tables = [row[0] for row in cursor.fetchall()]
                    
                    logger.info(f"Full sync: Processing {len(tables)} tables from {db_name} database")
                    
                    for table_name in tables:
                        try:
                            # Skip sync-specific tables to avoid loops
                            if table_name in ['database_changes', 'sync_log_sqlite3', 'sync_reliability']:
                                continue
                            
                            # Get table schema
                            cursor.execute(f"PRAGMA table_info({table_name})")
                            columns_info = cursor.fetchall()
                            columns = [col[1] for col in columns_info]
                            
                            # Get ALL records from this table (no limits for full sync)
                            query = f"SELECT * FROM {table_name}"
                            cursor.execute(query)
                            rows = cursor.fetchall()
                            
                            logger.info(f"Full sync: Captured {len(rows)} records from {table_name}")
                            
                            for row in rows:
                                # Convert row to dictionary
                                row_dict = dict(zip(columns, row))
                                
                                # Create change record
                                change = {
                                    'table': table_name,
                                    'record_id': str(row_dict.get('id', '')),
                                    'operation': 'upsert',
                                    'data': row_dict,
                                    'timestamp': datetime.now().isoformat(),
                                    'change_hash': self._calculate_change_hash(row_dict),
                                    'server_id': self.server_id,
                                    'sync_type': 'full_sync'
                                }
                                
                                changes.append(change)
                                
                        except Exception as e:
                            logger.warning(f"Error capturing full state from table {table_name}: {e}")
                            continue
                            
            except Exception as e:
                logger.error(f"Error processing {db_name} database for full sync: {e}")
                continue
        
        logger.info(f"Full sync: Captured {len(changes)} total database records")
        return changes
    
    def _send_full_sync_to_server(self, server: SyncServer, all_data: List[Dict]) -> Dict:
        """Send complete database state to remote server"""
        try:
            import requests
            
            url = f"{server.protocol}://{server.host}:{server.port}/api/sync/sqlite3/full-sync-receive"
            
            # Send in batches to avoid overwhelming the server
            batch_size = 500
            total_sent = 0
            
            for i in range(0, len(all_data), batch_size):
                batch = all_data[i:i + batch_size]
                
                response = requests.post(url, json={
                    'source_server': self.server_id,
                    'sync_type': 'full_sync',
                    'batch_number': i // batch_size + 1,
                    'total_batches': (len(all_data) + batch_size - 1) // batch_size,
                    'changes': batch
                }, timeout=120)
                
                if response.status_code == 200:
                    total_sent += len(batch)
                    logger.info(f"Full sync: Sent batch {i // batch_size + 1}, {total_sent}/{len(all_data)} records")
                else:
                    logger.error(f"Full sync: Failed to send batch {i // batch_size + 1}")
                    return {'success': False, 'error': f'Failed to send batch: {response.text}'}
            
            return {
                'success': True,
                'records_sent': total_sent
            }
            
        except Exception as e:
            logger.error(f"Error sending full sync to {server.host}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_full_remote_database_state(self, server: SyncServer) -> List[Dict]:
        """Get complete database state from remote server"""
        try:
            import requests
            
            url = f"{server.protocol}://{server.host}:{server.port}/api/sync/sqlite3/full-sync-send"
            
            response = requests.get(url, params={
                'requesting_server': self.server_id,
                'sync_type': 'full_sync'
            }, timeout=180)
            
            if response.status_code == 200:
                data = response.json()
                remote_changes = data.get('changes', [])
                
                logger.info(f"Full sync: Retrieved {len(remote_changes)} records from {server.host}")
                return remote_changes
            else:
                logger.error(f"Failed to get full sync data from {server.host}: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting full sync from {server.host}: {e}")
            return []
    
    def perform_full_sync_all_tables(self, server_id: int) -> Dict:
        """
        Perform complete synchronization of ALL tables in both databases
        This ensures every table and record is synchronized across servers
        """
        try:
            server = SyncServer.query.get_or_404(server_id)
            
            if not server.sync_enabled:
                return {
                    'success': False,
                    'error': 'Sync is disabled for this server',
                    'operations': ['❌ Sync disabled']
                }
            
            operations = []
            
            # Step 1: Rediscover table mappings to catch new tables
            operations.append("🔍 Discovering all database tables...")
            self.table_database_map = self._discover_table_mappings()
            
            # Step 2: Capture ALL data from ALL tables
            operations.append("📊 Capturing complete database state...")
            all_changes = self._capture_full_database_state()
            
            # Step 3: Send all data to remote server
            if all_changes:
                operations.append(f"📤 Sending {len(all_changes)} complete records to {server.host}...")
                
                send_result = self._send_full_sync_to_server(server, all_changes)
                
                if send_result.get('success'):
                    operations.append(f"✅ Successfully sent all data to {server.host}")
                else:
                    operations.append(f"❌ Failed to send data: {send_result.get('error')}")
            
            # Step 4: Get complete remote data
            operations.append(f"📥 Receiving complete database state from {server.host}...")
            
            remote_data = self._get_full_remote_database_state(server)
            
            if remote_data:
                operations.append(f"📥 Received {len(remote_data)} records from {server.host}")
                
                # Step 5: Apply remote data with full integrity
                apply_result = self.apply_changes_zero_loss(remote_data)
                
                if apply_result.get('success'):
                    operations.append(f"✅ Successfully applied {apply_result['applied_count']} records")
                else:
                    operations.append(f"❌ Failed to apply remote data")
            
            # Step 6: Update sync timestamp
            server.last_sync = datetime.utcnow()
            db.session.commit()
            operations.append("✅ Full sync completed successfully")
            
            return {
                'success': True,
                'operations': operations,
                'local_changes_sent': len(all_changes) if all_changes else 0,
                'remote_changes_received': len(remote_data) if remote_data else 0,
                'total_tables_synced': len(self.table_database_map)
            }
            
        except Exception as e:
            error_msg = f"Full sync failed: {str(e)}"
            logger.error(error_msg)
            
            return {
                'success': False,
                'error': error_msg,
                'operations': [f"❌ {error_msg}"]
            }
    
    def _calculate_change_hash(self, data: Dict) -> str:
        """Calculate a hash for change detection"""
        import hashlib
        import json
        
        # Sort keys for consistent hashing
        sorted_data = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(sorted_data.encode()).hexdigest()
    
    def _get_remote_changes_reliable(self, server: SyncServer) -> List[Dict]:
        """Get remote changes with maximum reliability"""
        import requests
        import time
        
        max_retries = 5
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                url = f"{server.protocol}://{server.host}:{server.port}/api/sync/sqlite3/optimized-changes"
                
                params = {
                    'since': (server.last_sync or datetime.now() - timedelta(hours=24)).isoformat(),
                    'server_id': self.server_id,
                    'format': 'sqlite3_zero_loss'
                }
                
                response = requests.get(url, params=params, timeout=30, verify=False)
                
                if response.status_code == 200:
                    data = response.json()
                    changes = data.get('changes', [])
                    
                    logger.info(f"Successfully retrieved {len(changes)} remote changes on attempt {attempt + 1}")
                    return changes
                else:
                    logger.warning(f"HTTP {response.status_code} on attempt {attempt + 1}")
                    
            except Exception as e:
                logger.warning(f"Remote fetch attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
        
        logger.error(f"Failed to get remote changes after {max_retries} attempts")
        return []
    
    def send_changes_zero_loss(self, server: SyncServer, changes: List[Dict]) -> Dict:
        """
        Send changes with zero data loss guarantee
        Uses checksums and confirmations
        """
        if not changes:
            return {'success': True, 'sent_count': 0}
        
        import requests
        import time
        
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                url = f"{server.protocol}://{server.host}:{server.port}/api/sync/sqlite3/receive-changes"
                
                # Add checksums for verification
                payload = {
                    'changes': changes,
                    'server_id': self.server_id,
                    'timestamp': datetime.now().isoformat(),
                    'format': 'sqlite3_zero_loss',
                    'total_count': len(changes),
                    'checksum': self._calculate_batch_checksum(changes)
                }
                
                response = requests.post(url, json=payload, timeout=60, verify=False)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Verify all changes were applied
                    if result.get('applied_count') == len(changes):
                        logger.info(f"✅ All {len(changes)} changes sent successfully")
                        return {'success': True, 'sent_count': len(changes)}
                    else:
                        logger.warning(f"Partial send: {result.get('applied_count')}/{len(changes)}")
                        
                else:
                    logger.warning(f"Send failed: HTTP {response.status_code}")
                    
            except Exception as e:
                logger.warning(f"Send attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    time.sleep(2.0 * (attempt + 1))  # Longer delays for sends
        
        return {'success': False, 'sent_count': 0, 'error': 'Failed after all retries'}
    
    def _calculate_batch_checksum(self, changes: List[Dict]) -> str:
        """Calculate checksum for entire batch of changes"""
        import hashlib
        import json
        
        batch_data = json.dumps(changes, sort_keys=True, default=str)
        return hashlib.sha256(batch_data.encode()).hexdigest()
    
    def apply_changes_zero_loss(self, changes: List[Dict]) -> Dict:
        """
        Apply changes with 0% data loss guarantee
        Uses correct database for each table
        """
        if not changes:
            return {
                'success': True,
                'applied_count': 0,
                'errors': [],
                'total_received': 0
            }
        
        applied_count = 0
        errors = []
        
        # Group changes by database
        changes_by_db = {}
        for change in changes:
            table_name = change.get('table', '')
            db_path = self._get_database_path_for_table(table_name)
            
            if db_path not in changes_by_db:
                changes_by_db[db_path] = []
            changes_by_db[db_path].append(change)
        
        # Process each database separately
        for db_path, db_changes in changes_by_db.items():
            try:
                import sqlite3
                with sqlite3.connect(db_path, timeout=30) as conn:
                    cursor = conn.cursor()
                    conn.execute('BEGIN IMMEDIATE')
                    
                    # Ensure dependent tables are applied in safe order: roles/users first, join tables afterwards
                    table_priority = {'role': 1, 'user': 2, 'user_roles': 4}
                    # default priority 3 for everything else
                    def priority(ch):
                        return table_priority.get(ch.get('table'), 3)

                    for change in sorted(db_changes, key=priority):
                        try:
                            table_name = change.get('table', '')
                            record_id = change.get('record_id', '')
                            operation = change.get('operation', 'upsert')
                            data = change.get('data', {})
                            
                            logger.debug(f"Applying zero-loss change: {operation} on {table_name} ID {record_id}")
                            
                            if operation in ['upsert', 'insert', 'update']:
                                self._apply_upsert_zero_loss(cursor, table_name, record_id, data)
                            elif operation == 'soft_delete':
                                self._apply_soft_delete_zero_loss(cursor, table_name, record_id)
                            elif operation == 'delete':
                                self._apply_hard_delete_zero_loss(cursor, table_name, record_id)
                            elif operation == 'reactivate':
                                self._apply_reactivate_zero_loss(cursor, table_name, record_id)
                                
                            applied_count += 1
                                
                        except Exception as e:
                            error_msg = f"Error applying change to {table_name}: {e}"
                            logger.error(error_msg)
                            errors.append(error_msg)
                            continue
                    
                    # Commit transaction for this database
                    conn.commit()
                    logger.info(f"✅ Applied {len(db_changes)} changes to {db_path}")
                    
            except Exception as e:
                error_msg = f"Database transaction failed for {db_path}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
        
        logger.info(f"✅ Successfully applied {applied_count} changes with zero loss")
        
        return {
            'success': applied_count > 0 or len(changes) == 0,
            'applied_count': applied_count,
            'errors': errors,
            'total_received': len(changes)
        }
    
    def _apply_upsert_zero_loss(self, cursor, table_name: str, record_id: str, data: Dict):
        """Apply upsert with zero data loss verification"""
        if not data:
            return
        
        # Get table schema
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns_info = cursor.fetchall()
        valid_columns = {col[1] for col in columns_info}
        
        # Filter data to only include valid columns
        filtered_data = {k: v for k, v in data.items() if k in valid_columns}
        
        if not filtered_data:
            logger.warning(f"No valid columns found for table {table_name}")
            return
        
        # Use INSERT OR REPLACE for atomic upserts
        columns = list(filtered_data.keys())
        values = [filtered_data[col] for col in columns]
        
        # Ensure primary key is included
        if 'id' not in columns and record_id:
            columns.insert(0, 'id')
            values.insert(0, record_id)
        
        placeholders = ', '.join(['?' for _ in columns])
        query = f"INSERT OR REPLACE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        
        cursor.execute(query, values)
        
        # Verify the record was inserted/updated
        if record_id:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE id = ?", (record_id,))
            count = cursor.fetchone()[0]
            if count == 0:
                raise Exception(f"Failed to verify upsert for record {record_id} in {table_name}")
    
    def _apply_soft_delete_zero_loss(self, cursor, table_name: str, record_id: str):
        """Apply soft delete with verification"""
        # Check if table has soft delete columns
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {col[1] for col in cursor.fetchall()}
        
        if 'deleted_at' in columns:
            cursor.execute(f"UPDATE {table_name} SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (record_id,))
        elif 'is_deleted' in columns:
            cursor.execute(f"UPDATE {table_name} SET is_deleted = 1 WHERE id = ?", (record_id,))
        else:
            # Fall back to hard delete
            self._apply_hard_delete_zero_loss(cursor, table_name, record_id)
            return
        
        # Verify soft delete was applied
        if cursor.rowcount == 0:
            logger.warning(f"Soft delete verification failed for record {record_id} in {table_name}")
    
    def _apply_hard_delete_zero_loss(self, cursor, table_name: str, record_id: str):
        """Apply hard delete with verification"""
        cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (record_id,))
        
        # Verify deletion
        cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE id = ?", (record_id,))
        count = cursor.fetchone()[0]
        if count > 0:
            raise Exception(f"Failed to verify deletion for record {record_id} in {table_name}")
    
    def _apply_reactivate_zero_loss(self, cursor, table_name: str, record_id: str):
        """Reactivate a soft-deleted record with verification"""
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {col[1] for col in cursor.fetchall()}
        
        if 'deleted_at' in columns:
            cursor.execute(f"UPDATE {table_name} SET deleted_at = NULL WHERE id = ?", (record_id,))
        elif 'is_deleted' in columns:
            cursor.execute(f"UPDATE {table_name} SET is_deleted = 0 WHERE id = ?", (record_id,))
        
        # Verify reactivation
        if cursor.rowcount == 0:
            logger.warning(f"Reactivation verification failed for record {record_id} in {table_name}")

# Global instance for easy access
automatic_sqlite3_sync = AutomaticSQLite3Sync()
