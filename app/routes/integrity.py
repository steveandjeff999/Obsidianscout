from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required
import os
import sys
import time
import json
import platform
import shutil
from datetime import datetime
from app import db

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
    # Basic monitor info
    info = {
        'compromised': bool(monitor.integrity_compromised),
        'warning_only_mode': bool(monitor.warning_only_mode),
        'files_monitored': int(len(monitor.checksums or {})),
    }

    # Checksum file metadata (if available)
    try:
        checksums_file = getattr(monitor, 'checksums_file', None)
        if checksums_file and os.path.exists(checksums_file):
            stat = os.stat(checksums_file)
            file_meta = {'path': checksums_file, 'size_bytes': stat.st_size, 'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()}
            # Attempt to load the saved 'created' timestamp from the file if present
            try:
                with open(checksums_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'created' in data:
                        file_meta['created'] = data.get('created')
            except Exception:
                pass
            info['checksum_file'] = file_meta
        else:
            info['checksum_file'] = {'path': checksums_file, 'exists': False}
    except Exception as e:
        info['checksum_file_error'] = str(e)

    # Quick scan to identify modified/new/deleted files (may be expensive for large projects)
    # Make this optional via ?quick=1
    quick_param = request.args.get('quick', '0').lower()
    do_quick = quick_param in ('1', 'true', 'yes', 'on')
    scan_summary = {'scanned_at': None, 'duration_seconds': None, 'modified_count': None, 'examples': []}
    if do_quick:
        try:
            # Determine application root (reuse monitor logic)
            app_root = os.path.dirname(os.path.abspath(current_app.root_path)) if current_app else os.getcwd()
            start = time.time()
            current_checksums = monitor.scan_directory(app_root)
            duration = time.time() - start

            modified = []
            # Detect modified/deleted
            for fp, original in (monitor.checksums or {}).items():
                if fp in current_checksums:
                    if original.get('checksum') != current_checksums[fp].get('checksum'):
                        modified.append(fp)
                else:
                    modified.append(f"{fp} (deleted)")

            # Detect new files
            for fp in current_checksums:
                if fp not in (monitor.checksums or {}):
                    modified.append(f"{fp} (new)")

            scan_summary['scanned_at'] = datetime.utcnow().isoformat()
            scan_summary['duration_seconds'] = round(duration, 3)
            scan_summary['modified_count'] = len(modified)
            # Provide a few examples only
            scan_summary['examples'] = modified[:10]
        except Exception as e:
            scan_summary['error'] = str(e)
    else:
        # Lightweight summary from stored checksums
        try:
            scan_summary['scanned_at'] = None
            scan_summary['duration_seconds'] = 0
            scan_summary['modified_count'] = None
            scan_summary['examples'] = []
            scan_summary['note'] = 'Quick scan skipped. Add ?quick=1 to run a full scan (can be slow).'
        except Exception:
            pass

    info['quick_scan'] = scan_summary

    # Database connectivity check (lightweight)
    db_status = {'ok': False, 'latency_ms': None, 'error': None}
    try:
        start = time.time()
        # Use a minimal scalar select to verify connectivity
        with db.session.begin():
            db.session.execute('SELECT 1')
        db_status['latency_ms'] = int((time.time() - start) * 1000)
        db_status['ok'] = True
    except Exception as e:
        db_status['error'] = str(e)

    info['database'] = db_status

    # System / environment info
    try:
        info['system'] = {
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'server_time_utc': datetime.utcnow().isoformat()
        }
    except Exception:
        pass

    # Process / runtime stats
    try:
        proc = {
            'pid': os.getpid(),
            'ppid': os.getppid() if hasattr(os, 'getppid') else None,
            'threads': None,
        }
        # Thread count via threading module
        try:
            import threading as _thr
            proc['threads'] = _thr.active_count()
        except Exception:
            proc['threads'] = None

        # Uptime from app.start_time if available
        try:
            start = getattr(current_app, 'start_time', None)
            if start:
                proc['uptime_seconds'] = int((datetime.utcnow() - start).total_seconds())
            else:
                proc['uptime_seconds'] = None
        except Exception:
            proc['uptime_seconds'] = None

        # Try to get memory/cpu via psutil if installed, otherwise skip
        try:
            import importlib
            psutil = importlib.import_module('psutil')
            p = psutil.Process(os.getpid())
            mem = p.memory_info()
            proc['memory_rss'] = getattr(mem, 'rss', None)
            proc['memory_vms'] = getattr(mem, 'vms', None)
            # cpu_percent may take a short interval
            try:
                proc['cpu_percent'] = p.cpu_percent(interval=0.1)
            except Exception:
                proc['cpu_percent'] = None
        except Exception:
            # psutil not available or error
            proc['memory_rss'] = None
            proc['memory_vms'] = None
            proc['cpu_percent'] = None

        info['process'] = proc
    except Exception:
        pass

    # Application info (version, config hints)
    try:
        app_info = {}
        game_cfg = getattr(current_app, 'config', {}).get('GAME_CONFIG') if hasattr(current_app, 'config') else None
        if isinstance(game_cfg, dict):
            app_info['version'] = game_cfg.get('version')
        else:
            app_info['version'] = None
        info['app'] = app_info
    except Exception:
        pass

    # Disk usage for application root and instance folder
    try:
        roots = {}
        try:
            roots['app_root'] = app_root
        except Exception:
            roots['app_root'] = None

        # instance directory is typically next to the app package directory
        instance_dir = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance')
        roots['instance'] = instance_dir

        disks = {}
        for k, path in roots.items():
            try:
                if path and os.path.exists(path):
                    du = shutil.disk_usage(path)
                    disks[k] = {'path': path, 'total': du.total, 'used': du.used, 'free': du.free}
                else:
                    disks[k] = {'path': path, 'exists': False}
            except Exception as e:
                disks[k] = {'path': path, 'error': str(e)}

        info['disk'] = disks
    except Exception:
        pass

    # Overall OK hint
    try:
        mod_count = scan_summary.get('modified_count') if isinstance(scan_summary.get('modified_count'), int) else None
        info['ok'] = (not monitor.integrity_compromised) and db_status.get('ok', False) and (mod_count is None or mod_count == 0)
    except Exception:
        info['ok'] = (not monitor.integrity_compromised) and db_status.get('ok', False)

    # If the client prefers HTML (browser), render the UI template so visiting
    # /integrity/status in a browser shows a friendly page instead of raw JSON.
    accept = request.headers.get('Accept', '')
    if 'text/html' in accept or request.args.get('format') == 'html':
        try:
            return render_template('integrity/status.html')
        except Exception:
            # If template rendering fails, fall back to JSON response
            pass

    return jsonify(info)


@integrity_bp.route('/ui')
@login_required
def ui():
    """Render a modern UI page for integrity status"""
    return render_template('integrity/status.html')

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
