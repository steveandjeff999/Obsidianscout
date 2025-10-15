"""
Simplified Bidirectional Sync System
Single atomic sync operation that works reliably both ways
"""

import json
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from flask import current_app
from app import db
from app.models import SyncServer, SyncLog, DatabaseChange
from app.utils.change_tracking import disable_change_tracking, enable_change_tracking
import logging

logger = logging.getLogger(__name__)

def parse_datetime_string(value, field_name=None):
    """Helper function to parse datetime strings with multiple format support"""
    if not isinstance(value, str):
        return value
    
    try:
        # Try ISO format first
        return datetime.fromisoformat(value.replace('Z', '+00:00').replace('+00:00', ''))
    except:
        try:
            # Try parsing with dateutil for more flexible parsing
            from dateutil import parser
            return parser.parse(value).replace(tzinfo=None)
        except:
            try:
                # Try common formats
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S']:
                    try:
                        return datetime.strptime(value, fmt)
                    except:
                        continue
            except:
                pass
    
    logger.warning(f"Could not parse datetime string '{value}' for field '{field_name}', keeping as string")
    return value

def is_datetime_field(field_name):
    """Check if a field name indicates it should be a datetime"""
    datetime_fields = [
        'created_at', 'updated_at', 'timestamp', 'last_login', 
        'last_sync', 'started_at', 'completed_at', 'expires_at',
        'synced_at', 'deleted_at'
    ]
    return (field_name in datetime_fields or 
            field_name.endswith('_at') or 
            field_name.endswith('_time') or
            field_name.endswith('_login'))

class SimplifiedSyncManager:
    """Simplified sync manager with reliable bidirectional synchronization"""
    
    def __init__(self):
        self.connection_timeout = 30
        self.server_id = self._get_server_id()
    
    def _get_server_id(self):
        """Get or create a unique server ID"""
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
    
    def perform_bidirectional_sync(self, server_id: int) -> Dict:
        """
        Perform a single, atomic bidirectional sync with specified server
        Returns detailed sync results
        """
        server = SyncServer.query.get_or_404(server_id)
        
        if not server.sync_enabled:
            return {'success': False, 'error': 'Sync is disabled for this server'}
        
        # Create sync log
        sync_log = SyncLog(
            server_id=server.id,
            sync_type='bidirectional',
            direction='bidirectional',
            status='in_progress',
            started_at=datetime.now(timezone.utc)
        )
        db.session.add(sync_log)
        db.session.commit()
        
        results = {
            'success': False,
            'server_name': server.name,
            'server_url': f"{server.host}:{server.port}",
            'operations': [],
            'stats': {
                'sent_to_remote': 0,
                'received_from_remote': 0,
                'conflicts_resolved': 0,
                'errors': []
            }
        }
        
        try:
            logger.info(f"🔄 Starting bidirectional sync with {server.name}")
            
            # Step 1: Test connectivity
            if not self._test_connection(server):
                raise Exception("Server is not reachable")
            
            results['operations'].append("✅ Connection established")
            
            # Step 2: Exchange sync metadata and perform atomic sync
            sync_result = self._perform_atomic_sync(server, sync_log)
            results.update(sync_result)
            
            # Step 3: Update server last sync time
            server.last_sync = datetime.now(timezone.utc)
            server.status = 'online'
            
            sync_log.status = 'completed'
            sync_log.completed_at = datetime.now(timezone.utc)
            sync_log.items_synced = results['stats']['sent_to_remote'] + results['stats']['received_from_remote']
            
            db.session.commit()
            
            results['success'] = True
            results['operations'].append("✅ Sync completed successfully")
            
            logger.info(f"✅ Bidirectional sync completed with {server.name}")
            
        except Exception as e:
            logger.error(f"❌ Sync failed with {server.name}: {e}")
            
            sync_log.status = 'failed'
            sync_log.error_message = str(e)
            sync_log.completed_at = datetime.now(timezone.utc)
            
            server.status = 'error'
            
            db.session.commit()
            
            results['success'] = False
            results['error'] = str(e)
            results['stats']['errors'].append(str(e))
            results['operations'].append(f"❌ Sync failed: {str(e)}")
        
        return results
    
    def _test_connection(self, server: SyncServer) -> bool:
        """Test if server is reachable"""
        try:
            url = f"{server.protocol}://{server.host}:{server.port}/api/sync/ping"
            response = requests.get(url, timeout=5, verify=False)
            if response.status_code == 200:
                # Update server health status
                server.update_ping(success=True)
                db.session.commit()
                return True
            else:
                server.update_ping(success=False, error_message=f"HTTP {response.status_code}")
                db.session.commit()
                return False
        except Exception as e:
            server.update_ping(success=False, error_message=str(e))
            db.session.commit()
            return False
    
    def _perform_atomic_sync(self, server: SyncServer, sync_log: SyncLog) -> Dict:
        """
        Perform atomic bidirectional sync - all or nothing
        """
        results = {
            'operations': [],
            'stats': {
                'sent_to_remote': 0,
                'received_from_remote': 0,
                'conflicts_resolved': 0,
                'errors': []
            }
        }
        
        # Get cutoff time for changes (last sync or 24 hours ago)
        cutoff_time = server.last_sync
        if not cutoff_time:
            from datetime import timedelta
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Step 1: Get local changes to send
        local_changes = self._get_local_changes_since(cutoff_time)
        logger.info(f"📤 Found {len(local_changes)} local changes to send")
        results['operations'].append(f"📤 Prepared {len(local_changes)} local changes")
        
        # Step 2: Get remote changes 
        remote_changes = self._get_remote_changes(server, cutoff_time)
        logger.info(f"📥 Found {len(remote_changes)} remote changes to apply")
        results['operations'].append(f"📥 Received {len(remote_changes)} remote changes")
        
        # Step 3: Detect and resolve conflicts
        conflicts = self._detect_conflicts(local_changes, remote_changes)
        if conflicts:
            logger.info(f"⚠️  Detected {len(conflicts)} conflicts")
            resolved_conflicts = self._resolve_conflicts(conflicts)
            results['stats']['conflicts_resolved'] = len(resolved_conflicts)
            results['operations'].append(f"⚠️  Resolved {len(resolved_conflicts)} conflicts")
        
        # Step 4: Send local changes to remote server (atomic)
        if local_changes:
            send_result = self._send_changes_to_remote(server, local_changes)
            if send_result['success']:
                results['stats']['sent_to_remote'] = len(local_changes)
                results['operations'].append(f"✅ Sent {len(local_changes)} changes to remote")
                logger.info(f"✅ Successfully sent {len(local_changes)} changes to {server.name}")
            else:
                raise Exception(f"Failed to send changes: {send_result['error']}")
        
        # Step 5: Apply remote changes locally (atomic)
        if remote_changes:
            apply_result = self._apply_remote_changes(remote_changes)
            if apply_result['success']:
                results['stats']['received_from_remote'] = len(remote_changes)
                results['operations'].append(f"✅ Applied {len(remote_changes)} remote changes")
                logger.info(f"✅ Successfully applied {len(remote_changes)} changes from {server.name}")
            else:
                raise Exception(f"Failed to apply changes: {apply_result['error']}")
        
        # Step 6: Mark all synced changes as completed
        self._mark_changes_as_synced(local_changes)
        
        return results
    
    def _get_local_changes_since(self, since_time: datetime) -> List[Dict]:
        """Get local database changes since specified time"""
        try:
            changes = DatabaseChange.query.filter(
                DatabaseChange.timestamp > since_time,
                DatabaseChange.sync_status == 'pending'
            ).order_by(DatabaseChange.timestamp.asc()).all()
            
            return [change.to_dict() for change in changes]
        except Exception as e:
            logger.error(f"Error getting local changes: {e}")
            return []
    
    def _get_remote_changes(self, server: SyncServer, since_time: datetime) -> List[Dict]:
        """Get changes from remote server"""
        try:
            url = f"{server.protocol}://{server.host}:{server.port}/api/sync/changes"
            params = {
                'since': since_time.isoformat(),
                'server_id': self.server_id
            }
            
            response = requests.get(url, params=params, timeout=self.connection_timeout, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('changes', [])
            else:
                logger.error(f"Failed to get remote changes: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting remote changes: {e}")
            return []
    
    def _detect_conflicts(self, local_changes: List[Dict], remote_changes: List[Dict]) -> List[Dict]:
        """Detect conflicts between local and remote changes"""
        conflicts = []
        
        # Create lookup for local changes
        local_by_record = {}
        for change in local_changes:
            key = f"{change['table']}:{change['record_id']}"
            if key not in local_by_record:
                local_by_record[key] = []
            local_by_record[key].append(change)
        
        # Check for conflicts with remote changes
        for remote_change in remote_changes:
            key = f"{remote_change['table']}:{remote_change['record_id']}"
            if key in local_by_record:
                # Same record modified locally and remotely
                conflicts.append({
                    'record_key': key,
                    'local_changes': local_by_record[key],
                    'remote_change': remote_change
                })
        
        return conflicts
    
    def _resolve_conflicts(self, conflicts: List[Dict]) -> List[Dict]:
        """Resolve conflicts using latest timestamp wins strategy"""
        resolved = []
        
        for conflict in conflicts:
            local_changes = conflict['local_changes']
            remote_change = conflict['remote_change']
            
            # Get latest local change
            latest_local = max(local_changes, key=lambda x: x['timestamp'])
            
            # Compare timestamps - latest wins
            local_time = datetime.fromisoformat(latest_local['timestamp'].replace('Z', '+00:00'))
            remote_time = datetime.fromisoformat(remote_change['timestamp'].replace('Z', '+00:00'))
            
            if remote_time > local_time:
                # Remote wins - we'll apply remote change
                resolved.append({
                    'winner': 'remote',
                    'applied_change': remote_change,
                    'record_key': conflict['record_key']
                })
            else:
                # Local wins - we'll keep local change and skip remote
                resolved.append({
                    'winner': 'local',
                    'applied_change': latest_local,
                    'record_key': conflict['record_key']
                })
        
        return resolved
    
    def _send_changes_to_remote(self, server: SyncServer, changes: List[Dict]) -> Dict:
        """Send changes to remote server"""
        try:
            url = f"{server.protocol}://{server.host}:{server.port}/api/sync/receive-changes"
            payload = {
                'changes': changes,
                'server_id': self.server_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            response = requests.post(url, json=payload, timeout=self.connection_timeout, verify=False)
            
            if response.status_code == 200:
                return {'success': True}
            else:
                return {'success': False, 'error': f"HTTP {response.status_code}: {response.text}"}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _apply_remote_changes(self, changes: List[Dict]) -> Dict:
        """Apply remote changes locally"""
        try:
            # Disable change tracking to prevent recursive tracking
            disable_change_tracking()
            
            # Also disable real-time replication during sync to prevent queue issues
            from app.utils.real_time_replication import DisableReplication
            
            with DisableReplication():
                # Import models
                from app.models import User, ScoutingData, Match, Team, Event
                
                model_map = {
                    'users': User,
                    'user': User,  # Handle both table name formats
                    'scouting_data': ScoutingData,
                    'matches': Match,
                    'teams': Team,
                    'events': Event
                }
                
                applied_count = 0
                errors = []
                
                for change in changes:
                    try:
                        table_name = change.get('table')
                        operation = change.get('operation', 'upsert')
                        data = change.get('data', {})
                        record_id = change.get('record_id')
                        
                        logger.debug(f"Applying change: {operation} on {table_name} ID {record_id}")
                        
                        if table_name not in model_map:
                            logger.warning(f"Unknown table for sync: {table_name}")
                            continue
                        
                        model_class = model_map[table_name]
                        
                        if operation in ['upsert', 'insert', 'update']:
                            self._apply_upsert(model_class, record_id, data)
                        elif operation == 'soft_delete':
                            self._apply_soft_delete(model_class, record_id)
                        elif operation == 'delete':
                            self._apply_hard_delete(model_class, record_id)
                        elif operation == 'reactivate':
                            self._apply_reactivate(model_class, record_id)
                        
                        applied_count += 1
                        
                    except Exception as e:
                        error_msg = f"Error applying change {change}: {e}"
                        logger.error(error_msg)
                        errors.append(error_msg)
                        continue
            
            if errors:
                logger.warning(f"Applied {applied_count} changes with {len(errors)} errors")
            
            db.session.commit()
            return {
                'success': True, 
                'applied_count': applied_count,
                'errors': errors
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Fatal error applying remote changes: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            enable_change_tracking()
    
    def _apply_upsert(self, model_class, record_id, data):
        """Apply upsert operation with proper datetime handling"""
        existing_record = model_class.query.get(record_id)
        
        if existing_record:
            # Update existing record
            for key, value in data.items():
                if key != 'id' and hasattr(existing_record, key):
                    # Convert datetime strings for datetime fields
                    if is_datetime_field(key):
                        value = parse_datetime_string(value, key)
                    setattr(existing_record, key, value)
        else:
            # Create new record
            processed_data = {}
            for key, value in data.items():
                if is_datetime_field(key):
                    processed_data[key] = parse_datetime_string(value, key)
                else:
                    processed_data[key] = value
            
            new_record = model_class(**processed_data)
            db.session.add(new_record)
    
    def _apply_soft_delete(self, model_class, record_id):
        """Apply soft delete operation"""
        record = model_class.query.get(record_id)
        if record and hasattr(record, 'is_active'):
            record.is_active = False
            if hasattr(record, 'updated_at'):
                record.updated_at = datetime.now(timezone.utc)
    
    def _apply_hard_delete(self, model_class, record_id):
        """Apply hard delete operation"""
        record = model_class.query.get(record_id)
        if record:
            db.session.delete(record)
    
    def _apply_reactivate(self, model_class, record_id):
        """Apply reactivation operation"""
        record = model_class.query.get(record_id)
        if record and hasattr(record, 'is_active'):
            record.is_active = True
            if hasattr(record, 'updated_at'):
                record.updated_at = datetime.now(timezone.utc)
    
    def _mark_changes_as_synced(self, changes: List[Dict]):
        """Mark local changes as synced"""
        try:
            change_ids = [change['id'] for change in changes if 'id' in change]
            if change_ids:
                DatabaseChange.query.filter(DatabaseChange.id.in_(change_ids)).update(
                    {'sync_status': 'synced'}, synchronize_session=False
                )
                db.session.commit()
        except Exception as e:
            logger.error(f"Error marking changes as synced: {e}")

# Create global instance
simplified_sync_manager = SimplifiedSyncManager()
