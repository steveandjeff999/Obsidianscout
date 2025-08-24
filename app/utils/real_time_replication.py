"""
Real-time Database Replication System
Automatically replicates all database operations to all configured servers in real-time
No more sync needed - all databases stay synchronized automatically
"""

import requests
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from flask import current_app, request
from sqlalchemy import event
from sqlalchemy.orm import Session
from app import db
from app.models import SyncServer
import threading
import queue
import time

logger = logging.getLogger(__name__)

class RealTimeReplicator:
    """Handles real-time replication of database operations to all servers"""
    
    def __init__(self):
        self.replication_queue = queue.Queue()
        self.worker_thread = None
        self.running = False
        self.enabled = False  # Track if replication is enabled
        self.connection_timeout = 5
        self.retry_attempts = 2
        
    def start(self):
        """Start the real-time replication worker"""
        if not self.running:
            self.running = True
            # worker will use the Flask app passed to start (if any) to create an app context
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.worker_thread.start()
            logger.info("🚀 Real-time database replication started")
    
    def stop(self):
        """Stop the real-time replication worker"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
            logger.info("🛑 Real-time database replication stopped")
    
    def get_queue_size(self):
        """Get the current size of the replication queue"""
        return self.replication_queue.qsize()
    
    def is_worker_running(self):
        """Check if the background worker is running"""
        return self.running and self.worker_thread and self.worker_thread.is_alive()
    
    def replicate_operation(self, operation_type: str, table_name: str, record_data: Dict, record_id: Optional[str] = None):
        """Queue a database operation for replication to all servers"""
        if not self.running:
            return
            
        try:
            operation = {
                'type': operation_type,  # 'insert', 'update', 'delete'
                'table': table_name,
                'data': record_data,
                'record_id': record_id,
                'timestamp': datetime.utcnow().isoformat(),
                'source_server': self._get_server_id()
            }
            
            self.replication_queue.put(operation)
            logger.debug(f"📤 Queued {operation_type} operation for {table_name}")
        except Exception as e:
            logger.error(f"❌ Error queuing replication operation: {e}")
            # Don't re-raise to prevent disrupting the main application
    
    def queue_operation(self, operation_type: str, table_name: str, record_data: Dict, record_id: Optional[str] = None):
        """Alias for replicate_operation - queue a database operation for replication"""
        self.replicate_operation(operation_type, table_name, record_data, record_id)
    
    def _worker(self):
        """Background worker that processes replication queue"""
        while self.running:
            try:
                # Get operation from queue (wait up to 1 second)
                operation = self.replication_queue.get(timeout=1)
                # Get all active sync servers within the provided app context
                # Avoid calling create_app() here because that would re-run
                # application startup (and re-register event listeners), which
                # can mutate SQLAlchemy's listener deque while it's being iterated.
                if getattr(self, 'app', None) is not None:
                    with self.app.app_context():
                        servers = SyncServer.query.filter_by(sync_enabled=True).all()
                else:
                    # No app provided; skip this iteration to avoid creating
                    # a fresh app and re-running startup logic.
                    time.sleep(0.5)
                    self.replication_queue.task_done()
                    continue
                    
                    if servers:
                        self._replicate_to_servers(operation, servers)
                
                self.replication_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Error in replication worker: {e}")
                # Continue processing to prevent worker from stopping
                try:
                    self.replication_queue.task_done()
                except:
                    pass
                continue
            except Exception as e:
                logger.error(f"❌ Error in replication worker: {e}")
                time.sleep(1)
    
    def _replicate_to_servers(self, operation: Dict, servers: List[SyncServer]):
        """Replicate operation to all servers"""
        successful_replications = 0
        
        for server in servers:
            try:
                if self._send_operation_to_server(operation, server):
                    successful_replications += 1
                else:
                    logger.warning(f"⚠️ Failed to replicate to {server.name}")
            except Exception as e:
                logger.error(f"❌ Error replicating to {server.name}: {e}")
        
        if successful_replications > 0:
            logger.debug(f"✅ Replicated {operation['type']} to {successful_replications}/{len(servers)} servers")
    
    def _send_operation_to_server(self, operation: Dict, server: SyncServer) -> bool:
        """Send operation to a specific server"""
        try:
            url = f"{server.protocol}://{server.host}:{server.port}/api/realtime/receive"
            
            payload = {
                'operation': operation,
                'source_server_id': self._get_server_id(),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            response = requests.post(
                url, 
                json=payload, 
                timeout=self.connection_timeout,
                verify=False
            )
            
            if response.status_code == 200:
                return True
            else:
                logger.warning(f"❌ Server {server.name} returned HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Network error sending to {server.name}: {e}")
            return False
    
    def _get_server_id(self):
        """Get current server ID"""
        try:
            from app.models import SyncConfig
            return SyncConfig.get_value('server_id', 'local')
        except:
            return 'local'

# Global replicator instance
real_time_replicator = RealTimeReplicator()

def enable_real_time_replication():
    """Enable real-time replication for all tracked models"""
    from app.models import User, ScoutingData, Match, Team, Event
    
    models_to_track = [User, ScoutingData, Match, Team, Event]
    
    for model_class in models_to_track:
        setup_real_time_tracking(model_class)
    
    # Start the worker; the application should pass its Flask app instance
    # into start() if available. If not, the worker will run but will avoid
    # creating a new app (see worker logic).
    real_time_replicator.start()
    real_time_replicator.enabled = True
    logger.info("✅ Real-time replication enabled for all models")

def disable_real_time_replication():
    """Disable real-time replication"""
    real_time_replicator.stop()
    real_time_replicator.enabled = False
    logger.info("🛑 Real-time replication disabled")

def setup_real_time_tracking(model_class):
    """Setup real-time tracking for a model class with complete thread isolation"""
    
    @event.listens_for(model_class, 'after_insert', propagate=True)
    def track_insert(mapper, connection, target):
        """Track record insertions with complete thread isolation"""
        if not should_replicate():
            return
        
        try:
            # Immediately queue the operation without any processing in the event handler
            record_data = serialize_record(target, mapper)
            real_time_replicator.queue_operation(
                'insert', 
                target.__tablename__, 
                record_data, 
                str(target.id)
            )
        except Exception as e:
            # Log but don't raise to avoid breaking the transaction
            logger.error(f"❌ Error queuing insert for {model_class.__name__}: {e}")
    
    @event.listens_for(model_class, 'after_update', propagate=True)
    def track_update(mapper, connection, target):
        """Track record updates with complete thread isolation"""
        if not should_replicate():
            return
        
        try:
            # Immediately queue the operation without any processing in the event handler
            record_data = serialize_record(target, mapper)
            real_time_replicator.queue_operation(
                'update', 
                target.__tablename__, 
                record_data, 
                str(target.id)
            )
        except Exception as e:
            # Log but don't raise to avoid breaking the transaction
            logger.error(f"❌ Error queuing update for {model_class.__name__}: {e}")
        
    @event.listens_for(model_class, 'after_delete', propagate=True)
    def track_delete(mapper, connection, target):
        """Track record deletions with complete thread isolation"""
        if not should_replicate():
            return
        
        try:
            # Immediately queue the operation without any processing in the event handler
            real_time_replicator.queue_operation(
                'delete', 
                target.__tablename__, 
                None,  # No data needed for delete
                str(target.id)
            )
        except Exception as e:
            # Log but don't raise to avoid breaking the transaction
            logger.error(f"❌ Error queuing delete for {model_class.__name__}: {e}")

def serialize_record(target, mapper):
    """Serialize a record for replication"""
    record_data = {}
    
    for column in mapper.columns:
        value = getattr(target, column.name)
        
        if isinstance(value, datetime):
            value = value.isoformat()
        elif value is None:
            value = None
        else:
            # Convert to JSON-serializable type
            try:
                json.dumps(value)  # Test if it's JSON serializable
                record_data[column.name] = value
            except (TypeError, ValueError):
                record_data[column.name] = str(value)
    
    return record_data

def should_replicate():
    """Check if we should replicate this operation"""
    try:
        # Don't replicate if this operation came from another server
        if hasattr(request, 'headers') and request.headers.get('X-Replication-Source'):
            return False
        
        # Don't replicate during migrations or system operations
        if current_app.config.get('DISABLE_REPLICATION', False):
            return False
        
        return True
    except:
        return True

# Context manager to temporarily disable replication
class DisableReplication:
    """Context manager to temporarily disable replication"""
    
    def __enter__(self):
        current_app.config['DISABLE_REPLICATION'] = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        current_app.config['DISABLE_REPLICATION'] = False
