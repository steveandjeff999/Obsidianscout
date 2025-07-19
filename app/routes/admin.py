from flask import Blueprint, render_template, current_app, Response, stream_with_context, request, jsonify
from flask_login import login_required
from app.routes.auth import admin_required
from app.utils.version_manager import VersionManager
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

    return render_template('admin/update.html', 
                         current_version=current_version,
                         update_available=update_available,
                         changelog_txt=changelog_txt)

@bp.route('/update/check', methods=['POST'])
@login_required
@admin_required
def check_for_updates():
    """Check for available updates"""
    version_manager = VersionManager()
    
    # Get current version and repository URL from local config
    current_version = version_manager.get_current_version()
    repo_url = version_manager.config.get('repository_url', '')
    branch = version_manager.config.get('branch', 'main')
    
    # Fetch remote config using the new function
    remote_config = fetch_remote_config(repo_url, branch)
    
    if remote_config:
        remote_version = remote_config.get('version', '0.0.0.0')
        has_update, message = is_remote_version_newer(current_version, remote_version)
    else:
        has_update, message = False, "Could not fetch remote version"
    
    return jsonify({
        'update_available': has_update,
        'message': message,
        'current_version': current_version,
        'latest_version': remote_version if remote_config else "Unknown"
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
        # Determine which script to run based on OS
        script_path = None
        try:
            if platform.system() == 'Windows':
                script_path = os.path.join(current_app.root_path, '..', 'update.bat')
                yield f"data: Detected Windows OS, using update.bat script\n\n"
            else:
                script_path = os.path.join(current_app.root_path, '..', 'update.sh')
                yield f"data: Detected Unix-like OS, using update.sh script\n\n"
                # Ensure the script is executable on Unix-like systems
                if os.path.exists(script_path):
                    try:
                        os.chmod(script_path, 0o755)
                        yield f"data: Made update.sh executable\n\n"
                    except Exception as e:
                        yield f"data: Warning: Failed to set executable permissions: {e}\n\n"

            # Check if the script exists
            if not script_path or not os.path.exists(script_path):
                yield f"data: Error: Update script not found at {script_path}\n\n"
                yield "event: end\ndata: error\n\n"
                return

            # Send a message about which script is being executed
            yield f"data: Using update script: {script_path}\n\n"

            # Start the process
            if platform.system() == 'Windows':
                yield f"data: Starting Windows update process...\n\n"
                process = subprocess.Popen(
                    script_path,  # Use the path directly for Windows
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    universal_newlines=True,
                    shell=True
                )
            else:
                yield f"data: Starting Unix update process...\n\n"
                process = subprocess.Popen(
                    [script_path],  # Use list format for Unix
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    universal_newlines=True
                )

            # Stream output in real-time
            for line in iter(process.stdout.readline, ''):
                if line.strip():  # Only send non-empty lines
                    line_sanitized = line.replace('\r', '').rstrip('\n')
                    yield f"data: {line_sanitized}\n\n"

            # Wait for the process to complete
            process.stdout.close()
            return_code = process.wait()

            # Log the result
            if return_code == 0:
                yield f"data: Process completed with return code: {return_code}\n\n"
                
                # Update version information after successful update
                try:
                    version_manager = VersionManager()
                    
                    # Get repository info from config
                    repo_url = version_manager.config.get('repository_url', '')
                    branch = version_manager.config.get('branch', 'main')
                    current_version = version_manager.get_current_version()
                    
                    # Fetch remote config to get latest version
                    remote_config = fetch_remote_config(repo_url, branch)
                    if remote_config and 'version' in remote_config:
                        remote_version = remote_config['version']
                        has_update, _ = is_remote_version_newer(current_version, remote_version)
                        
                        if has_update:
                            version_manager.set_current_version(remote_version)
                            yield f"data: Updated to version {remote_version}\n\n"
                        else:
                            yield f"data: Already at latest version {current_version}\n\n"
                    else:
                        yield f"data: Could not fetch remote version information\n\n"
                except Exception as e:
                    yield f"data: Warning: Could not update version info: {str(e)}\n\n"
                
                yield "event: end\ndata: success\n\n"
            else:
                yield f"data: Process failed with return code: {return_code}\n\n"
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
