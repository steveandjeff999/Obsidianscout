"""
Real-time Replication Management Routes
Web interface for managing real-time database replication
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app.models import SyncServer
from app.utils.real_time_replication import real_time_replicator
import logging

logger = logging.getLogger(__name__)

def require_superadmin(f):
    """Decorator to require superadmin role only"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        # Only allow superadmin
        user_roles = [role.name for role in current_user.roles]
        if 'superadmin' not in user_roles:
            flash('You need superadmin privileges to access this page.', 'error')
            return redirect(url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function

realtime_routes = Blueprint('realtime', __name__, url_prefix='/realtime')

@realtime_routes.route('/test')
def test_page():
    """Test page to verify template rendering"""
    return render_template('realtime/dashboard.html', 
                         servers=[], 
                         status={'enabled': True, 'queue_size': 0, 'active_servers': 0})

@realtime_routes.route('/dashboard')
@login_required
@require_superadmin
def dashboard():
    """Real-time replication dashboard"""
    servers = SyncServer.query.filter_by(sync_enabled=True).all()
    
    # Get replication status
    status = {
        'enabled': real_time_replicator.running,
        'queue_size': real_time_replicator.replication_queue.qsize() if real_time_replicator.running else 0,
        'active_servers': len(servers)
    }
    
    return render_template('realtime/dashboard.html', 
                         servers=servers, 
                         status=status)

@realtime_routes.route('/enable', methods=['POST'])
@login_required
@require_superadmin
def enable_replication():
    """Enable real-time replication"""
    try:
        if not real_time_replicator.running:
            real_time_replicator.start()
            flash('✅ Real-time replication enabled', 'success')
        else:
            flash('⚠️ Real-time replication is already running', 'warning')
    except Exception as e:
        logger.error(f"Error enabling replication: {e}")
        flash(f'❌ Error enabling replication: {str(e)}', 'error')
    
    return redirect(url_for('realtime.dashboard'))

@realtime_routes.route('/disable', methods=['POST'])
@login_required
@require_superadmin
def disable_replication():
    """Disable real-time replication"""
    try:
        if real_time_replicator.running:
            real_time_replicator.stop()
            flash('🛑 Real-time replication disabled', 'info')
        else:
            flash('⚠️ Real-time replication is already stopped', 'warning')
    except Exception as e:
        logger.error(f"Error disabling replication: {e}")
        flash(f'❌ Error disabling replication: {str(e)}', 'error')
    
    return redirect(url_for('realtime.dashboard'))

@realtime_routes.route('/status', methods=['GET'])
@login_required
@require_superadmin
def get_status():
    """Get real-time replication status as JSON"""
    servers = SyncServer.query.filter_by(sync_enabled=True).all()
    
    status = {
        'enabled': getattr(real_time_replicator, 'enabled', False),
        'worker_running': real_time_replicator.is_worker_running() if hasattr(real_time_replicator, 'is_worker_running') else real_time_replicator.running,
        'queue_size': real_time_replicator.get_queue_size() if hasattr(real_time_replicator, 'get_queue_size') else real_time_replicator.replication_queue.qsize(),
        'active_servers': len(servers),
        'servers': [
            {
                'id': server.id,
                'name': server.name,
                'host': server.host,
                'port': server.port,
                'status': 'active' if server.is_active else 'inactive',
                'sync_enabled': server.sync_enabled,
                'is_primary': server.is_primary,
                'last_sync': server.last_sync.isoformat() if server.last_sync else None,
                'last_ping': server.last_ping.isoformat() if server.last_ping else None
            }
            for server in servers
        ]
    }
    
    return jsonify(status)

@realtime_routes.route('/test-connection/<int:server_id>', methods=['POST'])
@login_required
@require_superadmin
def test_connection(server_id):
    """Test connection to a specific server"""
    try:
        import requests
        from datetime import datetime
        
        server = SyncServer.query.get_or_404(server_id)
        url = f"{server.protocol}://{server.host}:{server.port}/api/realtime/ping"
        
        response = requests.get(url, timeout=5, verify=False)
        
        if response.status_code == 200:
            server.is_active = True
            server.last_ping = datetime.utcnow()
            from app import db
            db.session.commit()
            
            flash(f'✅ Connection to {server.name} successful', 'success')
        else:
            server.is_active = False
            from app import db
            db.session.commit()
            
            flash(f'❌ Connection to {server.name} failed: HTTP {response.status_code}', 'error')
            
    except Exception as e:
        server.is_active = False
        server.last_ping = datetime.utcnow()
        from app import db
        db.session.commit()
        
        logger.error(f"Connection test failed for server {server_id}: {e}")
        flash(f'❌ Connection test failed: {str(e)}', 'error')
    
    return redirect(url_for('realtime.dashboard'))
