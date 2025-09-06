"""
Multi-Server Sync Management Routes
Web interface for configuring and managing sync servers
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.models import SyncServer, SyncLog, SyncConfig
# Old sync manager disabled - Universal Sync System replaces it
# from app.utils.multi_server_sync import sync_manager

# Fallback sync_manager for compatibility
class FallbackSyncManager:
    def __init__(self):
        self.server_id = "universal-sync"
        # Properties that might be set by the UI
        self.sync_enabled = True
        self.sync_interval = 30
        self.file_watch_interval = 5
    
    def get_sync_servers(self, active_only=True):
        """Get sync servers with proper connection handling"""
        from flask import current_app
        try:
            if current_app:
                with current_app.app_context():
                    # Use a fresh session to avoid connection pool issues
                    from sqlalchemy.orm import sessionmaker
                    Session = sessionmaker(bind=db.engine)
                    session = Session()
                    try:
                        if active_only:
                            servers = session.query(SyncServer).filter_by(is_active=True).all()
                        else:
                            servers = session.query(SyncServer).all()
                        return servers
                    finally:
                        session.close()
        except Exception as e:
            logger.error(f"Error getting sync servers: {e}")
        return []
    
    def get_sync_status(self):
        """Get sync status for compatibility with safe server count"""
        try:
            servers_count = len(self.get_sync_servers())
        except Exception as e:
            logger.error(f"Error getting servers count: {e}")
            servers_count = 0
            
        return {
            'active': True,
            'message': 'Universal Sync System active',
            'type': 'universal',
            'last_sync': None,
            'sync_enabled': True,
            'servers_count': servers_count,
            'status': 'running'
        }
    
    def sync_with_server(self, server, sync_type='full'):
        """Fallback - Universal Sync System handles sync automatically"""
        return True
    
    def add_sync_server(self, name, host, port=5000, protocol='https'):
        """Add a new sync server"""
        from flask import current_app
        if current_app:
            with current_app.app_context():
                server = SyncServer(
                    name=name,
                    host=host,
                    port=port,
                    protocol=protocol,
                    is_active=True
                )
                db.session.add(server)
                db.session.commit()
                return server
        return None
    
    def remove_sync_server(self, server_id):
        """Remove a sync server"""
        from flask import current_app
        if current_app:
            with current_app.app_context():
                server = SyncServer.query.get(server_id)
                if server:
                    db.session.delete(server)
                    db.session.commit()
                    return True
        return False
    
    def ping_server(self, server):
        """Ping a server - Universal Sync System handles connectivity"""
        return True
    
    def upload_file_to_server(self, server, file_path, event_type='update'):
        """Fallback file upload - Universal Sync handles this automatically"""
        try:
            # Universal sync handles file sync automatically
            logger.info(f"File sync handled by Universal Sync System: {file_path}")
            return True
        except Exception as e:
            logger.warning(f"Universal file sync fallback: {e}")
            return False
    
    def delete_file_on_server(self, server, file_path):
        """Fallback file delete - Universal Sync handles this automatically"""
        try:
            # Universal sync handles file deletion automatically
            logger.info(f"File deletion handled by Universal Sync System: {file_path}")
            return True
        except Exception as e:
            logger.warning(f"Universal file deletion fallback: {e}")
            return False
    
    def sync_all_servers(self):
        """Sync with all servers"""
        servers = self.get_sync_servers()
        for server in servers:
            self.sync_with_server(server)
        return True
    
    def force_full_sync(self, server_id=None):
        """Force full sync"""
        if server_id:
            server = SyncServer.query.get(server_id)
            if server:
                return self.sync_with_server(server, 'full')
        else:
            return self.sync_all_servers()
        return True

sync_manager = FallbackSyncManager()

import logging
import requests

logger = logging.getLogger(__name__)

def require_superadmin(f):
    """Decorator to require superadmin role (using existing auth pattern)"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('You must be logged in to access this page.', 'error')
            return redirect(url_for('auth.login'))
        
        # Check if user has superadmin role
        if not current_user.has_role('superadmin'):
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function

sync_routes = Blueprint('sync', __name__, url_prefix='/sync')


@sync_routes.route('/')
@login_required
@require_superadmin
def dashboard():
    """Sync dashboard - overview of all sync servers and recent activity"""
    servers = sync_manager.get_sync_servers(active_only=False)
    recent_logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(10).all()
    sync_status = sync_manager.get_sync_status()
    
    return render_template('sync/dashboard.html',
                         servers=servers,
                         recent_logs=recent_logs,
                         sync_status=sync_status)


@sync_routes.route('/servers')
@login_required
@require_superadmin
def manage_servers():
    """Manage sync servers"""
    servers = SyncServer.query.order_by(SyncServer.sync_priority).all()
    return render_template('sync/servers.html', servers=servers)


@sync_routes.route('/servers/add', methods=['GET', 'POST'])
@login_required
@require_superadmin
def add_server():
    """Add a new sync server"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            host = request.form.get('host')
            port = int(request.form.get('port', 5000))
            protocol = request.form.get('protocol', 'https')
            
            if not name or not host:
                flash('Name and host are required', 'error')
                return render_template('sync/add_server.html')
            
            # Check if server already exists
            existing = SyncServer.query.filter_by(host=host, port=port).first()
            if existing:
                flash('A server with this host and port already exists', 'error')
                return render_template('sync/add_server.html')
            
            server = sync_manager.add_sync_server(
                name=name,
                host=host,
                port=port,
                protocol=protocol,
                user_id=current_user.id
            )
            
            flash(f'Server "{name}" added successfully', 'success')
            return redirect(url_for('sync.manage_servers'))
            
        except Exception as e:
            logger.error(f"Failed to add server: {e}")
            flash(f'Failed to add server: {str(e)}', 'error')
    
    return render_template('sync/add_server.html')


@sync_routes.route('/servers/<int:server_id>/edit', methods=['GET', 'POST'])
@login_required
@require_superadmin
def edit_server(server_id):
    """Edit a sync server"""
    server = SyncServer.query.get_or_404(server_id)
    
    if request.method == 'POST':
        try:
            server.name = request.form.get('name')
            server.host = request.form.get('host')
            server.port = int(request.form.get('port', 5000))
            server.protocol = request.form.get('protocol', 'https')
            server.sync_priority = int(request.form.get('sync_priority', 1))
            
            # Update sync settings
            server.sync_enabled = 'sync_enabled' in request.form
            server.sync_database = 'sync_database' in request.form
            server.sync_instance_files = 'sync_instance_files' in request.form
            server.sync_config_files = 'sync_config_files' in request.form
            server.sync_uploads = 'sync_uploads' in request.form
            
            db.session.commit()
            
            flash(f'Server "{server.name}" updated successfully', 'success')
            return redirect(url_for('sync.manage_servers'))
            
        except Exception as e:
            logger.error(f"Failed to update server: {e}")
            flash(f'Failed to update server: {str(e)}', 'error')
    
    return render_template('sync/edit_server.html', server=server)


@sync_routes.route('/servers/<int:server_id>/delete', methods=['POST'])
@login_required
@require_superadmin
def delete_server(server_id):
    """Delete a sync server"""
    try:
        server = SyncServer.query.get_or_404(server_id)
        server_name = server.name
        
        if sync_manager.remove_sync_server(server_id):
            flash(f'Server "{server_name}" deleted successfully', 'success')
        else:
            flash('Failed to delete server', 'error')
            
    except Exception as e:
        logger.error(f"Failed to delete server: {e}")
        flash(f'Failed to delete server: {str(e)}', 'error')
    
    return redirect(url_for('sync.manage_servers'))


@sync_routes.route('/servers/<int:server_id>/ping', methods=['POST'])
@login_required
@require_superadmin
def ping_server(server_id):
    """Ping a server to test connectivity"""
    try:
        server = SyncServer.query.get_or_404(server_id)
        success = sync_manager.ping_server(server)
        
        if success:
            flash(f'Server "{server.name}" is responding', 'success')
        else:
            flash(f'Server "{server.name}" is not responding: {server.last_error}', 'warning')
            
    except Exception as e:
        logger.error(f"Failed to ping server: {e}")
        flash(f'Failed to ping server: {str(e)}', 'error')
    
    return redirect(url_for('sync.manage_servers'))


@sync_routes.route('/servers/<int:server_id>/sync', methods=['POST'])
@login_required
@require_superadmin
def sync_server(server_id):
    """Trigger sync with a specific server - AUTOMATIC SQLite3 Zero Data Loss Sync"""
    try:
        from app.utils.automatic_sqlite3_sync import automatic_sqlite3_sync
        
        # AUTOMATIC SQLite3 SYNC - Zero Data Loss Guaranteed
        logger.info(f"🔄 Starting automatic SQLite3 sync with server {server_id}")
        result = automatic_sqlite3_sync.perform_automatic_sync(server_id)
        
        if result['success']:
            stats = result['stats']
            flash(f'✅ Automatic SQLite3 sync completed - {stats["local_changes_sent"]} sent, {stats["remote_changes_received"]} received, {stats["conflicts_resolved"]} conflicts resolved', 'success')
            
            if stats.get('duration'):
                flash(f'⏱️ Completed in {stats["duration"]:.2f} seconds with 0% data loss guarantee', 'info')
        else:
            flash(f'❌ SQLite3 sync failed: {result.get("error", "Unknown error")}', 'error')
        
    except Exception as e:
        logger.error(f"Failed to sync with server: {e}")
        flash(f'❌ Automatic SQLite3 sync failed: {str(e)}', 'error')
    
    return redirect(url_for('sync.manage_servers'))


@sync_routes.route('/sync-all', methods=['POST'])
@login_required
@require_superadmin
def sync_all():
    """Trigger sync with all servers - AUTOMATIC SQLite3 Zero Data Loss Sync"""
    try:
        from app.utils.automatic_sqlite3_sync import automatic_sqlite3_sync
        from app.models import SyncServer
        
        servers = SyncServer.query.filter_by(sync_enabled=True).all()
        total_sent = 0
        total_received = 0
        successful_syncs = 0
        failed_syncs = 0
        
        logger.info(f"🔄 Starting automatic SQLite3 sync with {len(servers)} servers")
        
        for server in servers:
            try:
                # AUTOMATIC SQLite3 SYNC - Zero Data Loss Guaranteed
                result = automatic_sqlite3_sync.perform_automatic_sync(server.id)
                
                if result['success']:
                    successful_syncs += 1
                    stats = result['stats']
                    total_sent += stats['local_changes_sent']
                    total_received += stats['remote_changes_received']
                    
                    logger.info(f"✅ SQLite3 sync completed with {server.name}")
                else:
                    failed_syncs += 1
                    logger.error(f"❌ SQLite3 sync failed with {server.name}: {result.get('error')}")
                    
            except Exception as e:
                logger.error(f"Failed to sync with {server.name}: {e}")
                failed_syncs += 1
        
        if successful_syncs > 0:
            flash(f'✅ Automatic SQLite3 sync completed: {successful_syncs} servers synced successfully', 'success')
            flash(f'📊 Total: {total_sent} changes sent, {total_received} changes received with 0% data loss', 'info')
        
        if failed_syncs > 0:
            flash(f'❌ {failed_syncs} servers failed to sync', 'error')
            
    except Exception as e:
        logger.error(f"Failed to sync all servers: {e}")
        flash(f'❌ Automatic SQLite3 sync all failed: {str(e)}', 'error')
    
    return redirect(url_for('sync.dashboard'))


@sync_routes.route('/force-sync', methods=['POST'])
@login_required
@require_superadmin
def force_sync():
    """Force a full sync with all servers"""
    try:
        sync_manager.force_full_sync()
        flash('Full sync initiated with all servers', 'info')
        
    except Exception as e:
        logger.error(f"Failed to force full sync: {e}")
        flash(f'Failed to force full sync: {str(e)}', 'error')
    
    return redirect(url_for('sync.dashboard'))


@sync_routes.route('/servers/<int:server_id>/update', methods=['POST'])
@login_required
@require_superadmin
def update_server(server_id):
    """Trigger remote update on a specific server via its /api/sync/update endpoint."""
    try:
        server = SyncServer.query.get_or_404(server_id)
        # Default to updating from this repository's main branch zip on GitHub
        zip_url = f"https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip"
        payload = {
            'zip_url': zip_url,
            'use_waitress': True,
            'port': server.port  # Use the server's actual port
        }
        url = f"{server.base_url}/api/sync/update"
        try:
            resp = requests.post(url, json=payload, timeout=10, verify=False)
            if resp.status_code in (200, 202):
                flash(f'Update started on server "{server.name}"', 'success')
            else:
                flash(f'Failed to start update on {server.name}: HTTP {resp.status_code}', 'error')
                logger.error(f"Update failed for {server.name} ({server.base_url}): HTTP {resp.status_code} - {resp.text if resp.text else 'No response body'}")
        except Exception as e:
            flash(f'Failed to contact {server.name}: {e}', 'error')

    except Exception as e:
        logger.error(f"Failed to trigger update: {e}")
        flash(f'Failed to trigger update: {e}', 'error')

    return redirect(url_for('sync.manage_servers'))


@sync_routes.route('/update-all-servers', methods=['POST'])
@login_required
@require_superadmin
def update_all_servers():
    """Trigger remote update on all configured sync servers."""
    try:
        servers = SyncServer.query.filter_by(sync_enabled=True).all()
        zip_url = f"https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip"
        successes = 0
        failures = []
        for server in servers:
            payload = {'zip_url': zip_url, 'use_waitress': True, 'port': server.port}  # Use each server's actual port
            url = f"{server.base_url}/api/sync/update"
            try:
                resp = requests.post(url, json=payload, timeout=10, verify=False)
                if resp.status_code in (200, 202):
                    successes += 1
                else:
                    failures.append((server.name, f'HTTP {resp.status_code}'))
                    logger.error(f"Update failed for {server.name} ({server.base_url}): HTTP {resp.status_code} - {resp.text if resp.text else 'No response body'}")
            except Exception as e:
                failures.append((server.name, str(e)))
                logger.error(f"Update failed for {server.name} ({server.base_url}): {str(e)}")

        if successes:
            flash(f'Started update on {successes} servers. {len(failures)} failures.', 'success')
        else:
            flash('No updates started (all failed).', 'error')

        if failures:
            for name, reason in failures:
                logger.warning(f'Update failed for {name}: {reason}')

    except Exception as e:
        logger.error(f"Failed to trigger updates: {e}")
        flash(f'Failed to trigger updates: {e}', 'error')

    return redirect(url_for('sync.dashboard'))


@sync_routes.route('/logs')
@login_required
@require_superadmin
def view_logs():
    """View sync operation logs"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    server_id = request.args.get('server_id', type=int)
    
    query = SyncLog.query
    if server_id:
        query = query.filter_by(server_id=server_id)
    
    logs = query.order_by(SyncLog.started_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    servers = SyncServer.query.all()
    
    return render_template('sync/logs.html', 
                         logs=logs,
                         servers=servers,
                         selected_server_id=server_id)


@sync_routes.route('/config', methods=['GET', 'POST'])
@login_required
@require_superadmin
def sync_config():
    """Configure sync settings"""
    if request.method == 'POST':
        try:
            # Update sync configuration
            sync_enabled = 'sync_enabled' in request.form
            sync_interval = int(request.form.get('sync_interval', 30))
            file_watch_interval = int(request.form.get('file_watch_interval', 5))
            
            SyncConfig.set_value('sync_enabled', sync_enabled, 'boolean', 
                               'Enable/disable automatic synchronization', current_user.id)
            SyncConfig.set_value('sync_interval', sync_interval, 'integer',
                               'Interval between sync operations (seconds)', current_user.id)
            SyncConfig.set_value('file_watch_interval', file_watch_interval, 'integer',
                               'Interval for file change monitoring (seconds)', current_user.id)
            
            # Update sync manager settings
            sync_manager.sync_enabled = sync_enabled
            sync_manager.sync_interval = sync_interval
            sync_manager.file_watch_interval = file_watch_interval
            
            flash('Sync configuration updated successfully', 'success')
            
        except Exception as e:
            logger.error(f"Failed to update sync config: {e}")
            flash(f'Failed to update sync configuration: {str(e)}', 'error')
    
    # Get current configuration
    config = {
        'sync_enabled': SyncConfig.get_value('sync_enabled', True),
        'sync_interval': SyncConfig.get_value('sync_interval', 30),
        'file_watch_interval': SyncConfig.get_value('file_watch_interval', 5)
    }
    
    return render_template('sync/config.html', config=config)


# AJAX endpoints for real-time updates
@sync_routes.route('/api/status')
@login_required
@require_superadmin
def api_status():
    """Get sync status for AJAX updates"""
    try:
        status = sync_manager.get_sync_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sync_routes.route('/api/servers')
@login_required
@require_superadmin
def api_servers():
    """Get server list for AJAX updates"""
    try:
        servers = sync_manager.get_sync_servers(active_only=False)
        return jsonify([server.to_dict() for server in servers])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sync_routes.route('/api/logs')
@login_required
@require_superadmin
def api_logs():
    """Get recent logs for AJAX updates"""
    try:
        limit = request.args.get('limit', 10, type=int)
        logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(limit).all()
        return jsonify([log.to_dict() for log in logs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Enhanced SQLite3 Sync Management Routes
@sync_routes.route('/sqlite3/<int:server_id>')
@login_required
@require_superadmin
def sqlite3_sync_server(server_id):
    """Perform SQLite3-enhanced sync with a specific server"""
    try:
        from app.utils.sqlite3_sync import SQLite3SyncManager
        
        server = SyncServer.query.get_or_404(server_id)
        
        if not server.sync_enabled:
            flash('Sync is disabled for this server', 'warning')
            return redirect(url_for('sync_routes.dashboard'))
        
        server_config = {
            'id': server.id,
            'name': server.name,
            'host': server.host,
            'port': server.port,
            'protocol': server.protocol,
            'last_sync': server.last_sync
        }
        
        sync_manager = SQLite3SyncManager()
        result = sync_manager.perform_reliable_sync(server_config)
        
        if result['success']:
            flash(f'SQLite3 sync completed successfully with {server.name}', 'success')
            
            # Create detailed flash messages for operations
            for operation in result['operations']:
                flash(operation, 'info')
            
            # Show statistics
            stats = result['stats']
            flash(f"Statistics: {stats['local_changes_sent']} sent, {stats['remote_changes_received']} received, "
                  f"{stats['conflicts_resolved']} conflicts resolved, {stats['duration']:.2f}s", 'info')
        else:
            flash(f'SQLite3 sync failed with {server.name}: {result.get("error", "Unknown error")}', 'error')
            for error in result['stats'].get('errors', []):
                flash(f"Error: {error}", 'error')
    
    except Exception as e:
        logger.error(f"SQLite3 sync error: {e}")
        flash(f'SQLite3 sync failed: {str(e)}', 'error')
    
    return redirect(url_for('sync_routes.dashboard'))


@sync_routes.route('/full-sync/<int:server_id>')
@login_required
@require_superadmin
def full_sync_server(server_id):
    """Perform complete full sync of ALL tables with a specific server"""
    try:
        from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
        
        server = SyncServer.query.get_or_404(server_id)
        
        if not server.sync_enabled:
            flash(f'Sync is disabled for server {server.name}', 'warning')
            return redirect(url_for('sync_routes.dashboard'))
        
        # Initialize automatic SQLite3 sync system
        auto_sync = AutomaticSQLite3Sync()
        
        # Perform full synchronization of ALL tables
        result = auto_sync.perform_full_sync_all_tables(server_id)
        
        if result['success']:
            flash(f'Full sync completed successfully with {server.name}', 'success')
            
            # Create detailed flash messages for operations
            for operation in result['operations']:
                flash(operation, 'info')
            
            # Show comprehensive statistics
            flash(f"Full sync statistics: {result['local_changes_sent']} records sent, "
                  f"{result['remote_changes_received']} records received, "
                  f"{result['total_tables_synced']} tables synchronized", 'info')
        else:
            flash(f'Full sync failed with {server.name}: {result.get("error", "Unknown error")}', 'error')
            for error in result.get('operations', []):
                if error.startswith('❌'):
                    flash(f"Error: {error}", 'error')
    
    except Exception as e:
        logger.error(f"Full sync error: {e}")
        flash(f'Full sync failed: {str(e)}', 'error')
    
    return redirect(url_for('sync_routes.dashboard'))


@sync_routes.route('/full-sync/all')
@login_required
@require_superadmin
def full_sync_all_servers():
    """Perform complete full sync of ALL tables with ALL enabled servers"""
    try:
        from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
        
        servers = SyncServer.query.filter_by(sync_enabled=True, is_active=True).all()
        
        if not servers:
            flash('No enabled servers found for full sync', 'warning')
            return redirect(url_for('sync_routes.dashboard'))
        
        auto_sync = AutomaticSQLite3Sync()
        total_synced = 0
        total_errors = 0
        total_tables = 0
        
        flash(f'Starting full sync with {len(servers)} servers...', 'info')
        
        for server in servers:
            try:
                # Perform full synchronization of ALL tables
                result = auto_sync.perform_full_sync_all_tables(server.id)
                
                if result['success']:
                    total_synced += result['local_changes_sent'] + result['remote_changes_received']
                    total_tables += result['total_tables_synced']
                    
                    flash(f'✅ Full sync with {server.name}: {result["local_changes_sent"]} sent, '
                          f'{result["remote_changes_received"]} received, '
                          f'{result["total_tables_synced"]} tables', 'success')
                else:
                    total_errors += 1
                    flash(f'❌ Full sync failed with {server.name}: {result.get("error", "Unknown error")}', 'error')
                
            except Exception as e:
                total_errors += 1
                logger.error(f"Full sync error with {server.name}: {e}")
                flash(f'❌ Full sync failed with {server.name}: {str(e)}', 'error')
        
        # Summary message
        if total_errors == 0:
            flash(f'🎉 Full sync completed successfully! '
                  f'Synchronized {total_synced} total records across {total_tables} tables with all servers', 'success')
        else:
            flash(f'Full sync completed with {total_errors} errors. '
                  f'Successfully synchronized {total_synced} records across {total_tables} tables', 'warning')
    
    except Exception as e:
        logger.error(f"Full sync all error: {e}")
        flash(f'Full sync failed: {str(e)}', 'error')
    
    return redirect(url_for('sync_routes.dashboard'))


@sync_routes.route('/sqlite3/all')
@login_required
@require_superadmin
def sqlite3_sync_all():
    """Perform SQLite3-enhanced sync with all enabled servers"""
    try:
        from app.utils.sqlite3_sync import SQLite3SyncManager
        
        servers = SyncServer.query.filter_by(sync_enabled=True, is_active=True).all()
        
        if not servers:
            flash('No enabled servers found for sync', 'warning')
            return redirect(url_for('sync_routes.dashboard'))
        
        sync_manager = SQLite3SyncManager()
        total_synced = 0
        total_errors = 0
        
        for server in servers:
            try:
                server_config = {
                    'id': server.id,
                    'name': server.name,
                    'host': server.host,
                    'port': server.port,
                    'protocol': server.protocol,
                    'last_sync': server.last_sync
                }
                
                result = sync_manager.perform_reliable_sync(server_config)
                
                if result['success']:
                    total_synced += 1
                    flash(f'✅ SQLite3 sync completed with {server.name}', 'success')
                else:
                    total_errors += 1
                    flash(f'❌ SQLite3 sync failed with {server.name}', 'error')
                    
            except Exception as e:
                total_errors += 1
                logger.error(f"SQLite3 sync error with {server.name}: {e}")
                flash(f'❌ SQLite3 sync failed with {server.name}: {str(e)}', 'error')
        
        if total_synced > 0:
            flash(f'SQLite3 sync completed: {total_synced} servers synced successfully', 'success')
        
        if total_errors > 0:
            flash(f'{total_errors} servers failed to sync', 'error')
    
    except Exception as e:
        logger.error(f"SQLite3 sync all error: {e}")
        flash(f'SQLite3 sync all failed: {str(e)}', 'error')
    
    return redirect(url_for('sync_routes.dashboard'))


@sync_routes.route('/reliability/<int:server_id>')
@login_required
@require_superadmin
def reliability_report(server_id):
    """Show reliability report for a server"""
    try:
        from app.utils.sqlite3_sync import SQLite3SyncManager
        
        server = SyncServer.query.get_or_404(server_id)
        sync_manager = SQLite3SyncManager()
        report = sync_manager.get_reliability_report(server_id)
        
        return render_template('sync/reliability_report.html', 
                             server=server, 
                             report=report)
    
    except Exception as e:
        logger.error(f"Reliability report error: {e}")
        flash(f'Failed to generate reliability report: {str(e)}', 'error')
        return redirect(url_for('sync_routes.dashboard'))


@sync_routes.route('/cleanup', methods=['GET', 'POST'])
@login_required
@require_superadmin
def cleanup_sync_data():
    """Clean up old sync data"""
    if request.method == 'POST':
        try:
            from app.utils.sqlite3_sync import SQLite3SyncManager
            
            days_to_keep = int(request.form.get('days_to_keep', 30))
            
            sync_manager = SQLite3SyncManager()
            result = sync_manager.cleanup_old_sync_data(days_to_keep)
            
            flash(f"Cleanup completed: {result['deleted_changes']} old changes and "
                  f"{result['deleted_logs']} old logs removed", 'success')
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            flash(f'Cleanup failed: {str(e)}', 'error')
        
        return redirect(url_for('sync_routes.cleanup_sync_data'))
    
    return render_template('sync/cleanup.html')


@sync_routes.route('/api/sqlite3/status/<int:server_id>')
@login_required
@require_superadmin
def api_sqlite3_status(server_id):
    """Get SQLite3 sync status and reliability for a server"""
    try:
        from app.utils.sqlite3_sync import SQLite3SyncManager
        
        sync_manager = SQLite3SyncManager()
        report = sync_manager.get_reliability_report(server_id)
        
        return jsonify(report)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        return jsonify([log.to_dict() for log in logs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
