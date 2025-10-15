"""
Enhanced SQLite3-based Sync System
Direct SQLite operations for maximum reliability and performance
"""

import sqlite3
import json
import requests
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import hashlib
import time
from contextlib import contextmanager
from threading import Lock
import os

logger = logging.getLogger(__name__)

class SQLite3SyncManager:
    """Enhanced sync manager using direct SQLite3 operations for maximum reliability"""
    
    def __init__(self, db_path: str = 'instance/scouting.db'):
        self.db_path = db_path
        self.connection_timeout = 30
        self.sync_lock = Lock()

        # Automatically include users DB if present so user/role joins are synced
        users_db = 'instance/users.db'
        self.extra_db_paths = [users_db] if os.path.exists(users_db) else []
        self._ensure_sync_tables()
    
    def _ensure_sync_tables(self):
        """Ensure sync-related tables exist with proper indexes"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if database_changes table exists and get its current structure
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='database_changes'")
            table_exists = cursor.fetchone() is not None
            
            if table_exists:
                # Get current columns
                cursor.execute("PRAGMA table_info(database_changes)")
                existing_columns = {row[1] for row in cursor.fetchall()}
                
                # Add missing columns if needed
                required_columns = {
                    'change_hash': 'TEXT',
                    'retry_count': 'INTEGER DEFAULT 0',
                    'last_error': 'TEXT',
                    'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
                    'synced_at': 'DATETIME'
                }
                
                for column_name, column_def in required_columns.items():
                    if column_name not in existing_columns:
                        try:
                            cursor.execute(f"ALTER TABLE database_changes ADD COLUMN {column_name} {column_def}")
                        except Exception as e:
                            logger.warning(f"Could not add column {column_name}: {e}")
            else:
                # Create new enhanced database_changes table
                cursor.execute('''
                    CREATE TABLE database_changes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_name TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        data TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        sync_status TEXT DEFAULT 'pending',
                        server_id TEXT,
                        change_hash TEXT,
                        retry_count INTEGER DEFAULT 0,
                        last_error TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        synced_at DATETIME
                    )
                ''')
            
            # Create indexes for performance (only if they don't exist)
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_changes_status ON database_changes(sync_status)',
                'CREATE INDEX IF NOT EXISTS idx_changes_timestamp ON database_changes(timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_changes_table_record ON database_changes(table_name, record_id)'
            ]
            
            # Only create change_hash index if the column exists
            cursor.execute("PRAGMA table_info(database_changes)")
            columns = {row[1] for row in cursor.fetchall()}
            if 'change_hash' in columns:
                indexes.append('CREATE INDEX IF NOT EXISTS idx_changes_hash ON database_changes(change_hash)')
            
            for index_sql in indexes:
                try:
                    cursor.execute(index_sql)
                except Exception as e:
                    logger.warning(f"Could not create index: {e}")
            
            # Enhanced sync_log table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_log_sqlite3 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    sync_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    items_synced INTEGER DEFAULT 0,
                    items_failed INTEGER DEFAULT 0,
                    error_message TEXT,
                    operation_details TEXT,
                    sync_hash TEXT,
                    performance_metrics TEXT
                )
            ''')
            
            # Sync reliability tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_reliability (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    operation_type TEXT NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_success DATETIME,
                    last_failure DATETIME,
                    avg_duration REAL DEFAULT 0.0,
                    reliability_score REAL DEFAULT 1.0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self, timeout: int = 30):
        """Get a reliable SQLite connection with proper error handling"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=timeout)
            conn.row_factory = sqlite3.Row  # Enable dict-like row access
            
            # SQLite optimization settings for reliability
            conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging for better concurrency
            conn.execute('PRAGMA synchronous=FULL')  # Maximum durability
            conn.execute('PRAGMA foreign_keys=ON')   # Enforce referential integrity
            conn.execute('PRAGMA temp_store=MEMORY')  # Use memory for temp storage
            conn.execute('PRAGMA cache_size=-64000')  # 64MB cache
            
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def perform_reliable_sync(self, server_config: Dict) -> Dict:
        """Perform highly reliable bidirectional sync using SQLite3 operations"""
        with self.sync_lock:
            sync_start = time.time()
            sync_id = self._create_sync_log(server_config)
            
            result = {
                'success': False,
                'sync_id': sync_id,
                'server_name': server_config.get('name', 'Unknown'),
                'operations': [],
                'stats': {
                    'local_changes_sent': 0,
                    'remote_changes_received': 0,
                    'conflicts_resolved': 0,
                    'errors': [],
                    'duration': 0.0
                },
                'reliability_info': {}
            }
            
            try:
                logger.info(f"🔄 Starting SQLite3-enhanced sync with {server_config.get('name')}")
                
                # Step 1: Test connection reliability
                if not self._test_connection_reliability(server_config):
                    raise Exception("Server connection reliability test failed")
                
                result['operations'].append("✅ Connection reliability verified")
                
                # Step 2: Get local changes using direct SQLite queries
                local_changes = self._get_local_changes_sqlite3(server_config.get('last_sync'))
                logger.info(f"📤 Found {len(local_changes)} local changes")
                result['operations'].append(f"📤 Prepared {len(local_changes)} local changes")
                
                # Step 3: Get remote changes
                remote_changes = self._get_remote_changes_reliable(server_config, server_config.get('last_sync'))
                logger.info(f"📥 Received {len(remote_changes)} remote changes")
                result['operations'].append(f"📥 Received {len(remote_changes)} remote changes")
                
                # Step 4: Perform conflict detection with SQLite3
                conflicts = self._detect_conflicts_sqlite3(local_changes, remote_changes)
                if conflicts:
                    resolved = self._resolve_conflicts_sqlite3(conflicts)
                    result['stats']['conflicts_resolved'] = len(resolved)
                    result['operations'].append(f"⚠️ Resolved {len(resolved)} conflicts")
                
                # Step 5: Apply changes atomically using SQLite3 transactions
                if local_changes:
                    sent_count = self._send_changes_reliable(server_config, local_changes)
                    result['stats']['local_changes_sent'] = sent_count
                    result['operations'].append(f"📤 Sent {sent_count} changes to remote")
                
                if remote_changes:
                    applied_count = self._apply_changes_sqlite3(remote_changes)
                    result['stats']['remote_changes_received'] = applied_count
                    result['operations'].append(f"📥 Applied {applied_count} remote changes")
                
                # Step 6: Update sync tracking
                self._mark_changes_synced_sqlite3(local_changes)
                self._update_server_last_sync_sqlite3(server_config['id'])
                
                # Step 7: Update reliability metrics
                sync_duration = time.time() - sync_start
                self._update_reliability_metrics(server_config['id'], 'sync', True, sync_duration)
                
                result['success'] = True
                result['stats']['duration'] = sync_duration
                result['operations'].append("✅ SQLite3-enhanced sync completed successfully")
                
                self._complete_sync_log(sync_id, 'completed', result['stats'])
                
                logger.info(f"✅ Enhanced sync completed in {sync_duration:.2f}s")
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ SQLite3 sync failed: {error_msg}")
                
                result['stats']['errors'].append(error_msg)
                result['operations'].append(f"❌ Sync failed: {error_msg}")
                
                self._update_reliability_metrics(server_config['id'], 'sync', False, time.time() - sync_start)
                self._complete_sync_log(sync_id, 'failed', result['stats'], error_msg)
            
            return result
    
    def _get_local_changes_sqlite3(self, since_time: Optional[datetime]) -> List[Dict]:
        """Get local changes using optimized SQLite3 queries"""
        if not since_time:
            since_time = datetime.now(timezone.utc) - timedelta(hours=24)
        
        changes = []
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check what columns exist in the database_changes table
            cursor.execute("PRAGMA table_info(database_changes)")
            available_columns = {row[1] for row in cursor.fetchall()}
            
            # Build query based on available columns
            base_columns = ['table_name', 'record_id', 'operation', 'data', 'timestamp', 'id']
            optional_columns = []
            
            if 'change_hash' in available_columns:
                optional_columns.append('change_hash')
            if 'retry_count' in available_columns:
                optional_columns.append('retry_count')
            
            all_columns = base_columns + optional_columns
            columns_sql = ', '.join(all_columns)
            
            # Use optimized query with proper indexing
            where_clauses = ["sync_status = 'pending'", "timestamp > ?"]
            if 'retry_count' in available_columns:
                where_clauses.append("retry_count < 3")
            
            query = f'''
                SELECT {columns_sql}
                FROM database_changes 
                WHERE {' AND '.join(where_clauses)}
                ORDER BY timestamp ASC
                LIMIT 10000
            '''
            
            cursor.execute(query, (since_time.isoformat(),))
            
            for row in cursor.fetchall():
                # Map row data to columns
                row_dict = dict(zip(all_columns, row))
                
                change_data = {
                    'id': row_dict['id'],
                    'table': row_dict['table_name'],
                    'record_id': row_dict['record_id'],
                    'operation': row_dict['operation'],
                    'timestamp': row_dict['timestamp'],
                    'change_hash': row_dict.get('change_hash', '')
                }
                
                # Parse data JSON safely
                try:
                    if row_dict['data']:
                        change_data['data'] = json.loads(row_dict['data'])
                    else:
                        change_data['data'] = {}
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Invalid JSON in change record {row_dict['id']}: {e}")
                    change_data['data'] = {}
                
                changes.append(change_data)

        # Additionally capture important tables from any extra DBs (e.g. users.db)
        try:
            for extra_db in getattr(self, 'extra_db_paths', []) or []:
                try:
                    changes += self._capture_direct_table_changes(extra_db, since_time, tables_to_include=['user', 'role', 'user_roles'])
                except Exception as e:
                    logger.warning(f"Failed to capture direct changes from {extra_db}: {e}")
        except Exception:
            # defensive; nothing to do
            pass

        return changes

    def _capture_direct_table_changes(self, db_path: str, since_time: Optional[datetime], tables_to_include: Optional[List[str]] = None) -> List[Dict]:
        """Capture recent (or all) rows directly from a secondary DB for specified tables.
        This is used for user/role join tables that may not be tracked in the primary database_changes table.
        """
        out_changes: List[Dict] = []
        if not os.path.exists(db_path):
            return out_changes

        with sqlite3.connect(db_path, timeout=self.connection_timeout) as conn:
            cursor = conn.cursor()

            # Determine which tables to inspect
            if not tables_to_include:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = [r[0] for r in cursor.fetchall()]
            else:
                tables = tables_to_include

            for table_name in tables:
                try:
                    # Skip if table doesn't exist
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                    if cursor.fetchone() is None:
                        continue

                    # Get table schema and columns
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    cols_info = cursor.fetchall()
                    columns = [col[1] for col in cols_info]

                    # Choose timestamp column if present
                    ts_field = None
                    if 'updated_at' in columns:
                        ts_field = 'updated_at'
                    elif 'created_at' in columns:
                        ts_field = 'created_at'

                    if ts_field and since_time:
                        query = f"SELECT * FROM {table_name} WHERE {ts_field} > ? ORDER BY {ts_field}"
                        cursor.execute(query, (since_time.isoformat(),))
                    else:
                        # No timestamp available - fetch all rows (careful for large tables)
                        cursor.execute(f"SELECT * FROM {table_name} LIMIT 10000")

                    rows = cursor.fetchall()
                    for row in rows:
                        row_dict = dict(zip(columns, row))
                        # Enrich join rows with user/role names to allow cross-server mapping by natural key
                        if table_name == 'user_roles':
                            try:
                                # Attempt to resolve username and role name
                                uid = row_dict.get('user_id')
                                rid = row_dict.get('role_id')
                                if uid:
                                    cursor.execute('SELECT username FROM user WHERE id = ?', (uid,))
                                    r = cursor.fetchone()
                                    if r:
                                        row_dict['user_username'] = r[0]
                                if rid:
                                    cursor.execute('SELECT name FROM role WHERE id = ?', (rid,))
                                    r2 = cursor.fetchone()
                                    if r2:
                                        row_dict['role_name'] = r2[0]
                            except Exception:
                                # best-effort only
                                pass

                        change = {
                            'table': table_name,
                            'record_id': str(row_dict.get('id', '')),
                            'operation': 'upsert',
                            'data': row_dict,
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'change_hash': hashlib.md5(json.dumps(row_dict, sort_keys=True, default=str).encode()).hexdigest()
                        }
                        out_changes.append(change)
                except Exception as e:
                    logger.warning(f"Error capturing direct table {table_name} from {db_path}: {e}")
                    continue

        return out_changes
    
    def _apply_changes_sqlite3(self, changes: List[Dict]) -> int:
        """Apply remote changes using atomic SQLite3 transactions"""
        applied_count = 0
        
        with self._get_connection() as conn:
            try:
                cursor = conn.cursor()
                
                # Start transaction
                conn.execute('BEGIN IMMEDIATE')
                
                for change in changes:
                    try:
                        table_name = change.get('table')
                        operation = change.get('operation', 'upsert')
                        data = change.get('data', {})
                        record_id = change.get('record_id')
                        
                        logger.debug(f"Applying SQLite3 change: {operation} on {table_name} ID {record_id}")
                        
                        # Apply dependent tables first: roles and users before join tables
                        # We'll gather and apply in a deterministic priority order at the database-level
                        # (actual per-batch ordering handled below)
                        if operation in ['upsert', 'insert', 'update']:
                            self._apply_upsert_sqlite3(cursor, table_name, record_id, data)
                        elif operation == 'soft_delete':
                            self._apply_soft_delete_sqlite3(cursor, table_name, record_id)
                        elif operation == 'delete':
                            self._apply_hard_delete_sqlite3(cursor, table_name, record_id)
                        elif operation == 'reactivate':
                            self._apply_reactivate_sqlite3(cursor, table_name, record_id)
                        
                        applied_count += 1
                        
                    except Exception as e:
                        logger.error(f"Error applying change {change}: {e}")
                        # Continue with other changes rather than failing entire batch
                        continue
                
                # If we detect many changes, apply with priority ordering to ensure referential integrity
                # Group by table and sort by priority: role(1), user(2), others(3), user_roles(4)
                try:
                    table_priority = {'role': 1, 'user': 2, 'user_roles': 4}
                    def prio(c):
                        return table_priority.get(c.get('table'), 3)

                    ordered_changes = sorted(changes, key=prio)

                    # Re-apply ordered changes in a fresh transaction
                    conn.rollback()
                    conn.execute('BEGIN IMMEDIATE')
                    applied_count = 0
                    for change in ordered_changes:
                        try:
                            table_name = change.get('table')
                            operation = change.get('operation', 'upsert')
                            data = change.get('data', {})
                            record_id = change.get('record_id')

                            if operation in ['upsert', 'insert', 'update']:
                                self._apply_upsert_sqlite3(cursor, table_name, record_id, data)
                            elif operation == 'soft_delete':
                                self._apply_soft_delete_sqlite3(cursor, table_name, record_id)
                            elif operation == 'delete':
                                self._apply_hard_delete_sqlite3(cursor, table_name, record_id)
                            elif operation == 'reactivate':
                                self._apply_reactivate_sqlite3(cursor, table_name, record_id)

                            applied_count += 1
                        except Exception as e:
                            logger.error(f"Error applying ordered change {change}: {e}")
                            continue

                    conn.commit()
                    logger.info(f"Successfully applied {applied_count} changes via SQLite3 (ordered)")
                    applied_count_result = applied_count
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Transaction rollback during ordered change application: {e}")
                    raise
                # applied_count_result already set above
                
            except Exception as e:
                conn.rollback()
                logger.error(f"Transaction rollback during change application: {e}")
                raise
        
        return applied_count
    
    def _apply_upsert_sqlite3(self, cursor: sqlite3.Cursor, table_name: str, record_id: str, data: Dict):
        """Apply upsert operation using SQLite3 REPLACE or INSERT OR REPLACE"""
        if not data:
            return
        
        # Get table schema
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns_info = cursor.fetchall()
        valid_columns = {col['name'] for col in columns_info}
        
        # Filter data to only include valid columns
        filtered_data = {k: v for k, v in data.items() if k in valid_columns}
        
        if not filtered_data:
            logger.warning(f"No valid columns found for table {table_name}")
            return
        
        # Use INSERT OR REPLACE for reliable upserts
        columns = list(filtered_data.keys())
        placeholders = ', '.join(['?' for _ in columns])
        values = [filtered_data[col] for col in columns]
        
        # Ensure primary key is included
        if 'id' not in columns and record_id:
            columns.insert(0, 'id')
            values.insert(0, record_id)
            placeholders = '?, ' + placeholders
        
        query = f"INSERT OR REPLACE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        cursor.execute(query, values)

        # Special handling: if this is user_roles and referenced ids don't exist, try to map by natural keys
        if table_name == 'user_roles':
            try:
                uid = filtered_data.get('user_id') or (record_id if 'id' in filtered_data else None)
                rid = filtered_data.get('role_id')
                # If user id not present locally, try to find by username
                if uid:
                    cursor.execute('SELECT id FROM user WHERE id = ?', (uid,))
                    if not cursor.fetchone():
                        uname = filtered_data.get('user_username')
                        if uname:
                            cursor.execute('SELECT id FROM user WHERE username = ? LIMIT 1', (uname,))
                            urow = cursor.fetchone()
                            if urow:
                                uid = urow[0]
                # If role id not present, try lookup by role_name
                if rid:
                    cursor.execute('SELECT id FROM role WHERE id = ?', (rid,))
                    if not cursor.fetchone():
                        rname = filtered_data.get('role_name')
                        if rname:
                            cursor.execute('SELECT id FROM role WHERE name = ? LIMIT 1', (rname,))
                            rrow = cursor.fetchone()
                            if rrow:
                                rid = rrow[0]

                # If we found remapped ids, ensure join row exists
                if uid and rid:
                    cursor.execute('SELECT COUNT(*) FROM user_roles WHERE user_id = ? AND role_id = ?', (uid, rid))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute('INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))
            except Exception as e:
                logger.warning(f"user_roles post-insert mapping/verification failed: {e}")
    
    def _apply_soft_delete_sqlite3(self, cursor: sqlite3.Cursor, table_name: str, record_id: str):
        """Apply soft delete using SQLite3"""
        # Check if table has deleted_at column
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {col['name'] for col in cursor.fetchall()}
        
        if 'deleted_at' in columns:
            cursor.execute(f"UPDATE {table_name} SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (record_id,))
        elif 'is_deleted' in columns:
            cursor.execute(f"UPDATE {table_name} SET is_deleted = 1 WHERE id = ?", (record_id,))
        else:
            # Fall back to hard delete if no soft delete columns
            self._apply_hard_delete_sqlite3(cursor, table_name, record_id)
    
    def _apply_hard_delete_sqlite3(self, cursor: sqlite3.Cursor, table_name: str, record_id: str):
        """Apply hard delete using SQLite3"""
        cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (record_id,))
    
    def _apply_reactivate_sqlite3(self, cursor: sqlite3.Cursor, table_name: str, record_id: str):
        """Reactivate a soft-deleted record using SQLite3"""
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {col['name'] for col in cursor.fetchall()}
        
        if 'deleted_at' in columns:
            cursor.execute(f"UPDATE {table_name} SET deleted_at = NULL WHERE id = ?", (record_id,))
        elif 'is_deleted' in columns:
            cursor.execute(f"UPDATE {table_name} SET is_deleted = 0 WHERE id = ?", (record_id,))
    
    def _test_connection_reliability(self, server_config: Dict) -> bool:
        """Test connection reliability and update metrics"""
        try:
            url = f"{server_config.get('protocol', 'http')}://{server_config['host']}:{server_config['port']}/api/sync/ping"
            
            start_time = time.time()
            response = requests.get(url, timeout=10, verify=False)
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                self._update_reliability_metrics(server_config['id'], 'connection', True, response_time)
                return True
            else:
                self._update_reliability_metrics(server_config['id'], 'connection', False, response_time)
                return False
                
        except Exception as e:
            logger.error(f"Connection reliability test failed: {e}")
            self._update_reliability_metrics(server_config['id'], 'connection', False, 0.0)
            return False
    
    def _get_remote_changes_reliable(self, server_config: Dict, since_time: Optional[datetime]) -> List[Dict]:
        """Get remote changes with retry logic and reliability tracking"""
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                url = f"{server_config.get('protocol', 'http')}://{server_config['host']}:{server_config['port']}/api/sync/changes"
                params = {
                    'since': since_time.isoformat() if since_time else (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
                    'server_id': server_config.get('id', 'local'),
                    'format': 'sqlite3_optimized'
                }
                
                start_time = time.time()
                response = requests.get(url, params=params, timeout=self.connection_timeout, verify=False)
                response_time = time.time() - start_time
                
                if response.status_code == 200:
                    data = response.json()
                    changes = data.get('changes', [])
                    
                    self._update_reliability_metrics(server_config['id'], 'fetch_changes', True, response_time)
                    return changes
                else:
                    logger.warning(f"HTTP {response.status_code} on attempt {attempt + 1}")
                    
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
        
        self._update_reliability_metrics(server_config['id'], 'fetch_changes', False, 0.0)
        return []
    
    def _send_changes_reliable(self, server_config: Dict, changes: List[Dict]) -> int:
        """Send changes with reliability tracking and retry logic"""
        if not changes:
            return 0
        
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                url = f"{server_config.get('protocol', 'http')}://{server_config['host']}:{server_config['port']}/api/sync/receive-changes"
                payload = {
                    'changes': changes,
                    'server_id': server_config.get('id', 'local'),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'format': 'sqlite3_optimized'
                }
                
                start_time = time.time()
                response = requests.post(url, json=payload, timeout=self.connection_timeout, verify=False)
                response_time = time.time() - start_time
                
                if response.status_code == 200:
                    self._update_reliability_metrics(server_config['id'], 'send_changes', True, response_time)
                    return len(changes)
                else:
                    logger.warning(f"Send failed with HTTP {response.status_code} on attempt {attempt + 1}")
                    
            except Exception as e:
                logger.warning(f"Send attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
        
        self._update_reliability_metrics(server_config['id'], 'send_changes', False, 0.0)
        return 0
    
    def _detect_conflicts_sqlite3(self, local_changes: List[Dict], remote_changes: List[Dict]) -> List[Dict]:
        """Detect conflicts using SQLite3 operations for performance"""
        if not local_changes or not remote_changes:
            return []
        
        conflicts = []
        
        # Create temporary in-memory database for conflict detection
        with sqlite3.connect(':memory:') as temp_conn:
            temp_conn.execute('''
                CREATE TABLE local_changes (
                    table_name TEXT,
                    record_id TEXT,
                    timestamp TEXT,
                    change_hash TEXT,
                    PRIMARY KEY (table_name, record_id)
                )
            ''')
            
            temp_conn.execute('''
                CREATE TABLE remote_changes (
                    table_name TEXT,
                    record_id TEXT,
                    timestamp TEXT,
                    change_hash TEXT,
                    PRIMARY KEY (table_name, record_id)
                )
            ''')
            
            # Insert local changes
            for change in local_changes:
                temp_conn.execute('''
                    INSERT OR REPLACE INTO local_changes VALUES (?, ?, ?, ?)
                ''', (change.get('table'), change.get('record_id'), 
                      change.get('timestamp'), change.get('change_hash', '')))
            
            # Insert remote changes
            for change in remote_changes:
                temp_conn.execute('''
                    INSERT OR REPLACE INTO remote_changes VALUES (?, ?, ?, ?)
                ''', (change.get('table'), change.get('record_id'),
                      change.get('timestamp'), change.get('change_hash', '')))
            
            # Find conflicts using SQL JOIN
            cursor = temp_conn.cursor()
            cursor.execute('''
                SELECT 
                    l.table_name,
                    l.record_id,
                    l.timestamp as local_time,
                    r.timestamp as remote_time,
                    l.change_hash as local_hash,
                    r.change_hash as remote_hash
                FROM local_changes l
                INNER JOIN remote_changes r 
                ON l.table_name = r.table_name 
                AND l.record_id = r.record_id
                WHERE l.change_hash != r.change_hash
            ''')
            
            for row in cursor.fetchall():
                conflicts.append({
                    'table': row[0],
                    'record_id': row[1],
                    'local_timestamp': row[2],
                    'remote_timestamp': row[3],
                    'local_hash': row[4],
                    'remote_hash': row[5]
                })
        
        logger.info(f"Detected {len(conflicts)} conflicts using SQLite3")
        return conflicts
    
    def _resolve_conflicts_sqlite3(self, conflicts: List[Dict]) -> List[Dict]:
        """Resolve conflicts using latest timestamp wins strategy"""
        resolved = []
        
        for conflict in conflicts:
            try:
                local_time = datetime.fromisoformat(conflict['local_timestamp'])
                remote_time = datetime.fromisoformat(conflict['remote_timestamp'])
                
                winner = 'remote' if remote_time > local_time else 'local'
                resolved.append({
                    'table': conflict['table'],
                    'record_id': conflict['record_id'],
                    'winner': winner,
                    'resolution_method': 'latest_timestamp'
                })
                
            except Exception as e:
                logger.error(f"Error resolving conflict: {e}")
                continue
        
        return resolved
    
    def _mark_changes_synced_sqlite3(self, changes: List[Dict]):
        """Mark changes as synced using SQLite3"""
        if not changes:
            return
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            change_ids = [change.get('id') for change in changes if change.get('id')]
            
            if change_ids:
                placeholders = ', '.join(['?' for _ in change_ids])
                cursor.execute(f'''
                    UPDATE database_changes 
                    SET sync_status = 'completed', 
                        synced_at = CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})
                ''', change_ids)
                conn.commit()
    
    def _update_server_last_sync_sqlite3(self, server_id: int):
        """Update server last sync time using SQLite3"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sync_servers 
                SET last_sync = CURRENT_TIMESTAMP,
                    status = 'online'
                WHERE id = ?
            ''', (server_id,))
            conn.commit()
    
    def _create_sync_log(self, server_config: Dict) -> int:
        """Create sync log entry and return ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sync_log_sqlite3 
                (server_id, sync_type, direction, status, operation_details)
                VALUES (?, 'bidirectional', 'both', 'in_progress', ?)
            ''', (server_config.get('id'), json.dumps(server_config)))
            conn.commit()
            return cursor.lastrowid
    
    def _complete_sync_log(self, sync_id: int, status: str, stats: Dict, error_message: str = None):
        """Complete sync log entry"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sync_log_sqlite3
                SET status = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    items_synced = ?,
                    items_failed = ?,
                    error_message = ?,
                    performance_metrics = ?
                WHERE id = ?
            ''', (status, 
                  stats.get('local_changes_sent', 0) + stats.get('remote_changes_received', 0),
                  len(stats.get('errors', [])),
                  error_message,
                  json.dumps(stats),
                  sync_id))
            conn.commit()
    
    def _update_reliability_metrics(self, server_id: int, operation_type: str, success: bool, duration: float):
        """Update reliability metrics for server operations"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get existing metrics
            cursor.execute('''
                SELECT success_count, failure_count, avg_duration, reliability_score
                FROM sync_reliability
                WHERE server_id = ? AND operation_type = ?
            ''', (server_id, operation_type))
            
            row = cursor.fetchone()
            
            if row:
                success_count = row['success_count'] + (1 if success else 0)
                failure_count = row['failure_count'] + (0 if success else 1)
                
                # Calculate moving average duration
                old_avg = row['avg_duration']
                total_ops = success_count + failure_count
                new_avg = ((old_avg * (total_ops - 1)) + duration) / total_ops if total_ops > 0 else duration
                
                # Calculate reliability score (success rate)
                reliability_score = success_count / total_ops if total_ops > 0 else 1.0
                
                cursor.execute('''
                    UPDATE sync_reliability
                    SET success_count = ?,
                        failure_count = ?,
                        avg_duration = ?,
                        reliability_score = ?,
                        last_success = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE last_success END,
                        last_failure = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE last_failure END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE server_id = ? AND operation_type = ?
                ''', (success_count, failure_count, new_avg, reliability_score,
                      success, not success, server_id, operation_type))
            else:
                # Create new metrics entry
                cursor.execute('''
                    INSERT INTO sync_reliability
                    (server_id, operation_type, success_count, failure_count, avg_duration, 
                     reliability_score, last_success, last_failure)
                    VALUES (?, ?, ?, ?, ?, ?, 
                           CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                           CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
                ''', (server_id, operation_type, 
                      1 if success else 0, 
                      0 if success else 1, 
                      duration, 
                      1.0 if success else 0.0,
                      success, not success))
            
            conn.commit()
    
    def get_reliability_report(self, server_id: int) -> Dict:
        """Get comprehensive reliability report for a server"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    operation_type,
                    success_count,
                    failure_count,
                    avg_duration,
                    reliability_score,
                    last_success,
                    last_failure
                FROM sync_reliability
                WHERE server_id = ?
                ORDER BY operation_type
            ''', (server_id,))
            
            metrics = {}
            for row in cursor.fetchall():
                total_ops = row['success_count'] + row['failure_count']
                metrics[row['operation_type']] = {
                    'success_count': row['success_count'],
                    'failure_count': row['failure_count'],
                    'total_operations': total_ops,
                    'success_rate': row['reliability_score'],
                    'avg_duration': row['avg_duration'],
                    'last_success': row['last_success'],
                    'last_failure': row['last_failure']
                }
            
            return {
                'server_id': server_id,
                'operations': metrics,
                'overall_reliability': sum(m['success_rate'] for m in metrics.values()) / len(metrics) if metrics else 0.0
            }
    
    def cleanup_old_sync_data(self, days_to_keep: int = 30):
        """Clean up old sync data to maintain performance"""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        cutoff_iso = cutoff_date.isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Clean up old completed sync changes
            cursor.execute('''
                DELETE FROM database_changes
                WHERE sync_status = 'completed'
                  AND synced_at < ?
            ''', (cutoff_iso,))
            
            deleted_changes = cursor.rowcount
            
            # Clean up old sync logs
            cursor.execute('''
                DELETE FROM sync_log_sqlite3
                WHERE completed_at < ?
                  AND status IN ('completed', 'failed')
            ''', (cutoff_iso,))
            
            deleted_logs = cursor.rowcount
            
            conn.commit()
            
            logger.info(f"Cleaned up {deleted_changes} old changes and {deleted_logs} old logs")
            
            return {
                'deleted_changes': deleted_changes,
                'deleted_logs': deleted_logs,
                'cutoff_date': cutoff_iso
            }
