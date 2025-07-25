from flask import Blueprint, render_template, current_app, Response, stream_with_context, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from app.routes.auth import admin_required
from app.utils.version_manager import VersionManager
from app.utils.update_manager import UpdateManager
from app.utils.remote_config import fetch_remote_config, is_remote_version_newer
from app.utils.theme_manager import ThemeManager
from app.models import User, Role

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

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

    # Get Git configuration and status
    update_manager = UpdateManager()
    git_config = update_manager.get_git_config()
    git_status = update_manager.get_git_status()
    
    # Add changes summary to the status
    changes_summary = update_manager.get_git_changes_summary()
    git_status['changes_summary'] = changes_summary
    
    return render_template('admin/update.html', 
                         current_version=current_version,
                         update_available=update_available,
                         changelog_txt=changelog_txt,
                         git_config=git_config,
                         git_status=git_status,
                         **get_theme_context())

@bp.route('/update/check', methods=['POST'])
@login_required
@admin_required
def check_for_updates():
    """Check for available updates"""
    update_manager = UpdateManager()
    
    # Get current version
    current_version = update_manager.get_current_version()
    
    # Check for updates using Git or direct download
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
            git_config = update_manager.get_git_config()
            git_status = update_manager.get_git_status()
            
            yield f"data: Using update method: {'Git' if git_status['git_installed'] else 'Direct Download'}\n\n"
            yield f"data: {git_config['description']}\n\n"
            
            # Check Git installation status
            if not git_status['git_installed']:
                yield f"data: Git is not installed on this system\n\n"
                yield f"data: Using direct download method instead\n\n"
            
            # Check if this is a Git repository
            if not git_status['is_repo'] and git_status['git_installed']:
                yield f"data: Initializing Git repository automatically...\n\n"
                yield f"data: This may take a moment for new repositories\n\n"
                yield f"data: Setting up branches and remote configuration...\n\n"
            
            # Check for uncommitted changes
            changes_summary = update_manager.get_git_changes_summary()
            if changes_summary != "No uncommitted changes" and changes_summary != "Not a Git repository":
                yield f"data: 📝 Found uncommitted changes: {changes_summary}\n\n"
                yield f"data: Auto-committing changes before update...\n\n"
            
            # Perform the update using Git or direct download
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
                
                # Provide helpful guidance for common issues
                if "Failed to switch to branch" in message:
                    yield f"data: This is normal for new repositories. The system will create the branch automatically.\n\n"
                    yield f"data: You can manually push to the remote repository later if needed.\n\n"
                elif "Git pull failed" in message:
                    yield f"data: This is normal for new repositories without remote content.\n\n"
                    yield f"data: The update will continue with local changes.\n\n"
                elif "Could not configure remote origin" in message:
                    yield f"data: Remote repository configuration failed. This is normal for new repositories.\n\n"
                    yield f"data: You can configure the remote manually later: git remote add origin <repository-url>\n\n"
                elif "does already exist" in message:
                    yield f"data: Branch conflict detected. The system is resolving this automatically.\n\n"
                    yield f"data: This is normal when there are conflicting Git references.\n\n"
                elif "Resolved branch conflict" in message:
                    yield f"data: Branch conflict resolved successfully!\n\n"
                elif "Created temporary branch" in message:
                    yield f"data: Created temporary branch to avoid conflicts.\n\n"
                    yield f"data: The update will continue with the temporary branch.\n\n"
                elif "Installing packages from requirements.txt" in message:
                    yield f"data: Installing new packages from requirements.txt...\n\n"
                    yield f"data: This may take a few minutes.\n\n"
                elif "Packages installed successfully" in message:
                    yield f"data: ✅ Package installation completed successfully!\n\n"
                elif "Failed to install packages" in message:
                    yield f"data: ⚠️ Package installation failed, but update will continue.\n\n"
                    yield f"data: You may need to install packages manually: pip install -r requirements.txt\n\n"
                elif "Flask reload mechanism triggered" in message:
                    yield f"data: 🔄 Flask reload mechanism triggered...\n\n"
                    yield f"data: The application will reload gracefully to apply changes.\n\n"
                    yield f"data: Please wait a moment and refresh the page.\n\n"
                elif "Restart signal sent" in message:
                    yield f"data: 🔄 Restart signal sent to parent process...\n\n"
                    yield f"data: The application will restart to apply changes.\n\n"
                    yield f"data: Please wait a moment and refresh the page.\n\n"
                elif "Changes committed:" in message:
                    yield f"data: ✅ {message}\n\n"
                elif "Pre-update commit:" in message:
                    yield f"data: ✅ Pre-update changes committed successfully\n\n"
                elif "Post-update commit:" in message:
                    yield f"data: ✅ Post-update changes committed successfully\n\n"
                elif "Post-direct-update commit:" in message:
                    yield f"data: ✅ Post-direct-update changes committed successfully\n\n"
                elif "server restarting immediately" in message:
                    yield f"data: 🔄 Server restarting immediately...\n\n"
                    yield f"data: The application will restart to apply all changes.\n\n"
                    yield f"data: Please wait a moment and refresh the page.\n\n"
                
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
def configure_git():
    """Configure the Git repository settings"""
    try:
        data = request.get_json()
        
        update_manager = UpdateManager()
        
        # Extract configuration
        repository_url = data.get('repositoryUrl', '')
        branch = data.get('branch', 'main')
        backup_enabled = data.get('backupEnabled', True)
        
        # Set the Git configuration
        update_manager.set_git_config(repository_url, branch, backup_enabled)
        
        return jsonify({
            'success': True,
            'message': 'Git repository configured successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error configuring Git repository: {str(e)}'
        }), 500

@bp.route('/update/status', methods=['GET'])
@login_required
@admin_required
def get_git_status():
    """Get Git repository status"""
    try:
        update_manager = UpdateManager()
        git_status = update_manager.get_git_status()
        
        # Add changes summary to the status
        changes_summary = update_manager.get_git_changes_summary()
        git_status['changes_summary'] = changes_summary
        
        return jsonify({
            'success': True,
            'git_status': git_status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error getting Git status: {str(e)}'
        }), 500

@bp.route('/restart', methods=['POST'])
@login_required
@admin_required
def restart_server():
    """Manually restart the server"""
    try:
        update_manager = UpdateManager()
        success, message = update_manager.restart_server()
        
        if success:
            if "Flask reload mechanism" in message:
                flash('Server restart initiated using Flask reload mechanism.', 'success')
                return jsonify({
                    'success': True,
                    'message': 'Server restart initiated. The application will reload gracefully.',
                    'restart_immediate': True
                })
            elif "Restart signal sent" in message:
                flash('Server restart signal sent. The application will restart.', 'success')
                return jsonify({
                    'success': True,
                    'message': 'Server restart signal sent. Please wait a moment and refresh the page.',
                    'restart_immediate': True
                })
            else:
                flash('Server restart flag created. The server will restart on the next request.', 'success')
        else:
            flash(f'Failed to restart server: {message}', 'error')
            
    except Exception as e:
        flash(f'Error restarting server: {str(e)}', 'error')
    
    return redirect(url_for('admin.update_page'))

@bp.route('/update/restore', methods=['POST'])
@login_required
@admin_required
def restore_backup():
    """Restore the latest backup and redirect to the update page with a status message."""
    update_manager = UpdateManager()
    success, message = update_manager.restore_latest_backup()
    if success:
        flash(f"Restore successful: {message}", 'success')
    else:
        flash(f"Restore failed: {message}", 'danger')
    return redirect(url_for('admin.update_page'))
