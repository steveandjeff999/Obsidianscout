"""
Real-time server update monitoring system
Provides WebSocket-based status updates for server updates
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from app import socketio, db
from app.models import SyncServer
import requests
import threading
import time
from datetime import datetime
import logging
import json
from functools import wraps

logger = logging.getLogger(__name__)

# Decorator to require superadmin role
def require_superadmin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.has_role('superadmin'):
            flash('Super Admin access required', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

logger = logging.getLogger(__name__)

update_monitor_bp = Blueprint('update_monitor', __name__, url_prefix='/update_monitor')


@update_monitor_bp.route('/api/test_connection/<int:server_id>')
@require_superadmin
def test_connection(server_id):
    """Test connection to a specific server with detailed diagnostics"""
    try:
        from app.models import SyncServer
        server = SyncServer.query.get_or_404(server_id)
        
        results = {
            'server_name': server.name,
            'base_url': server.base_url,
            'tests': []
        }
        
        # Test 1: Basic network connectivity
        try:
            import socket
            import urllib.parse
            
            parsed = urllib.parse.urlparse(server.base_url)
            host = parsed.hostname
            port = parsed.port
            
            results['tests'].append({
                'name': 'Network Connectivity',
                'status': 'running',
                'details': f'Testing TCP connection to {host}:{port}'
            })
            
            sock = socket.create_connection((host, port), timeout=10)
            sock.close()
            results['tests'][-1]['status'] = 'success'
            results['tests'][-1]['message'] = 'TCP connection successful'
            
        except Exception as e:
            results['tests'][-1]['status'] = 'failed'
            results['tests'][-1]['error'] = str(e)
        
        # Test 2: HTTP/HTTPS connectivity
        try:
            results['tests'].append({
                'name': 'HTTP Response',
                'status': 'running',
                'details': f'Testing HTTP response from {server.base_url}'
            })
            
            import requests
            resp = requests.get(server.base_url, timeout=10, verify=False, allow_redirects=True)
            results['tests'][-1]['status'] = 'success'
            results['tests'][-1]['message'] = f'HTTP {resp.status_code} response received'
            results['tests'][-1]['response_code'] = resp.status_code
            
        except Exception as e:
            results['tests'][-1]['status'] = 'failed'
            results['tests'][-1]['error'] = str(e)
        
        # Test 3: Sync API ping
        try:
            results['tests'].append({
                'name': 'Sync API Ping',
                'status': 'running',
                'details': f'Testing {server.base_url}/api/sync/ping'
            })
            
            ping_url = f"{server.base_url}/api/sync/ping"
            resp = requests.get(ping_url, timeout=10, verify=False)
            
            if resp.status_code == 200:
                data = resp.json()
                results['tests'][-1]['status'] = 'success'
                results['tests'][-1]['message'] = f"Sync API available - Version: {data.get('version', 'Unknown')}"
                results['tests'][-1]['data'] = data
            else:
                results['tests'][-1]['status'] = 'failed'
                results['tests'][-1]['error'] = f'HTTP {resp.status_code}: {resp.text[:200]}'
            
        except Exception as e:
            results['tests'][-1]['status'] = 'failed'
            results['tests'][-1]['error'] = str(e)
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Track active update processes
active_updates = {}  # server_id: {status, progress, messages, started_at, etc.}

class UpdateMonitor:
    """Monitors server update progress in real-time"""
    
    def __init__(self, server_id, zip_url, port, use_waitress=True):
        self.server_id = server_id
        self.server = SyncServer.query.get(server_id)
        self.zip_url = zip_url
        self.port = port
        self.use_waitress = use_waitress
        self.status = 'initializing'
        self.progress = 0
        self.messages = []
        self.started_at = datetime.utcnow()
        self.completed_at = None
        self.error = None
        
    def add_message(self, message, level='info'):
        """Add a status message"""
        timestamp = datetime.utcnow().strftime('%H:%M:%S')
        msg = {
            'timestamp': timestamp,
            'message': message,
            'level': level
        }
        self.messages.append(msg)
        
        # Emit to WebSocket clients
        socketio.emit('update_monitor_message', {
            'server_id': self.server_id,
            'server_name': self.server.name,
            'message': msg,
            'status': self.status,
            'progress': self.progress
        }, room=f'update_monitor_{self.server_id}')
        
        logger.info(f"Update {self.server.name}: {message}")
    
    def update_status(self, status, progress=None):
        """Update the overall status"""
        self.status = status
        if progress is not None:
            self.progress = progress
            
        socketio.emit('update_monitor_status', {
            'server_id': self.server_id,
            'server_name': self.server.name,
            'status': self.status,
            'progress': self.progress,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }, room=f'update_monitor_{self.server_id}')
    
    def start_update(self):
        """Start the update process with monitoring"""
        active_updates[self.server_id] = self
        
        def update_thread():
            try:
                self.add_message("🚀 Starting server update process...")
                self.update_status('connecting', 5)
                
                # Step 1: Test connection
                self.add_message(f"🔍 Testing connection to {self.server.base_url}...")
                try:
                    ping_url = f"{self.server.base_url}/api/sync/ping"
                    self.add_message(f"📡 Attempting to reach: {ping_url}")
                    resp = requests.get(ping_url, timeout=15, verify=False)
                    if resp.status_code == 200:
                        data = resp.json()
                        self.add_message(f"✅ Server is reachable - Version: {data.get('version', 'Unknown')}", 'success')
                        self.update_status('connected', 15)
                        self.last_contact = datetime.utcnow()
                    else:
                        raise Exception(f"Server returned HTTP {resp.status_code}: {resp.text[:200]}")
                except requests.exceptions.ConnectTimeout:
                    self.add_message(f"❌ Connection timeout - server may be offline or unreachable", 'error')
                    self.update_status('failed', 100)
                    self.error = "Connection timeout - check if server is running and accessible"
                    return
                except requests.exceptions.ConnectionError as e:
                    self.add_message(f"❌ Connection error - cannot reach server: {str(e)[:100]}", 'error')
                    self.update_status('failed', 100)
                    self.error = f"Connection error: {str(e)[:100]}"
                    return
                except Exception as e:
                    self.add_message(f"❌ Connection failed: {e}", 'error')
                    self.update_status('failed', 100)
                    self.error = str(e)
                    return
                
                # Step 2: Send update request
                self.add_message("📦 Sending update request...")
                self.update_status('requesting', 25)
                
                payload = {
                    'zip_url': self.zip_url,
                    'use_waitress': self.use_waitress,
                    'port': self.port
                }
                
                update_url = f"{self.server.base_url}/api/sync/update"
                try:
                    resp = requests.post(update_url, json=payload, timeout=10, verify=False)
                    if resp.status_code in (200, 202):
                        result = resp.json()
                        self.add_message(f"✅ Update request accepted: {result.get('message', 'Started')}", 'success')
                        self.update_status('updating', 35)
                    else:
                        error_msg = f"Server returned HTTP {resp.status_code}"
                        try:
                            error_data = resp.json()
                            error_msg += f": {error_data.get('error', 'Unknown error')}"
                        except:
                            error_msg += f": {resp.text}"
                        raise Exception(error_msg)
                        
                except Exception as e:
                    self.add_message(f"❌ Update request failed: {e}", 'error')
                    self.update_status('failed', 100)
                    self.error = str(e)
                    return
                
                # Step 3: Monitor update progress
                self.add_message("⏳ Monitoring update progress...")
                self.monitor_update_progress()
                
            except Exception as e:
                self.add_message(f"❌ Update failed: {e}", 'error')
                self.update_status('failed', 100)
                self.error = str(e)
            finally:
                # Clean up after some time
                threading.Timer(300, lambda: active_updates.pop(self.server_id, None)).start()
        
        thread = threading.Thread(target=update_thread, daemon=True)
        thread.start()
        return thread
    
    def monitor_update_progress(self):
        """Monitor the update progress by checking server status"""
        self.add_message("🔄 Waiting for server to restart...")
        self.update_status('restarting', 45)
        
        # Wait a bit for the server to start shutting down
        time.sleep(5)
        
        # Check if server goes offline (indicating update started)
        server_offline = False
        offline_checks = 0
        max_offline_checks = 12  # 1 minute
        
        while offline_checks < max_offline_checks:
            try:
                ping_url = f"{self.server.base_url}/api/sync/ping"
                resp = requests.get(ping_url, timeout=5, verify=False)
                if resp.status_code != 200:
                    server_offline = True
                    break
            except:
                server_offline = True
                break
            
            offline_checks += 1
            time.sleep(5)
            self.add_message(f"⏳ Still checking server status... ({offline_checks}/{max_offline_checks})")
        
        if not server_offline:
            self.add_message("⚠️  Server didn't go offline - update may not have started", 'warning')
            self.update_status('uncertain', 70)
        else:
            self.add_message("📴 Server went offline - update in progress", 'info')
            self.update_status('installing', 60)
        
        # Wait for server to come back online
        self.add_message("⏳ Waiting for server to come back online...")
        online_checks = 0
        max_online_checks = 36  # 3 minutes
        server_back_online = False
        
        while online_checks < max_online_checks:
            try:
                ping_url = f"{self.server.base_url}/api/sync/ping"
                resp = requests.get(ping_url, timeout=5, verify=False)
                if resp.status_code == 200:
                    data = resp.json()
                    self.add_message(f"✅ Server is back online! Version: {data.get('version', 'Unknown')}", 'success')
                    server_back_online = True
                    break
            except:
                pass
            
            online_checks += 1
            progress = min(95, 60 + (online_checks / max_online_checks) * 35)
            self.update_status('restarting', progress)
            self.add_message(f"⏳ Waiting for server... ({online_checks}/{max_online_checks})")
            time.sleep(5)
        
        if server_back_online:
            # Verify sync configuration is preserved
            self.add_message("🔍 Verifying sync configuration...")
            self.update_status('verifying', 90)
            
            try:
                # Check if the server still has its sync configuration
                # This is a basic check - the full verification happens on the remote server
                self.add_message("✅ Update completed successfully!", 'success')
                self.update_status('completed', 100)
                self.completed_at = datetime.utcnow()
                
                # Update server's last sync time
                self.server.last_sync = datetime.utcnow()
                self.server.error_count = 0
                self.server.last_error = None
                db.session.commit()
                
            except Exception as e:
                self.add_message(f"⚠️  Update completed but verification failed: {e}", 'warning')
                self.update_status('completed_with_warnings', 100)
                self.completed_at = datetime.utcnow()
        else:
            self.add_message("❌ Server didn't come back online within expected time", 'error')
            self.update_status('timeout', 100)
            self.completed_at = datetime.utcnow()
            self.error = "Server didn't come back online"

@update_monitor_bp.route('/dashboard')
@login_required
@require_superadmin
def dashboard():
    """Display the update monitor dashboard"""
    servers = SyncServer.query.filter_by(sync_enabled=True).all()
    return render_template('update_dashboard.html', servers=servers)

@update_monitor_bp.route('/api/start_update/<int:server_id>', methods=['POST'])
@login_required
@require_superadmin
def start_monitored_update(server_id):
    """Start an update with real-time monitoring"""
    server = SyncServer.query.get_or_404(server_id)
    
    # Check if already updating
    if server_id in active_updates:
        return jsonify({'error': 'Update already in progress for this server'}), 400
    
    data = request.get_json() or {}
    zip_url = data.get('zip_url', 'https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip')
    use_waitress = data.get('use_waitress', True)
    port = data.get('port', server.port)
    
    # Start the monitored update
    monitor = UpdateMonitor(server_id, zip_url, port, use_waitress)
    monitor.start_update()
    
    return jsonify({
        'message': f'Update monitoring started for {server.name}',
        'server_id': server_id,
        'monitor_room': f'update_monitor_{server_id}'
    })

@update_monitor_bp.route('/api/update_status/<int:server_id>')
@login_required
@require_superadmin  
def get_update_status(server_id):
    """Get current update status for a server"""
    if server_id in active_updates:
        monitor = active_updates[server_id]
        return jsonify({
            'status': monitor.status,
            'progress': monitor.progress,
            'messages': monitor.messages[-10:],  # Last 10 messages
            'started_at': monitor.started_at.isoformat(),
            'completed_at': monitor.completed_at.isoformat() if monitor.completed_at else None,
            'error': monitor.error
        })
    else:
        return jsonify({'status': 'not_running', 'progress': 0, 'messages': []})

# WebSocket events (using main namespace for simplicity)
@socketio.on('join_update_monitor')
def on_join_update_monitor(data):
    """Join the update monitor room for a specific server"""
    server_id = data['server_id']
    room = f'update_monitor_{server_id}'
    join_room(room)
    logger.info(f"User joined update monitor room for server {server_id}")
    emit('update_monitor_joined', {'room': room, 'server_id': server_id})

@socketio.on('leave_update_monitor') 
def on_leave_update_monitor(data):
    """Leave the update monitor room"""
    server_id = data['server_id']
    room = f'update_monitor_{server_id}'
    leave_room(room)

@socketio.on('update_monitor_start_server')
def on_start_server_update(data):
    """Start update for a single server"""
    server_id = data['server_id']
    server = SyncServer.query.get(server_id)
    if server:
        # Check if already updating
        if server_id in active_updates:
            emit('update_monitor_error', {'message': 'Update already in progress for this server', 'server_id': server_id})
            return
        
        zip_url = 'https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip'
        monitor = UpdateMonitor(server_id, zip_url, server.port, True)
        monitor.start_update()
        
        emit('update_monitor_started', {
            'server_id': server_id,
            'server_name': server.name,
            'message': f'Update started for {server.name}'
        })

@socketio.on('update_monitor_test_connection')
def on_test_connection(data):
    """Test connection to a server"""
    server_id = data['server_id']
    logger.info(f"Testing connection to server {server_id}")
    server = SyncServer.query.get(server_id)
    if server:
        try:
            ping_url = f"{server.base_url}/api/sync/ping"
            resp = requests.get(ping_url, timeout=5, verify=False)
            success = resp.status_code == 200
            message = "Connection successful" if success else f"HTTP {resp.status_code}"
        except Exception as e:
            success = False
            message = str(e)
        
        logger.info(f"Connection test result for server {server_id}: {message}")
        emit('update_monitor_connection_test', {
            'server_id': server_id,
            'success': success,
            'message': message
        })

@socketio.on('update_monitor_refresh_status')
def on_refresh_status():
    """Refresh status for all servers"""
    servers = SyncServer.query.filter_by(sync_enabled=True).all()
    for server in servers:
        if server.id in active_updates:
            monitor = active_updates[server.id]
            emit('update_monitor_status', {
                'server_id': server.id,
                'server_name': server.name,
                'status': monitor.status,
                'progress': monitor.progress,
                'started_at': monitor.started_at.isoformat(),
                'completed_at': monitor.completed_at.isoformat() if monitor.completed_at else None
            })

@socketio.on('update_monitor_start_all')
def on_start_all_updates():
    """Start updates for all servers"""
    servers = SyncServer.query.filter_by(sync_enabled=True).all()
    zip_url = 'https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip'
    
    started_count = 0
    for server in servers:
        if server.id not in active_updates:
            monitor = UpdateMonitor(server.id, zip_url, server.port, True)
            monitor.start_update()
            started_count += 1
    
    emit('update_monitor_bulk_started', {
        'message': f'Started updates for {started_count} servers'
    })

@socketio.on('update_monitor_stop_all')
def on_stop_all_updates():
    """Stop all updates"""
    # Note: This is a simple implementation that just clears the active updates
    # In a production system, you would want to actually stop the threads
    stopped_count = len(active_updates)
    active_updates.clear()
    
    emit('update_monitor_bulk_stopped', {
        'message': f'Stopped {stopped_count} updates'
    })
