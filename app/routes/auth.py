from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
try:
    from werkzeug.urls import url_parse
except ImportError:
    # For newer versions of Werkzeug (>= 2.0)
    from urllib.parse import urlparse as url_parse
from functools import wraps
from app import db
from app.models import User, Role
from datetime import datetime
from app.utils.system_check import SystemCheck
from app.utils.theme_manager import ThemeManager
from werkzeug.utils import secure_filename
import os

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('auth', __name__, url_prefix='/auth')

def role_required(*roles):
    """Decorator to require specific roles"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            
            # Check if user has any of the required roles
            user_roles = current_user.get_role_names()
            if not any(role in user_roles for role in roles):
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('main.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require admin role"""
    return role_required('admin')(f)

def analytics_required(f):
    """Decorator to require admin or analytics role"""
    return role_required('admin', 'analytics')(f)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember_me = bool(request.form.get('remember_me'))
        
        user = User.query.filter_by(username=username).first()
        
        if user is None or not user.check_password(password):
            flash('Invalid username or password', 'error')
            return redirect(url_for('auth.login'))
        
        if not user.is_active:
            flash('Your account has been deactivated. Please contact an administrator.', 'error')
            return redirect(url_for('auth.login'))
        
        # Update last login time
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        login_user(user, remember=remember_me)
        
        # Redirect to next page or appropriate page based on role
        next_page = request.args.get('next')
        
        if not next_page or url_parse(next_page).netloc != '':
            # For scouts, redirect to scouting page instead of main dashboard
            if user.has_role('scout') and not user.has_role('admin') and not user.has_role('analytics'):
                next_page = url_for('scouting.index')
            else:
                next_page = url_for('main.index')
        
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(next_page)
    
    return render_template('auth/login.html', **get_theme_context())

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png']:
                    if len(file.read()) > 2 * 1024 * 1024:
                        flash('Profile picture must be less than 2MB.', 'error')
                        return redirect(request.url)
                    file.seek(0)
                    avatar_dir = os.path.join(current_app.root_path, 'static', 'img', 'avatars')
                    if not os.path.exists(avatar_dir):
                        os.makedirs(avatar_dir)
                    avatar_filename = f'user_{current_user.id}{ext}'
                    file_path = os.path.join(avatar_dir, avatar_filename)
                    file.save(file_path)
                    current_user.profile_picture = f'img/avatars/{avatar_filename}'
                    db.session.commit()
                    flash('Profile picture updated!', 'success')
                else:
                    flash('Only JPG and PNG images are allowed.', 'error')
            else:
                flash('No file selected.', 'error')
        return redirect(request.url)
    return render_template('auth/profile.html', user=current_user, **get_theme_context())

@bp.route('/users')
@admin_required
def manage_users():
    users = User.query.all()
    roles = Role.query.all()
    return render_template('auth/manage_users.html', users=users, roles=roles, **get_theme_context())

@bp.route('/add_user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form.get('email')
        password = request.form['password']
        role_ids = request.form.getlist('roles')
        
        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('auth.add_user'))
        
        # Check if email already exists (if provided)
        if email and User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('auth.add_user'))
        
        # Set email to None if empty string is provided
        if email == '':
            email = None
            
        user = User(username=username, email=email)
        user.set_password(password)
        
        # Add roles
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                user.roles.append(role)
        
        db.session.add(user)
        db.session.commit()
        
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('auth.manage_users'))
    
    roles = Role.query.all()
    return render_template('auth/add_user.html', roles=roles, **get_theme_context())

@bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.username = request.form['username']
        
        # Handle email (convert empty string to None)
        email = request.form.get('email')
        user.email = None if email == '' else email
        
        user.is_active = bool(request.form.get('is_active'))
        
        # Update password if provided
        new_password = request.form.get('password')
        if new_password:
            user.set_password(new_password)
        
        # Update roles
        user.roles.clear()
        role_ids = request.form.getlist('roles')
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                user.roles.append(role)
        
        # --- Profile picture upload logic ---
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename:
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png']:
                    if len(file.read()) > 2 * 1024 * 1024:
                        flash('Profile picture must be less than 2MB.', 'error')
                        return redirect(request.url)
                    file.seek(0)
                    avatar_dir = os.path.join(current_app.root_path, 'static', 'img', 'avatars')
                    if not os.path.exists(avatar_dir):
                        os.makedirs(avatar_dir)
                    avatar_filename = f'user_{user.id}{ext}'
                    file_path = os.path.join(avatar_dir, avatar_filename)
                    file.save(file_path)
                    user.profile_picture = f'img/avatars/{avatar_filename}'
                else:
                    flash('Only JPG and PNG images are allowed.', 'error')
                    return redirect(request.url)
            elif not user.profile_picture:
                user.profile_picture = 'img/avatars/default.png'
        
        db.session.commit()
        flash(f'User {user.username} updated successfully', 'success')
        return redirect(url_for('auth.manage_users'))
    
    roles = Role.query.all()
    return render_template('auth/edit_user.html', user=user, roles=roles, **get_theme_context())

@bp.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('auth.manage_users'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    flash(f'User {username} deleted successfully', 'success')
    return redirect(url_for('auth.manage_users'))

@bp.route('/system_check', methods=['GET', 'POST'])
@admin_required
def system_check():
    """Run system checks to validate integrity of the application"""
    if request.method == 'POST':
        # Create system check instance
        checker = SystemCheck()
        
        # Run all checks
        results = checker.run_all_checks()
        
        # Return results as JSON if requested
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(results)
        
        # Flash message based on overall status
        if results['overall']['status'] == 'pass':
            flash('System check completed successfully.', 'success')
        elif results['overall']['status'] == 'warn':
            flash('System check completed with warnings. Please review the results.', 'warning')
        else:
            flash('System check failed. Critical issues were detected.', 'error')
        
        return render_template('auth/system_check.html', results=results, **get_theme_context())
    
    return render_template('auth/system_check.html', **get_theme_context())

@bp.route('/admin/settings')
@admin_required
def admin_settings():
    """Admin settings page"""
    # Get version information for admin dashboard
    update_available = False
    current_version = None
    
    try:
        from app.utils.remote_config import fetch_remote_config, is_remote_version_newer
        from app.utils.version_manager import VersionManager
        
        # Get version info
        version_manager = VersionManager()
        current_version = version_manager.get_current_version()
        repo_url = version_manager.config.get('repository_url', '')
        branch = version_manager.config.get('branch', 'main')
        
        # Check for updates
        remote_config = fetch_remote_config(repo_url, branch)
        if remote_config and 'version' in remote_config:
            remote_version = remote_config['version']
            update_available, _ = is_remote_version_newer(current_version, remote_version)
    except Exception as e:
        current_app.logger.error(f"Error checking for updates in admin settings: {e}")
    
    return render_template('auth/admin_settings.html', 
                          update_available=update_available,
                          current_version=current_version, **get_theme_context())

@bp.route('/admin/integrity')
@admin_required
def admin_integrity():
    """View integrity monitoring configuration"""
    status = {}
    if hasattr(current_app, 'file_integrity_monitor'):
        monitor = current_app.file_integrity_monitor
        status = {
            'compromised': monitor.integrity_compromised,
            'files_monitored': len(monitor.checksums),
            'has_password': monitor.integrity_password_hash is not None,
            'warning_only_mode': monitor.warning_only_mode
        }
    
    return render_template('auth/admin_integrity.html', status=status, **get_theme_context())

@bp.route('/admin/integrity/password', methods=['POST'])
@admin_required
def update_integrity_password():
    """Update the integrity password"""
    new_password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    
    if not new_password or not confirm_password:
        flash("Both password fields are required.", "danger")
        return redirect(url_for('auth.admin_integrity'))
    
    if new_password != confirm_password:
        flash("Passwords do not match.", "danger")
        return redirect(url_for('auth.admin_integrity'))
    
    if len(new_password) < 6:
        flash("Password must be at least 6 characters long.", "danger")
        return redirect(url_for('auth.admin_integrity'))
    
    if hasattr(current_app, 'file_integrity_monitor'):
        monitor = current_app.file_integrity_monitor
        monitor.set_integrity_password(new_password)
        flash("Integrity password updated successfully.", "success")
    else:
        flash("File integrity monitoring is not available.", "danger")
    
    return redirect(url_for('auth.admin_integrity'))

@bp.route('/admin/integrity/reinitialize', methods=['POST'])
@admin_required
def reinitialize_integrity():
    """Reinitialize file integrity monitoring"""
    if hasattr(current_app, 'file_integrity_monitor'):
        monitor = current_app.file_integrity_monitor
        
        # Reset the compromised flag before reinitializing
        monitor.integrity_compromised = False
        
        # Reinitialize the checksums
        monitor.initialize_checksums()
        
        # Perform an integrity check immediately after reinitializing
        integrity_ok = monitor.check_integrity()
        
        if integrity_ok:
            flash(f"File integrity monitoring reinitialized. Now monitoring {len(monitor.checksums)} files. All files verified.", "success")
        else:
            if monitor.warning_only_mode:
                flash(f"File integrity monitoring reinitialized, but some files were modified. Warning-only mode is enabled.", "warning")
            else:
                flash(f"File integrity monitoring reinitialized, but some files were modified. You may need to verify integrity.", "warning")
    else:
        flash("File integrity monitoring is not available.", "danger")
    
    return redirect(url_for('auth.admin_integrity'))

# Context processor to make current_user and role functions available in templates
@bp.app_context_processor
def inject_auth_vars():
    return {
        'current_user': current_user,
        'user_has_role': lambda role: current_user.is_authenticated and current_user.has_role(role)
    }
