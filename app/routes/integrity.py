from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required
import os
import sys

integrity_bp = Blueprint('integrity', __name__, url_prefix='/integrity')

@integrity_bp.route('/verify', methods=['GET', 'POST'])
def verify_integrity():
    """Handle integrity password verification"""
    if not hasattr(current_app, 'file_integrity_monitor'):
        flash('File integrity monitoring is not enabled.', 'error')
        return redirect(url_for('main.index'))
    
    monitor = current_app.file_integrity_monitor
    
    if not monitor.integrity_compromised:
        flash('File integrity is not compromised.', 'info')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        
        if not password:
            flash('Password is required.', 'error')
            return render_template('integrity/verify.html')
        
        if monitor.verify_integrity_password(password):
            # Password correct, reset integrity monitoring and check integrity immediately
            integrity_ok = monitor.reset_integrity()
            if integrity_ok:
                flash('Integrity password verified. File monitoring has been reset and verified.', 'success')
            else:
                flash('Integrity password verified, but some files are still modified. Please check your system.', 'warning')
            return redirect(url_for('main.index'))
        else:
            # Password incorrect, shut down the server
            flash('Incorrect password. Server will shut down for security.', 'error')
            
            # Log the failed attempt
            print(f"SECURITY ALERT: Failed integrity password attempt from {request.remote_addr}")
            
            # Shut down the server
            def shutdown_server():
                import time
                time.sleep(2)  # Give time for the response to be sent
                print("SECURITY SHUTDOWN: Incorrect integrity password provided")
                os._exit(1)
            
            import threading
            threading.Thread(target=shutdown_server).start()
            
            return render_template('integrity/verify.html', shutdown=True)
    
    return render_template('integrity/verify.html')

@integrity_bp.route('/status')
@login_required
def status():
    """Show integrity monitoring status"""
    if not hasattr(current_app, 'file_integrity_monitor'):
        return jsonify({'error': 'File integrity monitoring is not enabled'})
    
    monitor = current_app.file_integrity_monitor
    
    return jsonify({
        'compromised': monitor.integrity_compromised,
        'warning_only_mode': monitor.warning_only_mode,
        'files_monitored': len(monitor.checksums),
        'last_check': 'Startup Only'
    })

@integrity_bp.route('/reset_password', methods=['POST'])
@login_required
def reset_password():
    """Reset the integrity password (admin only)"""
    if not hasattr(current_app, 'file_integrity_monitor'):
        return jsonify({'error': 'File integrity monitoring is not enabled'})
    
    new_password = request.json.get('password')
    if not new_password:
        return jsonify({'error': 'Password is required'})
    
    monitor = current_app.file_integrity_monitor
    monitor.set_integrity_password(new_password)
    
    return jsonify({'success': True, 'message': 'Integrity password updated'})
