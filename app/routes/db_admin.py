"""
Database Administration Routes for Concurrent SQLite Operations

This module provides admin routes to monitor and manage the concurrent
database operations, including CR-SQLite status and connection pool statistics.
"""

from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.utils.database_manager import concurrent_db_manager
from app.utils.concurrent_models import with_concurrent_db
import logging

logger = logging.getLogger(__name__)

# Create blueprint
db_admin_bp = Blueprint('db_admin', __name__, url_prefix='/admin/database')

@db_admin_bp.route('/')
@login_required
def database_status():
    """Display database status and concurrent operations info"""
    if not current_user.has_role('superadmin'):
        flash('Super Admin access required', 'error')
        return redirect(url_for('main.index'))
    
    try:
        # Get database information
        db_info = concurrent_db_manager.get_database_info()
        
        # Get connection pool stats
        pool_stats = concurrent_db_manager.get_connection_stats()
        
        return render_template('admin/database_status.html',
                             db_info=db_info,
                             pool_stats=pool_stats)
    except Exception as e:
        logger.error(f"Error getting database status: {e}")
        flash(f'Error retrieving database status: {str(e)}', 'error')
        return redirect(url_for('main.index'))

@db_admin_bp.route('/api/status')
@login_required
def api_database_status():
    """API endpoint for database status (for AJAX updates)"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        db_info = concurrent_db_manager.get_database_info()
        pool_stats = concurrent_db_manager.get_connection_stats()
        
        return jsonify({
            'success': True,
            'database_info': db_info,
            'pool_stats': pool_stats
        })
    except Exception as e:
        logger.error(f"Error getting database status via API: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@db_admin_bp.route('/optimize', methods=['POST'])
@login_required
def optimize_database():
    """Optimize the database for better concurrent performance"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        concurrent_db_manager.optimize_database()
        flash('Database optimization completed successfully', 'success')
        return jsonify({'success': True, 'message': 'Database optimized'})
    except Exception as e:
        logger.error(f"Error optimizing database: {e}")
        return jsonify({
            'success': False,
            'error': f'Optimization failed: {str(e)}'
        }), 500

@db_admin_bp.route('/enable-wal', methods=['POST'])
@login_required
def enable_wal_mode():
    """Enable WAL mode for better concurrency"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        concurrent_db_manager.enable_wal_mode()
        flash('WAL mode enabled successfully', 'success')
        return jsonify({'success': True, 'message': 'WAL mode enabled'})
    except Exception as e:
        logger.error(f"Error enabling WAL mode: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to enable WAL mode: {str(e)}'
        }), 500

@db_admin_bp.route('/test-concurrent', methods=['POST'])
@login_required
def test_concurrent_operations():
    """Test concurrent database operations"""
    if not current_user.has_role('superadmin'):
        return jsonify({'error': 'Super Admin access required'}), 403
    
    try:
        # Test concurrent reads
        @with_concurrent_db(readonly=True)
        def test_read():
            from app.models import User
            return User.concurrent_count()
        
        # Execute tests
        user_count = test_read()
        
        return jsonify({
            'success': True,
            'message': 'Concurrent read test completed',
            'results': {
                'user_count': user_count
            }
        })
        
    except Exception as e:
        logger.error(f"Error testing concurrent operations: {e}")
        return jsonify({
            'success': False,
            'error': f'Concurrent test failed: {str(e)}'
        }), 500

# Add error handlers
@db_admin_bp.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@db_admin_bp.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500
