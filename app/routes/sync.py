"""
Sync Routes
Handles synchronization endpoints for multi-server communication
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from app.models import db
from app.utils.decorators import admin_required, superadmin_required, role_required
import json
import traceback

bp = Blueprint('sync', __name__, url_prefix='/sync')

@bp.route('/status', methods=['GET'])
@login_required
@role_required('admin')
def sync_status():
    """Get synchronization status"""
    try:
        return jsonify({
            'status': 'active',
            'server_id': current_app.config.get('SERVER_ID', 'unknown'),
            'timestamp': str(db.func.now())
        })
    except Exception as e:
        current_app.logger.error(f"Sync status error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/health', methods=['GET'])
def sync_health():
    """Health check endpoint for sync monitoring"""
    try:
        # Simple health check
        db.session.execute(db.text('SELECT 1')).fetchone()
        return jsonify({
            'status': 'healthy',
            'timestamp': str(db.func.now())
        })
    except Exception as e:
        current_app.logger.error(f"Sync health check error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/ping', methods=['GET', 'POST'])
def sync_ping():
    """Simple ping endpoint for connectivity testing"""
    return jsonify({
        'pong': True,
        'timestamp': str(db.func.now())
    })

@bp.route('/data', methods=['POST'])
@login_required
@role_required('admin')
def sync_data():
    """Handle data synchronization"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Log the sync operation
        current_app.logger.info(f"Sync data received from {request.remote_addr}")
        
        # TODO: Implement actual data sync logic here
        # For now, just acknowledge receipt
        return jsonify({
            'status': 'received',
            'records_processed': len(data.get('records', [])),
            'timestamp': str(db.func.now())
        })
    
    except Exception as e:
        current_app.logger.error(f"Sync data error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/lock', methods=['POST'])
@login_required
@role_required('admin')
def acquire_lock():
    """Acquire a synchronization lock"""
    try:
        data = request.get_json()
        lock_name = data.get('lock_name', 'default')
        
        # Simple lock mechanism - store in application config
        locks = current_app.config.setdefault('SYNC_LOCKS', {})
        
        if lock_name in locks:
            return jsonify({
                'acquired': False,
                'locked_by': locks[lock_name]['owner'],
                'message': f'Lock {lock_name} already held'
            }), 409
        
        locks[lock_name] = {
            'owner': current_user.username,
            'timestamp': str(db.func.now())
        }
        
        return jsonify({
            'acquired': True,
            'lock_name': lock_name,
            'owner': current_user.username
        })
    
    except Exception as e:
        current_app.logger.error(f"Lock acquisition error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/unlock', methods=['POST'])
@login_required
@role_required('admin')
def release_lock():
    """Release a synchronization lock"""
    try:
        data = request.get_json()
        lock_name = data.get('lock_name', 'default')
        
        locks = current_app.config.get('SYNC_LOCKS', {})
        
        if lock_name not in locks:
            return jsonify({
                'released': False,
                'message': f'Lock {lock_name} not found'
            }), 404
        
        lock_owner = locks[lock_name]['owner']
        if lock_owner != current_user.username and not current_user.has_role('superadmin'):
            return jsonify({
                'released': False,
                'message': f'Lock {lock_name} owned by {lock_owner}'
            }), 403
        
        del locks[lock_name]
        
        return jsonify({
            'released': True,
            'lock_name': lock_name
        })
    
    except Exception as e:
        current_app.logger.error(f"Lock release error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/locks', methods=['GET'])
@login_required
@role_required('admin')
def list_locks():
    """List all active synchronization locks"""
    try:
        locks = current_app.config.get('SYNC_LOCKS', {})
        return jsonify({
            'locks': locks,
            'count': len(locks)
        })
    except Exception as e:
        current_app.logger.error(f"List locks error: {e}")
        return jsonify({'error': str(e)}), 500
