from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
try:
    from werkzeug.urls import url_parse
except ImportError:
    # For newer versions of Werkzeug (>= 2.0)
    from urllib.parse import urlparse as url_parse
from functools import wraps
from app import db
from app.models import User, Role, DatabaseChange
from sqlalchemy import or_, func
from datetime import datetime
from app.utils.system_check import SystemCheck
from app.utils.theme_manager import ThemeManager
from werkzeug.utils import secure_filename
import os
from app.utils import notifications as notif_util
from app.utils import emailer as emailer_util
from app.utils import token as token_util
import json
 

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

            # Superadmin: full access to role-restricted endpoints
            if current_user.has_role('superadmin'):
                return f(*args, **kwargs)
            
            # Check if user has any of the required roles
            user_roles = current_user.get_role_names()
            if not any(role in user_roles for role in roles):
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('main.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require admin or superadmin role"""
    return role_required('admin', 'superadmin')(f)

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
        team_number = request.form.get('team_number')
        remember_me = bool(request.form.get('remember_me'))

        if not team_number:
            flash('Team number is required.', 'error')
            return redirect(url_for('auth.login'))
        
        try:
            team_number = int(team_number)
        except ValueError:
            flash('Team number must be a valid number.', 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(username=username, scouting_team_number=team_number).first()
        
        if user is None or not user.check_password(password):
            flash('Invalid username, password, or team number.', 'error')
            return redirect(url_for('auth.login'))
        
        if not user.is_active:
            flash('Your account has been deactivated. Please contact an administrator.', 'error')
            return redirect(url_for('auth.login'))
        
        # Update last login time
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        login_user(user, remember=remember_me)
        
        # Check if user must change password
        if user.must_change_password:
            flash('You must change your password before continuing.', 'warning')
            return redirect(url_for('auth.change_password'))
        
        # If user has no roles, redirect to select role page
        if not user.has_roles():
            return redirect(url_for('auth.select_role'))

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


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash('Email is required', 'error')
            return redirect(url_for('auth.forgot_password'))
        user = User.query.filter_by(email=email).first()
        if not user:
            # Don't reveal user existence; send generic message
            flash('If an account with that email exists, a reset link has been sent.', 'info')
            return redirect(url_for('auth.login'))

        token = token_util.generate_reset_token(email)
        reset_url = url_for('auth.reset_password', token=token, _external=True)
        subject = 'ObsidianScout password reset'
        body = f"Hello {user.username},\n\nA password reset was requested for your account.\n\nUsername: {user.username}\n\nClick the link below to reset your password (valid for 1 hour):\n\n{reset_url}\n\nIf you did not request this, please ignore this email."
        ok, msg = emailer_util.send_email(to=email, subject=subject, body=body)
        if ok:
            flash('If an account with that email exists, a reset link has been sent.', 'info')
            return redirect(url_for('auth.login'))

        # Sending failed. Persist the outgoing reset email to instance/reset_outbox.json for manual review
        try:
            outbox_path = os.path.join(current_app.instance_path, 'reset_outbox.json')
            if not os.path.exists(current_app.instance_path):
                os.makedirs(current_app.instance_path, exist_ok=True)
            out = []
            if os.path.exists(outbox_path):
                try:
                    with open(outbox_path, 'r', encoding='utf-8') as f:
                        out = json.load(f) or []
                except Exception:
                    out = []
            entry = {
                'to': email,
                'subject': subject,
                'body': body,
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }
            out.append(entry)
            with open(outbox_path, 'w', encoding='utf-8') as f:
                json.dump(out, f, indent=2)
        except Exception:
            current_app.logger.exception('Failed to write reset_outbox.json')

        # Show helpful messages: generic flash plus debug-mode immediate link for testing
        flash('Failed to send reset email; the reset has been queued for manual review by an administrator.', 'warning')
        if current_app.debug:
            # In debug mode, render a page showing the reset link so you can finish testing.
            return render_template('auth/forgot_password.html', debug_reset_url=reset_url, **get_theme_context())
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html', **get_theme_context())


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    email = token_util.verify_reset_token(token)
    if not email:
        flash('Reset link is invalid or expired.', 'error')
        return redirect(url_for('auth.login'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid reset link.', 'error')
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        password = request.form.get('password')
        confirm = request.form.get('confirm')
        if not password or password != confirm:
            flash('Passwords do not match or are empty.', 'error')
            return redirect(url_for('auth.reset_password', token=token))
        user.set_password(password)
        user.must_change_password = False
        db.session.commit()
        flash('Password has been reset. You may now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token, **get_theme_context())

@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Force password change for users who must change password, or allow voluntary changes.

    Previously this endpoint blocked access for normal users who didn't have the
    `must_change_password` flag set. We allow any authenticated user to change
    their password voluntarily while preserving the forced-change behavior at
    login (login redirects to this page when must_change_password is True).
    """
    # No early redirect: allow any authenticated user to use this page.
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        # Verify current password
        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
            return render_template('auth/change_password.html', **get_theme_context())
        
        # Validate new password
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return render_template('auth/change_password.html', **get_theme_context())
        
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return render_template('auth/change_password.html', **get_theme_context())
        
        if new_password == current_password:
            flash('New password must be different from current password.', 'error')
            return render_template('auth/change_password.html', **get_theme_context())
        
        # Update password and clear the must_change_password flag. Wrap commit
        # in try/except to avoid leaving the user in a broken state on DB errors.
        current_user.set_password(new_password)
        current_user.must_change_password = False
        try:
            db.session.commit()
        except Exception:
            current_app.logger.exception('Failed to commit password change to database')
            db.session.rollback()
            flash('An internal error occurred while saving your new password. Please try again or contact an administrator.', 'error')
            return render_template('auth/change_password.html', **get_theme_context())

        flash('Password changed successfully!', 'success')
        
        # Redirect to appropriate page based on role
        if current_user.has_role('scout') and not current_user.has_role('admin') and not current_user.has_role('analytics'):
            return redirect(url_for('scouting.index'))
        else:
            return redirect(url_for('main.index'))
    
    return render_template('auth/change_password.html', **get_theme_context())

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        team_number = request.form.get('team_number')
        email = request.form.get('email')

        if not team_number:
            flash('Team number is required.', 'error')
            return redirect(url_for('auth.register'))

        # Check if account creation is locked for this team
        from app.models import ScoutingTeamSettings
        team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=int(team_number)).first()
        if team_settings and team_settings.account_creation_locked:
            flash('Account creation is currently locked for this team. Please contact your team administrator.', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.register'))

        user = User.query.filter_by(username=username).first()
        if user is not None:
            flash('Username already exists.', 'error')
            return redirect(url_for('auth.register'))

        # Normalize email value: treat empty string as None
        if email == '':
            email = None
        # Check for duplicate email if provided
        if email and User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
            return redirect(url_for('auth.register'))

        new_user = User(username=username, email=email, scouting_team_number=team_number)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        # Check if this is the first user for the team
        team_user_count = User.query.filter_by(scouting_team_number=team_number).count()
        if team_user_count == 1:
            # First user becomes admin
            admin_role = Role.query.filter_by(name='admin').first()
            if admin_role:
                new_user.roles.append(admin_role)
            db.session.commit()
        flash('Congratulations, you are now a registered user!', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', **get_theme_context())

@bp.route('/select_role', methods=['GET', 'POST'])
@login_required
def select_role():
    if current_user.roles:
        # If user already has a role, redirect them
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        role_id = request.form.get('role')
        if not role_id:
            flash('You must select a role.', 'error')
            return redirect(url_for('auth.select_role'))

        role = Role.query.get(role_id)
        if not role or role.name == 'superadmin':
            flash('Invalid role selected.', 'error')
            return redirect(url_for('auth.select_role'))

        current_user.roles.append(role)
        db.session.commit()
        flash(f'Your role has been set to {role.name}.', 'success')
        return redirect(url_for('main.index'))

    roles = Role.query.all()
    return render_template('auth/select_role.html', roles=roles, **get_theme_context())

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
        # If a profile picture was uploaded, handle it first
        if 'profile_picture' in request.files and request.files['profile_picture'].filename:
            file = request.files['profile_picture']
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
            return redirect(request.url)

        # Otherwise process username/email update from the form
        new_username = request.form.get('username')
        new_email = request.form.get('email')

        # Validate username uniqueness if changed
        if new_username and new_username != current_user.username:
            if User.query.filter_by(username=new_username).first():
                flash('Username already exists.', 'error')
                return redirect(request.url)
            current_user.username = new_username

        # Normalize email (empty string => None) and validate uniqueness
        if new_email == '':
            new_email = None
        if new_email and new_email != current_user.email:
            if User.query.filter_by(email=new_email).first():
                flash('Email already exists.', 'error')
                return redirect(request.url)
            current_user.email = new_email
        elif new_email is None:
            current_user.email = None

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(request.url)
    return render_template('auth/profile.html', user=current_user, **get_theme_context())


# Notifications management (simple file-backed storage to avoid DB migrations)
@bp.context_processor
def inject_notifications():
    try:
        current = notif_util.load_notifications()
    except Exception:
        current = []
    # Filter out expired notifications here if desired
    return {'site_notifications': current}


@bp.route('/notifications/suggestions', methods=['GET'])
@login_required
def notification_suggestions():
    """Return JSON suggestions for users or teams for the notifications form.

    Query params:
      - q: search string
      - type: 'users' or 'teams' (default 'users')
    """
    q = (request.args.get('q') or '').strip()
    typ = (request.args.get('type') or 'users').lower()
    results = []
    try:
        # Debug log to help track why the endpoint might return HTML (e.g. redirects)
        try:
            current_app.logger.debug('notifications_suggestions requested by %s from %s', getattr(current_user, 'username', 'anonymous'), request.remote_addr)
        except Exception:
            pass
        if typ == 'teams':
            # Distinct team numbers (as strings)
            query = User.query.filter(User.scouting_team_number != None)
            if q:
                query = query.filter(func.cast(User.scouting_team_number, db.String).contains(q))
            teams = query.with_entities(User.scouting_team_number).distinct().limit(200).all()
            # Flatten and convert to strings
            results = [str(t[0]) for t in teams if t[0] is not None]
        else:
            # users
            query = User.query
            if q:
                query = query.filter(User.username.ilike(f"%{q}%"))
            users = query.with_entities(User.username).limit(200).all()
            results = [u[0] for u in users if u[0]]
    except Exception:
        # On error return empty list but still 200 so frontend can handle gracefully
        results = []
    return jsonify({'results': results})


@bp.route('/notifications/dismiss', methods=['POST'])
@login_required
def dismiss_notification():
    """Record a server-side dismissal for the current user (optional)"""
    data = request.get_json() or {}
    notif_id = data.get('notif_id')
    if not notif_id:
        return jsonify({'success': False, 'message': 'notif_id required'}), 400
    ok = notif_util.dismiss_for_user(current_user.username, notif_id)
    return jsonify({'success': bool(ok)})


@bp.route('/notifications/dismissed', methods=['GET'])
@login_required
def get_dismissed_notifications():
    dismissed = notif_util.get_dismissed_for_user(current_user.username)
    return jsonify({'dismissed': dismissed})


@bp.route('/users')
@admin_required
def manage_users():
    query = User.query
    search = request.args.get('search')
    if search:
        # Handle both username and team number searches properly
        if search.isdigit():
            # Search by exact team number if numeric
            query = query.filter(
                or_(
                    User.username.contains(search),
                    User.scouting_team_number == int(search)
                )
            )
        else:
            # Search by username and team number as string
            query = query.filter(
                or_(
                    User.username.contains(search),
                    func.cast(User.scouting_team_number, db.String).contains(search)
                )
            )

    if not current_user.has_role('superadmin'):
        query = query.filter_by(scouting_team_number=current_user.scouting_team_number)

    # Compute counts: for superadmins show global totals; for regular admins show team-limited totals
    if current_user.has_role('superadmin'):
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
    else:
        total_users = User.query.filter_by(scouting_team_number=current_user.scouting_team_number).count()
        active_users = User.query.filter_by(scouting_team_number=current_user.scouting_team_number, is_active=True).count()

    users = query.all()
    all_roles = Role.query.all()
    return render_template('auth/manage_users.html', users=users, all_roles=all_roles, search=search,
                           total_users=total_users, active_users=active_users,
                           **get_theme_context())

@bp.route('/add_user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form.get('email')
        password = request.form['password']
        scouting_team_number = request.form.get('scouting_team_number')
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
            
        user = User(username=username, email=email, scouting_team_number=scouting_team_number)
        user.set_password(password)
        
        # Add roles
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                # Only superadmins can assign the superadmin role
                if role.name == 'superadmin' and not current_user.has_role('superadmin'):
                    flash('Only superadmins can create other superadmins', 'error')
                    return redirect(url_for('auth.add_user'))
                user.roles.append(role)
        
        db.session.add(user)
        db.session.flush()  # ensure ID
        # Manual change tracking fallback
        try:
            DatabaseChange.log_change(
                table_name='user',
                record_id=user.id,
                operation='insert',
                new_data={
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'scouting_team_number': user.scouting_team_number,
                    'is_active': user.is_active
                },
                server_id='local'
            )
        except Exception as e:
            current_app.logger.error(f"Manual insert change tracking failed: {e}")
        db.session.commit()
        
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('auth.manage_users'))
    
    roles = Role.query.all()
    return render_template('auth/add_user.html', roles=roles, **get_theme_context())

@bp.route('/users/update/<int:user_id>', methods=['POST'])
@admin_required
def update_user(user_id):
    from flask import current_app
    current_app.logger.info(f"Update user request for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    current_app.logger.info(f"Form data: {dict(request.form)}")
    
    if not current_user.has_role('superadmin'):
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('auth.manage_users'))

    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, current active status: {user.is_active}")

    user.username = request.form.get('username')
    user.scouting_team_number = request.form.get('scouting_team_number')

    password = request.form.get('password')
    if password:
        user.set_password(password)

    # Handle is_active checkbox
    old_status = user.is_active
    user.is_active = 'is_active' in request.form
    current_app.logger.info(f"Active status changed from {old_status} to {user.is_active}")

    role_ids = request.form.getlist('roles')
    user.roles.clear()
    for role_id in role_ids:
        role = Role.query.get(role_id)
        if role:
            # Only superadmins can assign the superadmin role
            if role.name == 'superadmin' and not current_user.has_role('superadmin'):
                flash('Only superadmins can assign superadmin roles', 'error')
                return redirect(url_for('auth.manage_users'))
            user.roles.append(role)

    db.session.commit()
    # Manual update change tracking fallback
    try:
        DatabaseChange.log_change(
            table_name='user',
            record_id=user.id,
            operation='update',
            new_data={
                'id': user.id,
                'username': user.username,
                'scouting_team_number': user.scouting_team_number,
                'is_active': user.is_active
            },
            server_id='local'
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Manual update change tracking failed: {e}")
    current_app.logger.info(f"User {user.username} updated successfully. New active status: {user.is_active}")
    flash(f'User {user.username} updated successfully.', 'success')
    return redirect(url_for('auth.manage_users'))

@bp.route('/users/<int:user_id>')
@login_required
def view_user(user_id):
    """View user profile/details"""
    user = User.query.get_or_404(user_id)
    
    # Check permissions - users can view their own profile, admins can view team members, superadmins can view all
    if not (current_user.id == user_id or 
            current_user.has_role('superadmin') or 
            (current_user.has_role('admin') and user.scouting_team_number == current_user.scouting_team_number)):
        flash('You do not have permission to view this user.', 'error')
        return redirect(url_for('main.index'))
    
    # Get user's recent activity (if they have scouting data)
    from app.models import ScoutingData
    recent_scouting = ScoutingData.query.filter_by(
        scout_name=user.username,
        scouting_team_number=user.scouting_team_number
    ).order_by(ScoutingData.timestamp.desc()).limit(10).all()
    
    return render_template('auth/view_user.html', 
                         user=user, 
                         recent_scouting=recent_scouting)

@bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if not current_user.has_role('superadmin') and user.scouting_team_number != current_user.scouting_team_number:
        flash('You do not have permission to edit this user.', 'error')
        return redirect(url_for('auth.manage_users'))
    
    if request.method == 'POST':
        user.username = request.form['username']
        user.scouting_team_number = request.form.get('scouting_team_number')
        
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
                # Only superadmins can assign the superadmin role
                if role.name == 'superadmin' and not current_user.has_role('superadmin'):
                    flash('Only superadmins can assign superadmin roles', 'error')
                    return redirect(url_for('auth.edit_user', user_id=user.id))
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
    from flask import current_app
    current_app.logger.info(f"Soft delete attempt for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    
    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, roles: {[role.name for role in user.roles]}, active: {user.is_active}")
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        current_app.logger.info("Blocked - cannot delete own account")
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Prevent deactivating other superadmin users (safety measure)
    if user.has_role('superadmin'):
        current_app.logger.info("Blocked - cannot deactivate superadmin user")
        flash('Cannot deactivate other superadmin users for security reasons', 'error')
        return redirect(url_for('auth.manage_users'))
    
    username = user.username
    current_app.logger.info(f"Proceeding with soft delete of user: {username}")
    
    # Use soft delete instead of hard delete for sync consistency
    user.is_active = False
    # Update timestamp to ensure sync detection
    if hasattr(user, 'updated_at'):
        user.updated_at = datetime.utcnow()
    elif hasattr(user, 'last_login'):
        user.last_login = datetime.utcnow()  # Use as modification timestamp
    
    db.session.commit()
    # Manual soft delete change tracking fallback
    try:
        DatabaseChange.log_change(
            table_name='user',
            record_id=user.id,
            operation='soft_delete',
            new_data={
                'id': user.id,
                'username': user.username,
                'is_active': user.is_active
            },
            server_id='local'
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Manual soft delete change tracking failed: {e}")
    
    current_app.logger.info(f"Soft delete completed for user: {username}")
    flash(f'User {username} deactivated successfully', 'success')
    return redirect(url_for('auth.manage_users'))

@bp.route('/hard_delete_user/<int:user_id>', methods=['POST'])
@admin_required
def hard_delete_user(user_id):
    """Permanently delete a user from the database (hard delete)"""
    from flask import current_app
    current_app.logger.info(f"Hard delete attempt for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    
    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, roles: {[role.name for role in user.roles]}")
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        current_app.logger.info("Blocked - cannot delete own account")
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Extra security check - only superadmin can hard delete
    if not current_user.has_role('superadmin'):
        current_app.logger.info("Blocked - user is not superadmin")
        flash('Only superadmins can permanently delete users', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Prevent deleting other superadmin users (safety measure)
    if user.has_role('superadmin'):
        current_app.logger.info("Blocked - cannot delete superadmin user")
        flash('Cannot permanently delete other superadmin users for security reasons', 'error')
        return redirect(url_for('auth.manage_users'))
    
    username = user.username
    user_id = user.id  # Store ID before deletion
    current_app.logger.info(f"Proceeding with hard delete of user: {username}")
    
    # Manual hard delete change tracking BEFORE deletion
    try:
        DatabaseChange.log_change(
            table_name='user',
            record_id=user_id,
            operation='delete',
            old_data={
                'id': user_id, 
                'username': username,
                'scouting_team_number': user.scouting_team_number,
                'is_active': user.is_active
            },
            server_id='local'
        )
        current_app.logger.info(f"✅ Logged hard delete change for user {username}")
    except Exception as e:
        current_app.logger.error(f"❌ Manual hard delete change tracking failed: {e}")
    
    # Hard delete - this will trigger the after_delete event
    db.session.delete(user)
    db.session.commit()
    
    current_app.logger.info(f"Hard delete completed for user: {username}")
    flash(f'User {username} permanently deleted', 'warning')
    return redirect(url_for('auth.manage_users'))

@bp.route('/restore_user/<int:user_id>', methods=['POST'])
@admin_required
def restore_user(user_id):
    """Restore a soft-deleted (deactivated) user"""
    from flask import current_app
    current_app.logger.info(f"Restore attempt for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    
    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, roles: {[role.name for role in user.roles]}, active: {user.is_active}")
    
    if user.is_active:
        current_app.logger.info("User is already active")
        flash('User is already active', 'info')
        return redirect(url_for('auth.manage_users'))
    
    username = user.username
    current_app.logger.info(f"Proceeding with restore of user: {username}")
    
    # Reactivate user
    user.is_active = True
    if hasattr(user, 'updated_at'):
        user.updated_at = datetime.utcnow()
    
    db.session.commit()
    # Manual restore change tracking fallback
    try:
        DatabaseChange.log_change(
            table_name='user',
            record_id=user.id,
            operation='reactivate',
            new_data={'id': user.id, 'username': user.username, 'is_active': user.is_active},
            server_id='local'
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Manual restore change tracking failed: {e}")
    
    current_app.logger.info(f"Restore completed for user: {username}")
    flash(f'User {username} restored successfully', 'success')
    return redirect(url_for('auth.manage_users'))

@bp.route('/delete_user_permanently/<int:user_id>', methods=['POST'])
@admin_required
def delete_user_permanently(user_id):
    """Permanently delete a user from the database with change tracking for sync"""
    from flask import current_app
    
    # First, let's print to console to see if function is being called
    print(f"🔴 DELETE FUNCTION CALLED for user_id: {user_id}")
    current_app.logger.error(f"🔴 DELETE FUNCTION CALLED for user_id: {user_id}")
    
    current_app.logger.info(f"Delete user permanently attempt for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    
    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, roles: {[role.name for role in user.roles]}, active: {user.is_active}")
    
    print(f"🔴 Target user found: {user.username}")
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        print("🔴 Blocked - cannot delete own account")
        current_app.logger.info("Blocked - cannot delete own account")
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Extra security check - only superadmin can delete permanently
    if not current_user.has_role('superadmin'):
        print("🔴 Blocked - user is not superadmin")
        current_app.logger.info("Blocked - user is not superadmin")
        flash('Only superadmins can permanently delete users', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Prevent deleting other superadmin users (safety measure)
    if user.has_role('superadmin'):
        print("🔴 Blocked - cannot delete superadmin user")
        current_app.logger.info("Blocked - cannot delete superadmin user")
        flash('Cannot delete other superadmin users for security reasons', 'error')
        return redirect(url_for('auth.manage_users'))
    
    username = user.username
    print(f"🔴 Proceeding with permanent deletion of user: {username}")
    current_app.logger.info(f"Proceeding with permanent deletion of user: {username}")
    
    # Delete user - this will trigger the after_delete event and track the change for sync
    db.session.delete(user)
    db.session.commit()
    
    print(f"🔴 Permanent deletion completed for user: {username}")
    current_app.logger.info(f"Permanent deletion completed for user: {username}")
    flash(f'User {username} permanently deleted and synced across servers', 'warning')
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
    # Get account lock status for current user's team
    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    account_creation_locked = team_settings.account_creation_locked if team_settings else False

    return render_template('auth/admin_settings.html', 
                          account_creation_locked=account_creation_locked,
                          **get_theme_context())


@bp.route('/admin/account-lock-status', methods=['GET'])
@admin_required
def account_lock_status():
    """Return JSON with current account creation lock status for the admin's team"""
    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    locked = team_settings.account_creation_locked if team_settings else False
    return jsonify({'locked': bool(locked)})

@bp.route('/admin/toggle-account-lock', methods=['POST'])
@admin_required
def toggle_account_lock():
    """Toggle account creation lock for the admin's team"""
    from app.models import ScoutingTeamSettings
    
    # Get or create team settings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    if not team_settings:
        team_settings = ScoutingTeamSettings(scouting_team_number=current_user.scouting_team_number)
        db.session.add(team_settings)
    
    # Toggle the lock status
    if team_settings.account_creation_locked:
        team_settings.unlock_account_creation(current_user)
        flash('Account creation has been unlocked for your team.', 'success')
    else:
        team_settings.lock_account_creation(current_user)
        flash('Account creation has been locked for your team.', 'warning')
    
    db.session.commit()
    return redirect(url_for('auth.admin_settings'))

# Context processor to make current_user and role functions available in templates
@bp.app_context_processor
def inject_auth_vars():
    return {
        'current_user': current_user,
        'user_has_role': lambda role: current_user.is_authenticated and current_user.has_role(role)
    }
