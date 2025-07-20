from flask import Blueprint, render_template, current_app, Response, stream_with_context, request, jsonify
from flask_login import login_required
from app.routes.auth import admin_required
from app.utils.version_manager import VersionManager
from app.utils.update_manager import UpdateManager
from app.utils.remote_config import fetch_remote_config, is_remote_version_newer
import subprocess
import sys
import os
import platform

bp = Blueprint('admin', __name__, url_prefix='/admin')

@bp.route('/update')
@login_required
@admin_required
def update_page():
    """Render the application update page"""
    version_manager = VersionManager()
    current_version = version_manager.get_current_version()
    
    # Get repository info from config
    repo_url = version_manager.config.get('repository_url', '')
    branch = version_manager.config.get('branch', 'main')
    
    # Try to fetch remote config to check for updates
    remote_config = fetch_remote_config(repo_url, branch)
    if remote_config:
        remote_version = remote_config.get('version', '0.0.0.0')
        update_available, _ = is_remote_version_newer(current_version, remote_version)
    else:
        update_available = False

    # Read changelog from plain text file
    changelog_txt = ''
    changelog_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'CHANGELOG.txt')
    if os.path.exists(changelog_path):
        with open(changelog_path, 'r', encoding='utf-8') as f:
            changelog_txt = f.read()
    else:
        changelog_txt = 'No changelog found.'

    # Get update method information
    update_manager = UpdateManager()
    update_method_info = update_manager.get_update_method_info()
    
    return render_template('admin/update.html', 
                         current_version=current_version,
                         update_available=update_available,
                         changelog_txt=changelog_txt,
                         update_method_info=update_method_info)

@bp.route('/update/check', methods=['POST'])
@login_required
@admin_required
def check_for_updates():
    """Check for available updates"""
    update_manager = UpdateManager()
    
    # Get current version
    current_version = update_manager.get_current_version()
    
    # Check for updates using the configured method
    has_update, message = update_manager.check_for_updates()
    
    # Get latest version if update is available
    latest_version = "Unknown"
    if has_update:
        latest_version = update_manager.get_latest_version() or "Unknown"
    
    return jsonify({
        'update_available': has_update,
        'message': message,
        'current_version': current_version,
        'latest_version': latest_version
    })

@bp.route('/update/run', methods=['GET', 'POST'])
@login_required
@admin_required
def run_update():
    """Run the update script and stream the output"""
    
    # Create an ID for this update session to avoid running multiple updates at once
    update_session_id = None
    
    # Store this in the application context for checking if we're already running
    if not hasattr(current_app, 'update_running'):
        current_app.update_running = False
    
    # Handle POST request - this starts the update
    if request.method == 'POST':
        # If update is already running, don't start another one
        if current_app.update_running:
            return jsonify({'error': 'Update already in progress'}), 409
        
        # Mark that we're starting an update
        current_app.update_running = True
        # Return success to indicate the update has been triggered
        return jsonify({'status': 'started'}), 200
    
    # For GET requests, we stream the output
    def generate():
        try:
            update_manager = UpdateManager()
            update_method_info = update_manager.get_update_method_info()
            
            yield f"data: Using update method: {update_method_info['method']}\n\n"
            yield f"data: {update_method_info['description']}\n\n"
            
            # Perform the update using the configured method
            success, message = update_manager.perform_update()
            
            if success:
                yield f"data: {message}\n\n"
                
                # Update version information after successful update
                try:
                    latest_version = update_manager.get_latest_version()
                    if latest_version:
                        update_manager.set_current_version(latest_version)
                        yield f"data: Updated to version {latest_version}\n\n"
                    else:
                        yield f"data: Version information updated\n\n"
                except Exception as e:
                    yield f"data: Warning: Could not update version info: {str(e)}\n\n"
                
                yield "event: end\ndata: success\n\n"
            else:
                yield f"data: Update failed: {message}\n\n"
                yield "event: end\ndata: error\n\n"

        except Exception as e:
            yield f"data: An error occurred: {str(e)}\n\n"
            yield "event: end\ndata: error\n\n"
        finally:
            # Reset the update running flag
            current_app.update_running = False
    
    # Return the streaming response for GET requests
    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream'
    )
    # Add headers to prevent caching
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@bp.route('/update/version', methods=['POST'])
@login_required
@admin_required
def update_version():
    """Update version information after successful update"""
    try:
        data = request.get_json()
        new_version = data.get('version')
        
        version_manager = VersionManager()
        if new_version:
            version_manager.set_current_version(new_version)
        else:
            version_manager.update_version_info(mark_updated=True)
        
        return jsonify({
            'success': True,
            'current_version': version_manager.get_current_version(),
            'message': 'Version updated successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating version: {str(e)}'
        }), 500

@bp.route('/update/configure', methods=['POST'])
@login_required
@admin_required
def configure_update_method():
    """Configure the update method and related settings"""
    try:
        data = request.get_json()
        
        update_manager = UpdateManager()
        
        # Extract configuration
        update_method = data.get('updateMethod', 'git')
        backup_enabled = data.get('backupEnabled', True)
        
        # Method-specific configuration
        config_kwargs = {'backup_enabled': backup_enabled}
        
        if update_method == 'git':
            config_kwargs['repository_url'] = data.get('repositoryUrl', '')
            config_kwargs['branch'] = data.get('branch', 'main')
        elif update_method == 'direct_download':
            config_kwargs['download_url'] = data.get('downloadUrl', '')
        elif update_method == 'manual':
            # No additional config needed for manual updates
            pass
        else:
            return jsonify({
                'success': False,
                'message': f'Unknown update method: {update_method}'
            }), 400
        
        # Set the update method configuration
        update_manager.set_update_method(update_method, **config_kwargs)
        
        return jsonify({
            'success': True,
            'message': f'Update method configured successfully: {update_method}'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error configuring update method: {str(e)}'
        }), 500
