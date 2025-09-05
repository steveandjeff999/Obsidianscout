"""
Multi-Server Sync API Routes
Provides API endpoints for server-to-server synchronization
"""
import os
import json
import hashlib
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
from app import db
from app.models import SyncServer, SyncLog, FileChecksum, SyncConfig
from app.utils.multi_server_sync import sync_manager
import tempfile
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

sync_api = Blueprint('sync_api', __name__, url_prefix='/api/sync')


@sync_api.route('/ping', methods=['GET'])
def ping():
    """Health check endpoint for server availability"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0',
        'server_id': getattr(sync_manager, 'server_id', 'unknown')
    })


@sync_api.route('/changes', methods=['GET'])
def get_changes():
    """Get database changes since specified time for simplified sync"""
    try:
        since_param = request.args.get('since')
        requesting_server_id = request.args.get('server_id', 'unknown')
        catchup_mode = request.args.get('catchup_mode', 'false').lower() == 'true'
        
        if not since_param:
            return jsonify({'error': 'since parameter is required'}), 400
        
        # Parse since timestamp
        try:
            since_time = datetime.fromisoformat(since_param.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid since timestamp format'}), 400
        
        # Get changes since the specified time
        from app.models import DatabaseChange
        
        # For catch-up mode, use larger limits and different batching
        if catchup_mode:
            logger.info(f"🔄 Catch-up mode: Getting changes since {since_time} for server {requesting_server_id}")
            # Get more changes for catch-up operations
            changes = DatabaseChange.query.filter(
                DatabaseChange.timestamp > since_time,
                DatabaseChange.sync_status == 'pending'
            ).order_by(DatabaseChange.timestamp.asc()).all()
        else:
            logger.info(f"📤 Normal mode: Getting changes since {since_time} for server {requesting_server_id}")
            # Get normal batch of changes
            changes = DatabaseChange.query.filter(
                DatabaseChange.timestamp > since_time,
                DatabaseChange.sync_status == 'pending'
            ).order_by(DatabaseChange.timestamp.asc()).limit(100).all()
        
        change_data = [change.to_dict() for change in changes]
        
        logger.info(f"📤 Sending {len(change_data)} changes to server {requesting_server_id}")
        
        return jsonify({
            'changes': change_data,
            'count': len(change_data),
            'timestamp': datetime.utcnow().isoformat(),
            'server_id': getattr(sync_manager, 'server_id', 'unknown')
        })
        
    except Exception as e:
        logger.error(f"Error getting changes: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/receive-changes', methods=['POST'])
def receive_changes():
    """Receive and apply changes from another server for simplified sync"""
    try:
        data = request.get_json()
        
        if not data or 'changes' not in data:
            return jsonify({'error': 'changes data is required'}), 400
        
        changes = data['changes']
        sending_server_id = data.get('server_id', 'unknown')
        catchup_mode = data.get('catchup_mode', False)
        
        if catchup_mode:
            logger.info(f"� CATCH-UP: Receiving {len(changes)} changes from server {sending_server_id}")
        else:
            logger.info(f"�📥 Receiving {len(changes)} changes from server {sending_server_id}")
        
        # Log sample change for debugging
        if changes:
            sample_change = changes[0]
            logger.debug(f"Sample change: {sample_change}")
        
        # Apply changes using simplified sync manager
        from app.utils.simplified_sync import simplified_sync_manager
        result = simplified_sync_manager._apply_remote_changes(changes)
        
        if result['success']:
            applied_count = result.get('applied_count', 0)
            errors = result.get('errors', [])
            
            if catchup_mode:
                logger.info(f"✅ CATCH-UP: Successfully applied {applied_count} changes from {sending_server_id}")
            else:
                logger.info(f"✅ Successfully applied {applied_count} changes from {sending_server_id}")
            
            response_data = {
                'success': True,
                'applied_count': applied_count,
                'timestamp': datetime.utcnow().isoformat(),
                'catchup_mode': catchup_mode
            }
            
            if errors:
                response_data['warnings'] = errors
                logger.warning(f"Applied changes with {len(errors)} warnings")
            
            return jsonify(response_data)
        else:
            error_msg = result['error']
            if catchup_mode:
                logger.error(f"❌ CATCH-UP: Failed to apply changes from {sending_server_id}: {error_msg}")
            else:
                logger.error(f"❌ Failed to apply changes from {sending_server_id}: {error_msg}")
            return jsonify({'error': error_msg}), 500
            
    except Exception as e:
        logger.error(f"Error receiving changes: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/servers', methods=['GET'])
def get_servers():
    """Get list of configured sync servers"""
    servers = sync_manager.get_sync_servers()
    return jsonify({
        'servers': [server.to_dict() for server in servers],
        'count': len(servers)
    })


@sync_api.route('/servers', methods=['POST'])
def add_server():
    """Add a new sync server"""
    data = request.get_json()
    
    if not data or not data.get('name') or not data.get('host'):
        return jsonify({'error': 'Name and host are required'}), 400
    
    try:
        server = sync_manager.add_sync_server(
            name=data['name'],
            host=data['host'],
            port=data.get('port', 5000),
            protocol=data.get('protocol', 'https')
        )
        
        return jsonify({
            'message': 'Server added successfully',
            'server': server.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Failed to add server: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/servers/<int:server_id>', methods=['DELETE'])
def remove_server(server_id):
    """Remove a sync server"""
    try:
        if sync_manager.remove_sync_server(server_id):
            return jsonify({'message': 'Server removed successfully'})
        else:
            return jsonify({'error': 'Server not found'}), 404
            
    except Exception as e:
        logger.error(f"Failed to remove server: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/servers/<int:server_id>/ping', methods=['POST'])
def ping_server(server_id):
    """Ping a specific server"""
    server = SyncServer.query.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    try:
        success = sync_manager.ping_server(server)
        return jsonify({
            'success': success,
            'last_ping': server.last_ping.isoformat() if server.last_ping else None,
            'last_error': server.last_error
        })
        
    except Exception as e:
        logger.error(f"Failed to ping server: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/servers/<int:server_id>/sync', methods=['POST'])
def sync_with_server(server_id):
    """Trigger sync with a specific server"""
    server = SyncServer.query.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    data = request.get_json() or {}
    sync_type = data.get('sync_type', 'full')
    
    try:
        sync_manager.sync_with_server(server, sync_type)
        return jsonify({'message': f'Sync initiated with {server.name}'})
        
    except Exception as e:
        logger.error(f"Failed to sync with server: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/sync/all', methods=['POST'])
def sync_all_servers():
    """Trigger sync with all servers"""
    try:
        sync_manager.sync_all_servers()
        return jsonify({'message': 'Sync initiated with all servers'})
        
    except Exception as e:
        logger.error(f"Failed to sync with all servers: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/sync/force', methods=['POST'])
def force_full_sync():
    """Force a full sync with all servers"""
    data = request.get_json() or {}
    server_id = data.get('server_id')
    
    try:
        sync_manager.force_full_sync(server_id)
        return jsonify({'message': 'Full sync initiated'})
        
    except Exception as e:
        logger.error(f"Failed to force full sync: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/status', methods=['GET'])
def get_enhanced_sync_status():
    """Get enhanced sync status including file sync reliability metrics"""
    try:
        # Get database sync status
        database_status = sync_manager.get_sync_status()
        
        # Get file sync status
        try:
            from app.utils.real_time_file_sync import get_file_sync_status
            file_sync_status = get_file_sync_status()
        except ImportError as e:
            logger.warning(f"File sync module not available: {e}")
            file_sync_status = {
                'active': False,
                'message': 'File sync module not available'
            }
        except Exception as e:
            logger.error(f"Error getting file sync status: {e}")
            file_sync_status = {
                'active': False,
                'error': str(e),
                'message': 'Error getting file sync status'
            }
        
        # Get active servers count
        active_servers = SyncServer.query.filter_by(is_active=True).count()
        
        # Calculate overall health
        overall_health = 'healthy'
        if not database_status.get('active', False) or not file_sync_status.get('active', False):
            overall_health = 'degraded'
        elif file_sync_status.get('statistics', {}).get('failed_syncs_queue', 0) > 10:
            overall_health = 'warning'
        
        enhanced_status = {
            'overall_health': overall_health,
            'timestamp': datetime.utcnow().isoformat(),
            'active_servers': active_servers,
            'database_sync': database_status,
            'file_sync': file_sync_status,
            'reliability_features': {
                'retry_logic': True,
                'conflict_resolution': True,
                'error_recovery': True,
                'change_detection': True,
                'performance_monitoring': True,
                'debouncing': True
            }
        }
        
        return jsonify(enhanced_status)
        
    except Exception as e:
        logger.error(f"Failed to get enhanced sync status: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat(),
            'overall_health': 'error'
        }), 500


@sync_api.route('/sync/status', methods=['GET'])
def get_sync_status():
    """Get current sync status (legacy endpoint)"""
    try:
        status = sync_manager.get_sync_status()
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Failed to get sync status: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/logs', methods=['GET'])
def get_sync_logs():
    """Get sync operation logs"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        server_id = request.args.get('server_id')
        
        query = SyncLog.query
        if server_id:
            query = query.filter_by(server_id=server_id)
        
        logs = query.order_by(SyncLog.started_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'logs': [log.to_dict() for log in logs.items],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': logs.total,
                'pages': logs.pages
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get sync logs: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/files/upload', methods=['POST'])
def upload_file():
    """Upload a file to the server (excludes database files for safety)"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    file_path = request.form.get('path')
    base_folder = request.form.get('base_folder', 'instance')
    server_id = request.form.get('server_id')
    
    if not file_path:
        return jsonify({'error': 'File path is required'}), 400
    
    try:
        # Security check: block database files
        filename = os.path.basename(file_path).lower()
        file_ext = os.path.splitext(filename)[1]
        
        excluded_extensions = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.lock'}
        excluded_files = {'app.db', 'database.db', 'scouting.db', 'app.db-wal', 'app.db-shm'}
        
        if (file_ext in excluded_extensions or 
            filename in excluded_files or
            filename.endswith('.db-wal') or
            filename.endswith('.db-shm')):
            return jsonify({'error': 'Database files cannot be synced via file upload'}), 403
        
        # Secure the filename
        filename = secure_filename(os.path.basename(file_path))
        
        # Determine destination directory
        if base_folder == 'instance':
            dest_dir = current_app.instance_path
        elif base_folder == 'config':
            dest_dir = os.path.join(os.getcwd(), 'config')
        elif base_folder == 'uploads':
            dest_dir = os.path.join(os.getcwd(), 'uploads')
        else:
            return jsonify({'error': 'Invalid base folder'}), 400
        
        # Create full destination path
        dest_path = os.path.join(dest_dir, file_path)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Save the file
        file.save(dest_path)
        
        # Calculate checksum
        with open(dest_path, 'rb') as f:
            content = f.read()
            checksum = hashlib.sha256(content).hexdigest()
        
        # Update file checksum record
        stat = os.stat(dest_path)
        FileChecksum.get_or_create(
            file_path, checksum, stat.st_size,
            datetime.fromtimestamp(stat.st_mtime)
        )
        db.session.commit()
        
        logger.info(f"File uploaded: {file_path} from server {server_id}")
        
        return jsonify({
            'message': 'File uploaded successfully',
            'path': file_path,
            'checksum': checksum
        })
        
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/files/download', methods=['GET'])
def download_file():
    """Download a file from the server (excludes database files for safety)"""
    file_path = request.args.get('path')
    base_folder = request.args.get('base_folder', 'instance')
    
    if not file_path:
        return jsonify({'error': 'File path is required'}), 400
    
    try:
        # Security check: block database files
        filename = os.path.basename(file_path).lower()
        file_ext = os.path.splitext(filename)[1]
        
        excluded_extensions = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.lock'}
        excluded_files = {'app.db', 'database.db', 'scouting.db', 'app.db-wal', 'app.db-shm'}
        
        if (file_ext in excluded_extensions or 
            filename in excluded_files or
            filename.endswith('.db-wal') or
            filename.endswith('.db-shm')):
            return jsonify({'error': 'Database files cannot be downloaded via file sync'}), 403
        
        # Determine source directory
        if base_folder == 'instance':
            source_dir = current_app.instance_path
        elif base_folder == 'config':
            source_dir = os.path.join(os.getcwd(), 'config')
        elif base_folder == 'uploads':
            source_dir = os.path.join(os.getcwd(), 'uploads')
        else:
            return jsonify({'error': 'Invalid base folder'}), 400
        
        # Create full source path
        source_path = os.path.join(source_dir, file_path)
        
        if not os.path.exists(source_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Security check - ensure path is within allowed directory
        if not os.path.commonpath([source_path, source_dir]) == source_dir:
            return jsonify({'error': 'Invalid file path'}), 400
        
        return send_file(source_path, as_attachment=True, 
                        download_name=os.path.basename(file_path))
        
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/files/delete', methods=['POST'])
def delete_file():
    """Delete a file from the server (excludes database files for safety)"""
    data = request.get_json()
    
    if not data or 'path' not in data:
        return jsonify({'error': 'File path is required'}), 400
    
    file_path = data['path']
    base_folder = data.get('directory', 'instance')
    server_id = data.get('server_id')
    
    try:
        # Security check: block database files
        filename = os.path.basename(file_path).lower()
        file_ext = os.path.splitext(filename)[1]
        
        excluded_extensions = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.lock'}
        excluded_files = {'app.db', 'database.db', 'scouting.db', 'app.db-wal', 'app.db-shm'}
        
        if (file_ext in excluded_extensions or 
            filename in excluded_files or
            filename.endswith('.db-wal') or
            filename.endswith('.db-shm')):
            return jsonify({'error': 'Database files cannot be deleted via file sync'}), 403
        
        # Determine target directory
        if base_folder == 'instance':
            target_dir = current_app.instance_path
        elif base_folder == 'config':
            target_dir = os.path.join(os.getcwd(), 'config')
        elif base_folder == 'uploads':
            target_dir = os.path.join(os.getcwd(), 'uploads')
        else:
            return jsonify({'error': 'Invalid base folder'}), 400
        
        # Create full target path
        target_path = os.path.join(target_dir, file_path)
        
        # Security check - ensure path is within allowed directory
        if not os.path.commonpath([target_path, target_dir]) == target_dir:
            return jsonify({'error': 'Invalid file path'}), 400
        
        if not os.path.exists(target_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Delete the file with improved error handling
        def safe_delete_file(file_path):
            """Safely delete a file with permission handling"""
            import stat
            import time
            
            strategies = [
                # Strategy 1: Simple deletion
                lambda: os.remove(file_path),
                
                # Strategy 2: Change permissions then delete
                lambda: (os.chmod(file_path, stat.S_IWRITE), os.remove(file_path))[1],
                
                # Strategy 3: Wait and retry (in case file is locked)
                lambda: (time.sleep(0.5), os.remove(file_path))[1]
            ]
            
            last_error = None
            for i, strategy in enumerate(strategies, 1):
                try:
                    strategy()
                    return True, f"Deleted successfully (method {i})"
                except PermissionError as e:
                    last_error = f"Permission denied: {e}"
                    if i < len(strategies):
                        continue
                except Exception as e:
                    last_error = str(e)
                    if i < len(strategies):
                        continue
            
            return False, last_error
        
        # Attempt safe deletion
        success, message = safe_delete_file(target_path)
        
        if not success:
            logger.error(f"Failed to delete file {file_path}: {message}")
            return jsonify({'error': f'Could not delete file: {message}'}), 500
        
        # Remove from file checksum tracking
        try:
            file_checksum = FileChecksum.query.filter_by(file_path=file_path).first()
            if file_checksum:
                db.session.delete(file_checksum)
                db.session.commit()
        except Exception as e:
            logger.warning(f"Could not remove file checksum record: {e}")
        
        logger.info(f"File deleted: {file_path} (requested by server {server_id})")
        
        return jsonify({
            'message': 'File deleted successfully',
            'path': file_path
        })
        
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/database', methods=['POST'])
def receive_database_changes():
    """Receive database changes from another server"""
    data = request.get_json()
    
    if not data or 'changes' not in data:
        return jsonify({'error': 'Changes data is required'}), 400
    
    changes = data['changes']
    server_id = data.get('server_id')
    timestamp = data.get('timestamp')
    
    try:
        # Apply the database changes
        sync_manager._apply_database_changes(changes)
        
        logger.info(f"Applied {len(changes)} database changes from server {server_id}")
        
        return jsonify({
            'message': 'Database changes applied successfully',
            'changes_applied': len(changes)
        })
        
    except Exception as e:
        logger.error(f"Failed to apply database changes: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/database/changes', methods=['GET'])
def get_database_changes():
    """Get database changes since a specific timestamp"""
    since = request.args.get('since')
    
    try:
        since_timestamp = None
        if since:
            since_timestamp = datetime.fromisoformat(since)
        
        changes = sync_manager._get_database_changes_since(since_timestamp)
        
        return jsonify({
            'changes': changes,
            'timestamp': datetime.utcnow().isoformat(),
            'count': len(changes)
        })
        
    except Exception as e:
        logger.error(f"Failed to get database changes: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/config', methods=['GET'])
def get_sync_config():
    """Get sync configuration"""
    try:
        config = {
            'sync_enabled': SyncConfig.get_value('sync_enabled', True),
            'sync_interval': SyncConfig.get_value('sync_interval', 30),
            'file_watch_interval': SyncConfig.get_value('file_watch_interval', 5),
            'server_id': sync_manager.server_id
        }
        return jsonify(config)
        
    except Exception as e:
        logger.error(f"Failed to get sync config: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/config', methods=['POST'])
def update_sync_config():
    """Update sync configuration"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Configuration data is required'}), 400
    
    try:
        # Update configuration values
        if 'sync_enabled' in data:
            SyncConfig.set_value('sync_enabled', data['sync_enabled'], 'boolean')
            sync_manager.sync_enabled = data['sync_enabled']
        
        if 'sync_interval' in data:
            SyncConfig.set_value('sync_interval', data['sync_interval'], 'integer')
            sync_manager.sync_interval = data['sync_interval']
        
        if 'file_watch_interval' in data:
            SyncConfig.set_value('file_watch_interval', data['file_watch_interval'], 'integer')
            sync_manager.file_watch_interval = data['file_watch_interval']
        
        return jsonify({'message': 'Configuration updated successfully'})
        
    except Exception as e:
        logger.error(f"Failed to update sync config: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/update', methods=['POST'])
def trigger_remote_update():
    """Trigger a remote update on this server.

    Expected JSON: { "zip_url": "https://.../main.zip", "use_waitress": true, "port": 8080 }
    This endpoint spawns a background process to perform the update asynchronously and
    returns 202 Accepted.
    """
    data = request.get_json() or {}
    zip_url = data.get('zip_url')
    use_waitress = bool(data.get('use_waitress', True))
    port = int(data.get('port', 8080))

    if not zip_url:
        return jsonify({'error': 'zip_url is required'}), 400

    # Spawn background updater process
    try:
        repo_root = Path(__file__).resolve().parent.parent
        
        # Try multiple possible locations for the updater script
        possible_updater_paths = [
            repo_root / 'app' / 'utils' / 'remote_updater.py',  # New location
            repo_root / 'remote_updater.py',  # Fallback: root directory
            repo_root / 'simple_remote_updater.py',  # Simple fallback updater
            repo_root / 'utils' / 'remote_updater.py'  # Alternative location
        ]
        
        updater = None
        for path in possible_updater_paths:
            if path.exists():
                updater = path
                break
        
        if not updater:
            # List available files for debugging
            available_files = []
            try:
                for p in repo_root.rglob('*updater*.py'):
                    available_files.append(str(p.relative_to(repo_root)))
            except:
                pass
            
            error_msg = f'Updater script not found. Searched: {[str(p.relative_to(repo_root)) for p in possible_updater_paths]}'
            if available_files:
                error_msg += f'. Available files: {available_files}'
            
            return jsonify({'error': error_msg}), 500

        cmd = [sys.executable, str(updater), '--zip-url', zip_url, '--port', str(port)]
        if use_waitress:
            cmd.append('--use-waitress')

        # Log the update attempt
        logger.info(f"Starting update from {zip_url} on port {port} (waitress: {use_waitress})")
        logger.info(f"Using updater script: {updater}")

        # Create a log file for the update process
        log_file = repo_root / 'instance' / 'update_log.txt'
        log_file.parent.mkdir(exist_ok=True)
        
        # Spawn detached background process with logging
        with open(log_file, 'w') as f:
            f.write(f"Update started at {datetime.utcnow()}\n")
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Working directory: {repo_root}\n")
            f.write("=" * 50 + "\n")
            f.flush()
            
            process = subprocess.Popen(cmd, 
                                     stdout=f, 
                                     stderr=subprocess.STDOUT,  # Combine stderr with stdout
                                     cwd=str(repo_root),
                                     close_fds=True)
        
        logger.info(f"Update process started with PID {process.pid}, logging to {log_file}")

        return jsonify({
            'message': 'Update started', 
            'zip_url': zip_url,
            'port': port,
            'use_waitress': use_waitress,
            'note': 'Sync server configuration will be preserved during update'
        }), 202
    except Exception as e:
        logger.error(f"Failed to start updater: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/catchup/scan', methods=['POST'])
def trigger_catchup_scan():
    """Trigger a catch-up scan to detect and sync offline servers"""
    try:
        from app.utils.catchup_sync import catchup_sync_manager
        
        # Run catch-up scan in background
        results = catchup_sync_manager.run_automatic_catchup()
        
        return jsonify({
            'message': 'Catch-up scan completed',
            'servers_processed': len(results) if results else 0,
            'results': results or [],
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Failed to run catch-up scan: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/catchup/status', methods=['GET'])
def get_catchup_status():
    """Get status of catch-up synchronization system"""
    try:
        from app.utils.catchup_sync import catchup_sync_manager
        
        # Get servers needing catch-up (missing latest data)
        servers_needing_catchup = catchup_sync_manager.detect_servers_needing_catchup()
        
        # Get recent sync logs for catch-up operations
        recent_logs = SyncLog.query.filter(
            SyncLog.created_at >= datetime.utcnow() - timedelta(hours=24)
        ).order_by(SyncLog.created_at.desc()).limit(50).all()
        
        catchup_logs = [log for log in recent_logs if 'catch-up' in log.operation.lower()]
        
        return jsonify({
            'catchup_enabled': catchup_sync_manager.catchup_enabled,
            'max_catchup_days': catchup_sync_manager.max_catchup_days,
            'servers_needing_catchup': [{
                'id': server.id,
                'name': server.name,
                'host': server.host,
                'last_sync': server.last_sync.isoformat() if server.last_sync else None,
                'last_ping': server.last_ping.isoformat() if server.last_ping else None,
                'ping_success': server.ping_success
            } for server in servers_needing_catchup],
            'recent_catchup_logs': [{
                'id': log.id,
                'server_name': log.server.name if log.server else 'Unknown',
                'operation': log.operation,
                'status': log.status,
                'created_at': log.created_at.isoformat(),
                'details': log.details
            } for log in catchup_logs[:10]],
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Failed to get catch-up status: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/files/checksums', methods=['GET'])
def get_file_checksums():
    """Get file checksums for a directory - enhanced for catch-up mode"""
    try:
        path = request.args.get('path', 'instance')
        catchup_mode = request.args.get('catchup_mode', 'false').lower() == 'true'
        since_param = request.args.get('since')
        
        # Determine directory path
        if path == 'instance':
            directory_path = current_app.instance_path
        elif path == 'config':
            directory_path = os.path.join(os.getcwd(), 'config')
        elif path == 'uploads':
            directory_path = os.path.join(os.getcwd(), 'uploads')
        else:
            return jsonify({'error': 'Invalid path'}), 400
        
        if not os.path.exists(directory_path):
            return jsonify({})
        
        checksums = {}
        
        # Files to exclude from sync
        excluded_extensions = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.lock'}
        excluded_files = {'app.db', 'database.db', 'scouting.db', 'app.db-wal', 'app.db-shm'}
        
        # Parse since timestamp for catch-up mode
        since_time = None
        if catchup_mode and since_param:
            try:
                since_time = datetime.fromisoformat(since_param.replace('Z', '+00:00'))
            except ValueError:
                return jsonify({'error': 'Invalid since timestamp format'}), 400
        
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, directory_path)
                
                # Skip database files and lock files
                file_lower = file.lower()
                file_ext = os.path.splitext(file_lower)[1]
                
                if (file_ext in excluded_extensions or 
                    file_lower in excluded_files or
                    file_lower.endswith('.db-wal') or
                    file_lower.endswith('.db-shm')):
                    continue
                
                try:
                    stat = os.stat(file_path)
                    file_modified = datetime.fromtimestamp(stat.st_mtime)
                    
                    # In catch-up mode, only include files modified since specified time
                    if catchup_mode and since_time and file_modified <= since_time:
                        continue
                    
                    with open(file_path, 'rb') as f:
                        content = f.read()
                        checksum = hashlib.sha256(content).hexdigest()
                    
                    checksums[relative_path] = {
                        'checksum': checksum,
                        'size': stat.st_size,
                        'modified': file_modified.isoformat()
                    }
                except Exception as e:
                    logger.warning(f"Could not process file {file_path}: {e}")
        
        return jsonify(checksums)
        
    except Exception as e:
        logger.error(f"Failed to get file checksums: {e}")
        return jsonify({'error': str(e)}), 500


@sync_api.route('/universal_receive', methods=['POST'])
def universal_sync_receive():
    """
    Universal sync receiver for ALL database and file changes
    Handles real-time sync from the Universal Real-Time Sync System
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        changes = data.get('changes', [])
        source_server = data.get('source_server', 'unknown')
        
        if not changes:
            return jsonify({'error': 'No changes provided'}), 400
        
        # Process each change
        results = []
        for change in changes:
            try:
                result = _process_universal_change(change, source_server)
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing change: {e}")
                results.append({'status': 'error', 'error': str(e)})
        
        # Count results
        success_count = sum(1 for r in results if r.get('status') == 'success')
        error_count = len(results) - success_count
        
        response = {
            'status': 'processed',
            'total_changes': len(changes),
            'successful': success_count,
            'errors': error_count,
            'source_server': source_server,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        logger.info(f"Universal sync: processed {success_count}/{len(changes)} changes from {source_server}")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Universal sync receive error: {e}")
        return jsonify({'error': str(e)}), 500


def _process_universal_change(change, source_server):
    """Process a single universal sync change"""
    change_type = change.get('type')
    
    if change_type == 'database':
        return _process_database_change(change, source_server)
    elif change_type == 'file':
        return _process_file_change(change, source_server)
    else:
        return {'status': 'error', 'error': f'Unknown change type: {change_type}'}


def _process_database_change(change, source_server):
    """Process a database change from universal sync"""
    try:
        from app.utils.change_tracking import disable_change_tracking, enable_change_tracking
        
        # Temporarily disable change tracking to avoid loops
        disable_change_tracking()
        
        try:
            table_name = change.get('table_name')
            operation = change.get('operation')
            record_id = change.get('record_id')
            new_data = change.get('new_data')
            old_data = change.get('old_data')
            
            # Get the model class
            model_class = _get_model_class(table_name)
            if not model_class:
                return {'status': 'error', 'error': f'Unknown table: {table_name}'}
            
            # Apply the change based on operation
            if operation == 'insert':
                return _apply_insert(model_class, new_data)
            elif operation == 'update' or operation == 'soft_delete' or operation == 'restore':
                return _apply_update(model_class, record_id, new_data)
            elif operation == 'delete':
                return _apply_delete(model_class, record_id, old_data)
            else:
                return {'status': 'error', 'error': f'Unknown operation: {operation}'}
                
        finally:
            enable_change_tracking()
            
    except Exception as e:
        logger.error(f"Error processing database change: {e}")
        return {'status': 'error', 'error': str(e)}


def _process_file_change(change, source_server):
    """Process a file change from universal sync"""
    try:
        file_path = change.get('file_path')
        content = change.get('content')
        file_hash = change.get('file_hash')
        
        if not file_path or content is None:
            return {'status': 'error', 'error': 'Missing file path or content'}
        
        # Convert relative path to absolute
        if not os.path.isabs(file_path):
            app_root = Path(current_app.root_path).parent
            full_path = app_root / file_path
        else:
            full_path = Path(file_path)
        
        # Ensure directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if it's base64 encoded (binary file)
        try:
            import base64
            # Try to decode as base64
            binary_content = base64.b64decode(content)
            # Write as binary
            with open(full_path, 'wb') as f:
                f.write(binary_content)
        except:
            # Write as text
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # Verify hash if provided
        if file_hash:
            actual_hash = hashlib.sha256(open(full_path, 'rb').read()).hexdigest()
            if actual_hash != file_hash:
                logger.warning(f"File hash mismatch for {file_path}: expected {file_hash}, got {actual_hash}")
        
        logger.info(f"File synced: {file_path}")
        return {'status': 'success', 'file': str(file_path)}
        
    except Exception as e:
        logger.error(f"Error processing file change: {e}")
        return {'status': 'error', 'error': str(e)}


def _get_model_class(table_name):
    """Get model class by table name"""
    try:
        from app.models import (
            User, Role, ScoutingTeamSettings, Team, Event, Match,
            StrategyShare, ScoutingData, TeamListEntry, AllianceSelection,
            SyncServer, SyncLog, DatabaseChange, FileChecksum, SyncConfig
        )
        
        model_map = {}
        for model in [User, Role, ScoutingTeamSettings, Team, Event, Match,
                     StrategyShare, ScoutingData, TeamListEntry, AllianceSelection,
                     SyncServer, SyncLog, DatabaseChange, FileChecksum, SyncConfig]:
            if hasattr(model, '__tablename__'):
                model_map[model.__tablename__] = model
        
        return model_map.get(table_name)
    except Exception as e:
        logger.error(f"Error getting model class for {table_name}: {e}")
        return None


def _apply_insert(model_class, data):
    """Apply an insert operation"""
    try:
        # Create new instance
        instance = model_class()
        
        # Set attributes from data
        for key, value in data.items():
            if hasattr(instance, key):
                # Handle datetime fields
                if isinstance(value, str) and key.endswith(('_at', '_time', 'timestamp')):
                    try:
                        value = datetime.fromisoformat(value)
                    except:
                        pass
                setattr(instance, key, value)
        
        db.session.add(instance)
        db.session.commit()
        
        return {'status': 'success', 'operation': 'insert', 'id': getattr(instance, 'id', None)}
    except Exception as e:
        db.session.rollback()
        logger.error(f"Insert error: {e}")
        return {'status': 'error', 'error': str(e)}


def _apply_update(model_class, record_id, data):
    """Apply an update operation"""
    try:
        # Find existing record
        instance = model_class.query.get(record_id)
        if not instance:
            # Record doesn't exist, create it
            return _apply_insert(model_class, data)
        
        # Update attributes from data
        for key, value in data.items():
            if hasattr(instance, key):
                # Handle datetime fields
                if isinstance(value, str) and key.endswith(('_at', '_time', 'timestamp')):
                    try:
                        value = datetime.fromisoformat(value)
                    except:
                        pass
                setattr(instance, key, value)
        
        db.session.commit()
        
        return {'status': 'success', 'operation': 'update', 'id': record_id}
    except Exception as e:
        db.session.rollback()
        logger.error(f"Update error: {e}")
        return {'status': 'error', 'error': str(e)}


def _apply_delete(model_class, record_id, old_data):
    """Apply a delete operation"""
    try:
        # Find and delete record
        instance = model_class.query.get(record_id)
        if instance:
            db.session.delete(instance)
            db.session.commit()
            return {'status': 'success', 'operation': 'delete', 'id': record_id}
        else:
            return {'status': 'success', 'operation': 'delete', 'id': record_id, 'note': 'already deleted'}
    except Exception as e:
        db.session.rollback()
        logger.error(f"Delete error: {e}")
        return {'status': 'error', 'error': str(e)}


# Error handlers
@sync_api.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@sync_api.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500
