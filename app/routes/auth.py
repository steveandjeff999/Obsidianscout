from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
try:
    from werkzeug.urls import url_parse
except ImportError:
    # For newer versions of Werkzeug (>= 2.0)
    from urllib.parse import urlparse as url_parse
from functools import wraps
from app import db
from app.models import User, Role, DatabaseChange
from app.utils.api_utils import safe_int_team_number
from sqlalchemy import or_, func
from datetime import datetime, timezone
from app.utils.system_check import SystemCheck
# ThemeManager removed from auth routes; provide a lightweight context function below.
from werkzeug.utils import secure_filename
import os
from app.utils import notifications as notif_util
from app.utils import user_prefs as user_prefs_util
from app.utils.database_migrations import column_exists_for_bind
from app.models_misc import NotificationLog
from app.utils.emailer import send_email as send_email_util
from app.utils import emailer as emailer_util
from app.utils import token_utils as token_util
import json
 
def validate_csrf_token():
    token = request.form.get('csrf_token')
    if not token and request.is_json:
        data = request.get_json()
        if data:
            token = data.get('csrf_token')
    if not token:
        token = request.headers.get('X-CSRFToken')

    if not token or token != session.get('csrf_token'):
        if not request.is_json and request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash('CSRF validation failed. Please try again.', 'error')
        return False
    return True

def get_theme_context():
    # Provide minimal placeholders so templates can render without theme endpoints
    return {
        'themes': {},
        'current_theme_id': 'light',
        # Mark auth pages to render without global chrome for layout consistency
        'no_chrome': True
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
        if not validate_csrf_token():
            return redirect(url_for('auth.login'))

        username = request.form['username']
        password = request.form['password']
        team_number = request.form.get('team_number')
        remember_me = bool(request.form.get('remember_me'))

        if not team_number:
            flash('Team number is required.', 'error')
            return redirect(url_for('auth.login'))
        
        # Support alphanumeric team numbers for offseason (e.g., '581B')
        team_number = safe_int_team_number(team_number)
        if team_number is None:
            flash('Team number is required.', 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(username=username, scouting_team_number=team_number).first()
        
        if user is None or not user.check_password(password):
            flash('Invalid username, password, or team number.', 'error')
            return redirect(url_for('auth.login'))
        
        if not user.is_active:
            flash('Your account has been deactivated. Please contact an administrator.', 'error')
            return redirect(url_for('auth.login'))
        
        # Update last login time
        user.last_login = datetime.now(timezone.utc)
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
        if not validate_csrf_token():
            return redirect(url_for('auth.forgot_password'))
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
        ok, msg = emailer_util.send_email(to=email, subject=subject, body=body, bypass_user_opt_out=True)
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
                'created_at': datetime.now(timezone.utc).isoformat() + 'Z'
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
        if not validate_csrf_token():
            return redirect(url_for('auth.reset_password', token=token))
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
        if not validate_csrf_token():
            return redirect(url_for('auth.change_password'))
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
        if not validate_csrf_token():
            return redirect(url_for('auth.register'))
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
        team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=safe_int_team_number(team_number)).first()
        if team_settings and team_settings.account_creation_locked:
            flash('Account creation is currently locked for this team. Please contact your team administrator.', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.register'))

        # Enforce username uniqueness within the specified scouting team only
        # Support alphanumeric team numbers for offseason (e.g., '581B')
        team_number = safe_int_team_number(team_number)
        user = User.query.filter_by(username=username, scouting_team_number=team_number).first()
        if user is not None:
            flash('Username already exists for that team.', 'error')
            return redirect(url_for('auth.register'))

        # Normalize email value: treat empty string as None
        if email == '':
            email = None
        # Check for duplicate email if provided
        if email and User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
            return redirect(url_for('auth.register'))

        # Team number already converted by safe_int_team_number above
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
        if not validate_csrf_token():
            return redirect(url_for('auth.select_role'))
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
        if not validate_csrf_token():
            return redirect(request.url)
        # If a profile picture was uploaded, handle it first
        if 'profile_picture' in request.files and request.files['profile_picture'].filename:
            file = request.files['profile_picture']
            filename = secure_filename(file.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png']:
                if len(file.read()) > 10 * 1024 * 1024:
                    flash('Profile picture must be less than 10MB.', 'error')
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

        # Validate username uniqueness if changed (scoped to the user's team)
        if new_username and new_username != current_user.username:
            conflict = User.query.filter_by(username=new_username, scouting_team_number=current_user.scouting_team_number).filter(User.id != current_user.id).first()
            if conflict:
                flash('Username already exists for your team.', 'error')
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
        # Only-password-reset toggle
        only_pw_reset = request.form.get('only_password_reset_emails')
        only_pw_val = True if only_pw_reset in ('on', 'true', '1') else False
        # Prefer to persist to DB column when available; otherwise fallback to JSON file prefs
        try:
            if column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
                current_user.only_password_reset_emails = only_pw_val
            else:
                user_prefs_util.set_pref(current_user.username, 'only_password_reset_emails', only_pw_val)
        except Exception:
            # In case of any unexpected error, try fallback persistence to JSON
            try:
                user_prefs_util.set_pref(current_user.username, 'only_password_reset_emails', only_pw_val)
            except Exception:
                pass

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(request.url)
    # Prefer DB column if present, otherwise fall back to file-backed user_prefs
    # Prefer DB column if present, otherwise fall back to file-backed user_prefs
    try:
        if column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
            only_pw_reset_pref = bool(getattr(current_user, 'only_password_reset_emails', False))
        else:
            only_pw_reset_pref = user_prefs_util.get_pref(current_user.username, 'only_password_reset_emails', False)
    except Exception:
        only_pw_reset_pref = user_prefs_util.get_pref(current_user.username, 'only_password_reset_emails', False)
    return render_template('auth/profile.html', user=current_user, only_password_reset_emails=only_pw_reset_pref, **get_theme_context())


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
    if not validate_csrf_token():
        return jsonify({'success': False, 'message': 'CSRF validation failed'}), 400
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


@bp.route('/notifications/manage', methods=['GET'])
@role_required('superadmin')
def manage_site_notifications():
    """Superadmin UI: view and manage site notifications."""
    notifs = notif_util.load_notifications()
    # Provide some lightweight user/team lists to help form selection
    from app.models import User
    users = User.query.with_entities(User.username, User.email).all()
    # Distinct team numbers from users (strings)
    team_nums = list({str(u[0]) for u in User.query.with_entities(User.scouting_team_number).distinct().all() if u[0]})
    ctx = get_theme_context()
    ctx['no_chrome'] = False
    return render_template('auth/notifications.html', notifications=notifs, users=users, teams=sorted(team_nums), **ctx)


@bp.route('/notifications', methods=['GET'])
@role_required('superadmin')
def auth_notifications_root():
    return redirect(url_for('auth.manage_site_notifications'))


@bp.route('/notifications/create', methods=['POST'])
@role_required('superadmin')
def create_notification():
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_site_notifications'))
    data = request.form or request.get_json() or {}
    message = data.get('message') or ''
    level = data.get('level') or 'info'
    audience = data.get('audience') or 'site'
    teams_raw = data.get('teams') or ''
    users_raw = data.get('users') or ''
    # Parse comma-separated lists into arrays
    teams = [t.strip() for t in teams_raw.split(',') if t.strip()] if teams_raw else []
    users = [u.strip() for u in users_raw.split(',') if u.strip()] if users_raw else []
    try:
        notif = notif_util.add_notification(message=message, level=level, audience=audience, teams=teams, users=users)
        flash('Notification created', 'success')
    except Exception as e:
        flash(f'Failed to create notification: {str(e)}', 'error')
    return redirect(url_for('auth.manage_site_notifications'))


@bp.route('/notifications/delete/<int:notif_id>', methods=['POST'])
@role_required('superadmin')
def delete_notification(notif_id):
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_site_notifications'))
    try:
        notif_util.remove_notification(notif_id)
        flash('Notification removed', 'success')
    except Exception as e:
        flash(f'Failed to delete notification: {str(e)}', 'error')
    return redirect(url_for('auth.manage_site_notifications'))


@bp.route('/notifications/update/<int:notif_id>', methods=['POST'])
@role_required('superadmin')
def update_notification(notif_id):
    """Update an existing notification (message, level, audience, teams, users)."""
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_site_notifications'))
    try:
        message = request.form.get('message') or ''
        level = request.form.get('level') or 'info'
        audience = request.form.get('audience') or 'site'
        teams_raw = request.form.get('teams') or ''
        users_raw = request.form.get('users') or ''
        teams = [t.strip() for t in teams_raw.split(',') if t.strip()] if teams_raw else []
        users = [u.strip() for u in users_raw.split(',') if u.strip()] if users_raw else []

        notifs = notif_util.load_notifications()
        updated = False
        for n in notifs:
            if int(n.get('id')) == int(notif_id):
                n['message'] = message
                n['level'] = level
                n['audience'] = audience
                n['teams'] = teams
                n['users'] = users
                updated = True
                break
        if updated:
            notif_util.save_notifications(notifs)
            flash('Notification updated', 'success')
        else:
            flash('Notification not found', 'error')
    except Exception as e:
        current_app.logger.exception('Failed to update notification: %s', e)
        flash(f'Failed to update notification: {e}', 'error')
    return redirect(url_for('auth.manage_site_notifications'))


@bp.route('/notifications/send-email/<int:notif_id>', methods=['POST'])
@role_required('superadmin')
def send_notification_as_email(notif_id):
    """Send the specified notification to applicable users by email.
    Sends each email individually to avoid leaking recipient addresses to others.
    """
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_site_notifications'))
    try:
        notifs = notif_util.load_notifications()
        target = next((n for n in notifs if n.get('id') == int(notif_id)), None)
        if not target:
            flash('Notification not found', 'error')
            return redirect(url_for('auth.manage_site_notifications'))

        # Build recipients according to audience
        recipients = set()
        from app.models import User
        if target.get('audience') == 'site':
            users = User.query.with_entities(User.email).filter(User.email != None).all()
            recipients.update([u[0] for u in users if u and u[0]])
        elif target.get('audience') == 'teams':
            teams = target.get('teams') or []
            for t in teams:
                try:
                    tn = int(t)
                except Exception:
                    # skip invalid team number
                    continue
                users = User.query.filter_by(scouting_team_number=tn).with_entities(User.email).all()
                recipients.update([u[0] for u in users if u and u[0]])
        elif target.get('audience') == 'users':
            user_names = target.get('users') or []
            for uname in user_names:
                u = User.query.filter_by(username=uname).first()
                if u and u.email:
                    recipients.add(u.email)

        # Respect user preference to only receive password reset emails: if any users
        # have `only_password_reset_emails` set, exclude them from this notification (this
        # route is used for site notifications and is not a password reset email).
        if recipients:
            try:
                # Query users in the recipients list and check their preferences
                from app import db
                from sqlalchemy import inspect as sa_inspect
                eng = db.get_engine(current_app)
                try:
                    inspector = sa_inspect(eng)
                    cols = [c['name'] for c in inspector.get_columns('user')] if 'user' in inspector.get_table_names() else []
                except Exception:
                    cols = []
                if 'only_password_reset_emails' in cols:
                    rows = User.query.filter(User.email.in_(list(recipients))).with_entities(
                        User.username, User.email, User.only_password_reset_emails
                    ).all()
                else:
                    rows = User.query.filter(User.email.in_(list(recipients))).with_entities(
                        User.username, User.email
                    ).all()
                excluded_emails = set()
                for row in rows:
                    try:
                        # Rows may be a tuple (username, email, only_pw_reset) if DB column exists
                        if len(row) == 3:
                            uname, email, only_pw = row
                            if only_pw:
                                excluded_emails.add(email)
                                continue
                        else:
                            uname, email = row
                        # Legacy fallback: check file-backed preferences
                        if user_prefs_util.get_pref(uname, 'only_password_reset_emails', False):
                            excluded_emails.add(email)
                    except Exception:
                        # ignore per-user read errors
                        pass
            except Exception as e:
                current_app.logger.exception('Failed to check recipients opt-out settings: %s', e)
                excluded_emails = set()
            if excluded_emails:
                recipients = recipients - excluded_emails
                current_app.logger.info('Excluded %d recipient(s) from notification due to only_password_reset_emails setting', len(excluded_emails))
                flash(f"Excluded {len(excluded_emails)} recipient(s) who opted out of general emails.", 'info')

        subject = f"ObsidianScout Notification: {target.get('level', 'INFO').upper()}"
        body = target.get('message', '')
        success_count = 0
        fail_count = 0
        skipped_opt_out = 0
        fail_reasons = []
        for rcpt in recipients:
            try:
                ok, msg = emailer_util.send_email(to=rcpt, subject=subject, body=body)
                if ok:
                    success_count += 1
                else:
                    # If the mailer returned 'No recipients (all opted out)', treat as skipped opt-out
                    if msg and ('No recipients' in msg or 'opted out' in msg):
                        skipped_opt_out += 1
                    else:
                        fail_count += 1
                        fail_reasons.append(f"{rcpt}: {msg}")
            except Exception as e:
                fail_count += 1
                fail_reasons.append(f"{rcpt}: {str(e)}")

        # Compose a friendly summary message including skipped/opt-out recipients
        summary_parts = [f"Emails sent: {success_count}"]
        if fail_count:
            summary_parts.append(f"failed: {fail_count}")
        if skipped_opt_out:
            summary_parts.append(f"not sent (opted out): {skipped_opt_out}")
        summary = '; '.join(summary_parts)
        flash(summary, 'success' if fail_count == 0 else 'warning')
        if fail_reasons:
            current_app.logger.warning('Notification email errors: %s', '\n'.join(fail_reasons))
    except Exception as e:
        flash(f'Failed to send notification emails: {str(e)}', 'error')
    return redirect(url_for('auth.manage_site_notifications'))


@bp.route('/users', methods=['GET', 'POST'])
@admin_required
def manage_users():
    """List users (GET) and create users via AJAX/JSON (POST).

    Web UI: GET renders the management page. POST accepts JSON or form data and
    enforces team scoping: non-superadmin creators are restricted to their own
    scouting team; superadmins may set any target team.
    """
    # Handle creation via POST (support JSON for AJAX clients and form data for tests)
    if request.method == 'POST':
        # For non-JSON (form) requests, validate CSRF token
        if not request.is_json and not validate_csrf_token():
            flash('CSRF validation failed. Please try again.', 'error')
            return redirect(url_for('auth.manage_users'))

        data = request.get_json() if request.is_json else request.form
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        team_raw = data.get('scouting_team_number')
        roles_list = data.getlist('roles') if not request.is_json else (data.get('roles') or [])

        if not username or not password:
            if request.is_json:
                return jsonify({'success': False, 'error': 'username and password required', 'error_code': 'MISSING_FIELDS'}), 400
            flash('Username and password are required', 'error')
            return redirect(url_for('auth.manage_users'))

        # Scoping: admins are limited to their own team; superadmins may set team
        if not current_user.has_role('superadmin'):
            target_team = current_user.scouting_team_number
        else:
            try:
                target_team = safe_int_team_number(team_raw) if team_raw not in (None, '') else None
            except Exception:
                target_team = team_raw

        # Check username uniqueness per team
        if User.query.filter_by(username=username, scouting_team_number=target_team).first():
            if request.is_json:
                return jsonify({'success': False, 'error': 'Username already exists for that team', 'error_code': 'USERNAME_EXISTS'}), 409
            flash('Username already exists for the target team', 'error')
            return redirect(url_for('auth.manage_users'))

        if email == '':
            email = None
        if email and User.query.filter_by(email=email).first():
            if request.is_json:
                return jsonify({'success': False, 'error': 'Email already exists', 'error_code': 'EMAIL_EXISTS'}), 409
            flash('Email already exists', 'error')
            return redirect(url_for('auth.manage_users'))

        user = User(username=username, email=email, scouting_team_number=target_team)
        user.set_password(password)

        # Assign roles (form gives list of ids; JSON may pass list of names or ids)
        for r in roles_list:
            role_obj = None
            try:
                role_obj = Role.query.filter_by(name=str(r)).first()
            except Exception:
                pass
            if not role_obj:
                try:
                    role_obj = Role.query.get(int(r))
                except Exception:
                    role_obj = None
            if role_obj:
                if role_obj.name == 'superadmin' and not current_user.has_role('superadmin'):
                    if request.is_json:
                        return jsonify({'success': False, 'error': 'Only superadmins can assign superadmin role', 'error_code': 'PERMISSION_DENIED'}), 403
                    flash('Only superadmins can create other superadmins', 'error')
                    return redirect(url_for('auth.manage_users'))
                user.roles.append(role_obj)

        db.session.add(user)
        db.session.flush()
        try:
            DatabaseChange.log_change(
                table_name='user',
                record_id=user.id,
                operation='insert',
                new_data={'id': user.id, 'username': user.username, 'email': user.email, 'scouting_team_number': user.scouting_team_number, 'is_active': user.is_active},
                server_id='local'
            )
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to log DB change for user creation')
        db.session.commit()

        if request.is_json:
            return jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'team_number': user.scouting_team_number}}), 201
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('auth.manage_users'))

    # GET handling preserved below
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
        # Non-superadmin admins only see users on their own team; no team pagination needed
        query = query.filter_by(scouting_team_number=current_user.scouting_team_number)

    # Compute counts: for superadmins show global totals; for regular admins show team-limited totals
    if current_user.has_role('superadmin'):
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
    else:
        total_users = User.query.filter_by(scouting_team_number=current_user.scouting_team_number).count()
        active_users = User.query.filter_by(scouting_team_number=current_user.scouting_team_number, is_active=True).count()

    # --- Team pagination for superadmins: show teams 5 at a time when not searching ---
    users = None
    team_page = 1
    total_team_pages = 1
    total_teams = 0
    team_start = 0
    team_end = 0
    PAGE_SIZE = 10

    if current_user.has_role('superadmin') and not search:
        # Get distinct team numbers across users
        team_numbers = [t[0] for t in User.query.with_entities(User.scouting_team_number).distinct().all()]
        # Sort with None at the end (use robust sort for mixed types)
        from app.utils.team_utils import team_sort_key
        team_numbers = sorted(set(team_numbers), key=team_sort_key)
        total_teams = len(team_numbers)
        import math
        total_team_pages = max(1, math.ceil(total_teams / PAGE_SIZE))
        try:
            team_page = int(request.args.get('team_page', 1))
        except Exception:
            team_page = 1
        if team_page < 1:
            team_page = 1
        if team_page > total_team_pages:
            team_page = total_team_pages

        start_idx = (team_page - 1) * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        teams_to_show = team_numbers[start_idx:end_idx]

        # Build filter to include teams (including None)
        filters = []
        non_null_teams = [t for t in teams_to_show if t is not None]
        if non_null_teams:
            filters.append(User.scouting_team_number.in_(non_null_teams))
        if None in teams_to_show:
            filters.append(User.scouting_team_number.is_(None))

        if filters:
            users = query.filter(or_(*filters)).all()
        else:
            users = []

        team_start = start_idx + 1 if total_teams > 0 else 0
        team_end = min(end_idx, total_teams)
    else:
        # Not a paginated view (either admin scoped view or search results)
        users = query.all()
        # For non-superadmins, compute team counts for display
        if not current_user.has_role('superadmin'):
            total_teams = 1
            team_start = 1
            team_end = 1

    all_roles = Role.query.all()
    # These are superadmin/admin pages that should render with the global chrome
    # (sidebar/topbar) so the content is offset correctly. Override the default
    # auth no_chrome flag returned by get_theme_context().
    ctx = get_theme_context()
    ctx['no_chrome'] = False
    return render_template('auth/manage_users.html', users=users, all_roles=all_roles, search=search,
                           total_users=total_users, active_users=active_users,
                           team_page=team_page, total_team_pages=total_team_pages, total_teams=total_teams,
                           team_start=team_start, team_end=team_end,
                           **ctx)

@bp.route('/add_user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        if not validate_csrf_token():
            return redirect(url_for('auth.add_user'))
        username = request.form['username']
        email = request.form.get('email')
        password = request.form['password']
        # If creator is not a superadmin, lock new user to creator's scouting team
        if not current_user.has_role('superadmin'):
            scouting_team_number = current_user.scouting_team_number
        else:
            scouting_team_number = request.form.get('scouting_team_number')
        role_ids = request.form.getlist('roles')
        
        # Check if username already exists for the target team
        try:
            target_team = safe_int_team_number(scouting_team_number) if scouting_team_number not in (None, '') else None
        except Exception:
            target_team = scouting_team_number
        if User.query.filter_by(username=username, scouting_team_number=target_team).first():
            flash('Username already exists for the target team', 'error')
            return redirect(url_for('auth.add_user'))
        
        # Check if email already exists (if provided)
        if email and User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('auth.add_user'))
        
        # Set email to None if empty string is provided
        if email == '':
            email = None
            
        user = User(username=username, email=email, scouting_team_number=target_team)
        # Respect 'only_password_reset_emails' flag if provided
        only_pw_reset = request.form.get('only_password_reset_emails')
        only_pw_val = True if only_pw_reset in ('on', 'true', '1') else False
        # Prefer to persist to DB column when available; otherwise fallback to JSON file prefs
        try:
            if column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
                user.only_password_reset_emails = only_pw_val
            else:
                user_prefs_util.set_pref(user.username, 'only_password_reset_emails', only_pw_val)
        except Exception:
            try:
                user_prefs_util.set_pref(user.username, 'only_password_reset_emails', only_pw_val)
            except Exception:
                pass
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
            db.session.rollback()
            current_app.logger.error(f"Manual insert change tracking failed: {e}")
        db.session.commit()
        
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('auth.manage_users'))
    
    roles = Role.query.all()
    # Ensure sidebar/topbar chrome is present for administrative pages
    ctx = get_theme_context()
    ctx['no_chrome'] = False
    return render_template('auth/add_user.html', roles=roles, **ctx)

@bp.route('/users/update/<int:user_id>', methods=['POST'])
@admin_required
def update_user(user_id):
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_users'))
    from flask import current_app
    current_app.logger.info(f"Update user request for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    current_app.logger.info(f"Form data: {dict(request.form)}")
    # Load target user early so we can enforce scoped permissions
    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, current active status: {user.is_active}")

    # Permit action if current user is superadmin, or an admin managing users in their own team
    is_super = current_user.has_role('superadmin')
    is_team_admin = current_user.has_role('admin') and (user.scouting_team_number == current_user.scouting_team_number)
    if not (is_super or is_team_admin):
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('auth.manage_users'))

    # Prevent team-admins from modifying superadmin accounts
    if user.has_role('superadmin') and not is_super:
        flash('You do not have permission to modify superadmin users.', 'error')
        return redirect(url_for('auth.manage_users'))

    # Only superadmins can change username, team membership, or roles. Team admins may
    # toggle active status (deactivate/reactivate) and set a new password for team members.
    if is_super:
        # Validate uniqueness before applying changes
        new_username = request.form.get('username')
        new_team_raw = request.form.get('scouting_team_number')
        new_team = safe_int_team_number(new_team_raw) if new_team_raw not in (None, '') else None
        if new_username:
            conflict = User.query.filter(User.username == new_username, User.scouting_team_number == new_team, User.id != user.id).first()
            if conflict:
                flash('Another user already has that username for the selected team.', 'error')
                return redirect(url_for('auth.manage_users'))
        user.username = new_username
        user.scouting_team_number = new_team

    password = request.form.get('password')
    if password:
        # Allow both superadmins and team-admins to set passwords for users they manage
        user.set_password(password)

    # Handle is_active checkbox - team admins should be able to toggle this for team members
    old_status = user.is_active
    # Treat presence of checkbox as True/False
    user.is_active = 'is_active' in request.form
    current_app.logger.info(f"Active status changed from {old_status} to {user.is_active}")

    # Handle role updates: superadmins can change any roles; team-admins may change roles
    # for users in their own team but may NOT assign the superadmin role.
    if is_super or is_team_admin:
        # Prevent users from changing their own roles unless they are superadmin
        if user.id == current_user.id and not is_super:
            flash('You cannot modify your own roles.', 'error')
            return redirect(url_for('auth.manage_users'))

        role_ids = request.form.getlist('roles')
        user.roles.clear()
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                # Only superadmins can assign the superadmin role
                if role.name == 'superadmin' and not is_super:
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
        db.session.rollback()
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
        if not validate_csrf_token():
            return redirect(url_for('auth.edit_user', user_id=user.id))
        # Validate username uniqueness within the (possibly new) team before applying
        new_username = request.form['username']
        new_team_raw = request.form.get('scouting_team_number')
        try:
            new_team = int(new_team_raw) if new_team_raw not in (None, '') else None
        except Exception:
            new_team = new_team_raw
        conflict = User.query.filter(User.username == new_username, User.scouting_team_number == new_team, User.id != user.id).first()
        if conflict:
            flash('Another user already has that username for the selected team.', 'error')
            return redirect(url_for('auth.edit_user', user_id=user.id))
        user.username = new_username
        user.scouting_team_number = new_team
        
        # Handle email (convert empty string to None)
        email = request.form.get('email')
        user.email = None if email == '' else email
        
        user.is_active = bool(request.form.get('is_active'))
        # Admin-editable: allow admins to set whether this user only receives password reset emails
        only_pw_reset = request.form.get('only_password_reset_emails')
        only_pw_val = True if only_pw_reset in ('on', 'true', '1') else False
        # Prefer to persist to DB column when available; otherwise fallback to JSON file prefs
        try:
            if column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
                user.only_password_reset_emails = only_pw_val
            else:
                user_prefs_util.set_pref(user.username, 'only_password_reset_emails', only_pw_val)
        except Exception:
            try:
                user_prefs_util.set_pref(user.username, 'only_password_reset_emails', only_pw_val)
            except Exception:
                pass
        
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
                    if len(file.read()) > 10 * 1024 * 1024:
                        flash('Profile picture must be less than 10MB.', 'error')
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
    try:
        if column_exists_for_bind(db, 'users', 'user', 'only_password_reset_emails'):
            prefs_only_pw = bool(getattr(user, 'only_password_reset_emails', False))
        else:
            prefs_only_pw = user_prefs_util.get_pref(user.username, 'only_password_reset_emails', False)
    except Exception:
        prefs_only_pw = user_prefs_util.get_pref(user.username, 'only_password_reset_emails', False)
    return render_template('auth/edit_user.html', user=user, roles=roles, only_password_reset_emails=prefs_only_pw, **get_theme_context())

@bp.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_users'))
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
        user.updated_at = datetime.now(timezone.utc)
    elif hasattr(user, 'last_login'):
        user.last_login = datetime.now(timezone.utc)  # Use as modification timestamp
    
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
        db.session.rollback()
        current_app.logger.error(f"Manual soft delete change tracking failed: {e}")
    
    current_app.logger.info(f"Soft delete completed for user: {username}")
    flash(f'User {username} deactivated successfully', 'success')
    return redirect(url_for('auth.manage_users'))

@bp.route('/hard_delete_user/<int:user_id>', methods=['POST'])
@admin_required
def hard_delete_user(user_id):
    """Permanently delete a user from the database (hard delete)"""
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_users'))
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
        current_app.logger.info(f" Logged hard delete change for user {username}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f" Manual hard delete change tracking failed: {e}")
    
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
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_users'))
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
        user.updated_at = datetime.now(timezone.utc)
    
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
        db.session.rollback()
        current_app.logger.error(f"Manual restore change tracking failed: {e}")
    
    current_app.logger.info(f"Restore completed for user: {username}")
    flash(f'User {username} restored successfully', 'success')
    return redirect(url_for('auth.manage_users'))

@bp.route('/delete_user_permanently/<int:user_id>', methods=['POST'])
@admin_required
def delete_user_permanently(user_id):
    """Permanently delete a user from the database with change tracking for sync"""
    if not validate_csrf_token():
        return redirect(url_for('auth.manage_users'))
    from flask import current_app
    
    # First, let's print to console to see if function is being called
    print(f" DELETE FUNCTION CALLED for user_id: {user_id}")
    current_app.logger.error(f" DELETE FUNCTION CALLED for user_id: {user_id}")
    
    current_app.logger.info(f"Delete user permanently attempt for user_id: {user_id}")
    current_app.logger.info(f"Current user: {current_user.username}, roles: {[role.name for role in current_user.roles]}")
    
    user = User.query.get_or_404(user_id)
    current_app.logger.info(f"Target user: {user.username}, roles: {[role.name for role in user.roles]}, active: {user.is_active}")
    
    print(f" Target user found: {user.username}")
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        print(" Blocked - cannot delete own account")
        current_app.logger.info("Blocked - cannot delete own account")
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Extra security: allow permanent deletion by superadmins, or by admins for users
    # in their own scouting team. This enables team admins to permanently remove
    # users from their team while preventing cross-team deletions.
    allowed_to_permanently_delete = (
        current_user.has_role('superadmin') or
        (current_user.has_role('admin') and user.scouting_team_number == current_user.scouting_team_number)
    )
    if not allowed_to_permanently_delete:
        print(" Blocked - insufficient privileges to permanently delete user")
        current_app.logger.info("Blocked - insufficient privileges to permanently delete user")
        flash('Only superadmins or team admins (for their own team) can permanently delete users', 'error')
        return redirect(url_for('auth.manage_users'))
    
    # Prevent deleting other superadmin users (safety measure)
    if user.has_role('superadmin'):
        print(" Blocked - cannot delete superadmin user")
        current_app.logger.info("Blocked - cannot delete superadmin user")
        flash('Cannot delete other superadmin users for security reasons', 'error')
        return redirect(url_for('auth.manage_users'))
    
    username = user.username
    print(f" Proceeding with permanent deletion of user: {username}")
    current_app.logger.info(f"Proceeding with permanent deletion of user: {username}")
    
    # Delete user - this will trigger the after_delete event and track the change for sync
    db.session.delete(user)
    db.session.commit()
    
    print(f" Permanent deletion completed for user: {username}")
    current_app.logger.info(f"Permanent deletion completed for user: {username}")
    flash(f'User {username} permanently deleted', 'warning')
    return redirect(url_for('auth.manage_users'))

@bp.route('/system_check', methods=['GET', 'POST'])
@admin_required
def system_check():
    """Run system checks to validate integrity of the application"""
    if request.method == 'POST':
        if not validate_csrf_token():
            return redirect(url_for('auth.system_check'))
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

    # This is an administrative page that should render with the global
    # chrome (sidebar/topbar). get_theme_context() defaults auth pages to
    # no_chrome=True, so explicitly enable the chrome here to preserve the
    # standard admin layout and prevent content from overlapping the sidebar.
    ctx = get_theme_context()
    ctx['no_chrome'] = False
    # Load application version from app_config.json if available so the UI
    # displays the actual deployed version instead of a hard-coded value.
    app_version = None
    try:
        base = os.getcwd()
        cfg_path = os.path.join(base, 'app_config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                app_version = cfg.get('version')
    except Exception:
        try:
            current_app.logger.exception('Failed to load app_config.json for admin settings')
        except Exception:
            pass

    return render_template('auth/admin_settings.html',
                           account_creation_locked=account_creation_locked,
                           app_version=app_version,
                           scouting_team_settings=team_settings,
                           **ctx)


@bp.route('/admin/account-lock-status', methods=['GET'])
@admin_required
def account_lock_status():
    """Return JSON with current account creation lock status for the admin's team"""
    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    locked = team_settings.account_creation_locked if team_settings else False
    return jsonify({'locked': bool(locked)})


@bp.route('/admin/set-display-preference', methods=['POST'])
@admin_required
def set_display_preference():
    """Set per-team preference for displaying offseason team identifiers.

    Expects form data 'display_preference' with values '99xx' or 'letter'.
    """
    # This endpoint was removed in favor of a client-side per-user setting stored in
    # browser localStorage. Keep the route for compatibility but do not persist any
    # server-side state. Redirect back to admin settings.
    flash('Display preference is now controlled per-user in your browser (Settings page).', 'info')
    return redirect(url_for('auth.admin_settings'))

@bp.route('/admin/toggle-liquid-glass-buttons', methods=['POST'])
@admin_required
def toggle_liquid_glass_buttons():
    """Toggle liquid glass buttons setting for the admin's team"""
    if not validate_csrf_token():
        return redirect(url_for('auth.admin_settings'))
    from app.models import ScoutingTeamSettings
    
    # Get or create team settings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    if not team_settings:
        team_settings = ScoutingTeamSettings(scouting_team_number=current_user.scouting_team_number)
        db.session.add(team_settings)
    
    # Toggle the setting
    team_settings.liquid_glass_buttons = not team_settings.liquid_glass_buttons
    team_settings.updated_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    status = "enabled" if team_settings.liquid_glass_buttons else "disabled"
    flash(f'Liquid Glass Buttons have been {status} for your team.', 'success')
    
    return redirect(url_for('auth.admin_settings'))

@bp.route('/admin/liquid-glass-status', methods=['GET'])
def liquid_glass_status():
    """Return JSON with current liquid glass buttons status for the user's team"""
    if not current_user.is_authenticated:
        return jsonify({'enabled': False})
        
    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    enabled = team_settings.liquid_glass_buttons if team_settings else False
    return jsonify({'enabled': bool(enabled)})

@bp.route('/admin/toggle-spinning-counters', methods=['POST'])
@admin_required
def toggle_spinning_counters():
    """Toggle spinning counters setting for the admin's team"""
    if not validate_csrf_token():
        return redirect(url_for('auth.admin_settings'))
    from app.models import ScoutingTeamSettings
    
    # Get or create team settings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    if not team_settings:
        team_settings = ScoutingTeamSettings(scouting_team_number=current_user.scouting_team_number)
        db.session.add(team_settings)
    
    # Toggle the setting
    team_settings.spinning_counters_enabled = not team_settings.spinning_counters_enabled
    team_settings.updated_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    status = "enabled" if team_settings.spinning_counters_enabled else "disabled"
    flash(f'Spinning counters have been {status} for your team.', 'success')
    
    return redirect(url_for('auth.admin_settings'))

@bp.route('/admin/spinning-counter-status', methods=['GET'])
def spinning_counter_status():
    """Return JSON with current spinning-counter status for the user's team"""
    if not current_user.is_authenticated:
        return jsonify({'enabled': False})
        
    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.query.filter_by(scouting_team_number=current_user.scouting_team_number).first()
    enabled = team_settings.spinning_counters_enabled if team_settings else False
    return jsonify({'enabled': bool(enabled)})

@bp.route('/admin/toggle-account-lock', methods=['POST'])
@admin_required
def toggle_account_lock():
    """Toggle account creation lock for the admin's team"""
    if not validate_csrf_token():
        return redirect(url_for('auth.admin_settings'))
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


# -------------------------------------------------------------------------
# EPA Data Source Settings
# -------------------------------------------------------------------------

@bp.route('/admin/epa-settings', methods=['GET'])
@admin_required
def epa_settings():
    """Standalone EPA data-source settings page"""
    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.get_or_create_for_team(current_user.scouting_team_number)
    epa_source = getattr(team_settings, 'epa_source', 'scouted_only') or 'scouted_only'

    ctx = get_theme_context()
    ctx['no_chrome'] = False
    return render_template('auth/epa_settings.html',
                           epa_source=epa_source,
                           scouting_team_settings=team_settings,
                           **ctx)


@bp.route('/admin/epa-settings', methods=['POST'])
@admin_required
def epa_settings_save():
    """Save EPA data-source setting for the admin's scouting team"""
    if not validate_csrf_token():
        return redirect(url_for('auth.epa_settings'))

    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.get_or_create_for_team(current_user.scouting_team_number)

    new_source = request.form.get('epa_source', 'scouted_only')
    valid_sources = ('scouted_only', 'scouted_with_statbotics', 'statbotics_only',
                     'tba_opr_only', 'scouted_with_tba_opr')
    if new_source not in valid_sources:
        new_source = 'scouted_only'

    team_settings.epa_source = new_source
    team_settings.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    # Immediately flush all EPA caches so the new setting takes effect
    try:
        from app.utils.analysis import invalidate_epa_caches
        invalidate_epa_caches()
    except Exception:
        pass

    labels = {
        'scouted_only': 'Scouted Data Only',
        'scouted_with_statbotics': 'Scouted Data + Statbotics EPA Gap-Fill',
        'statbotics_only': 'Statbotics EPA Only',
        'tba_opr_only': 'TBA OPR Only',
        'scouted_with_tba_opr': 'Scouted Data + TBA OPR Gap-Fill',
    }
    flash(f'EPA data source set to: {labels.get(new_source, new_source)}', 'success')
    return redirect(url_for('auth.epa_settings'))


@bp.route('/admin/epa-source-status', methods=['GET'])
def epa_source_status():
    """Return JSON with current EPA source setting for the user's team"""
    if not current_user.is_authenticated:
        return jsonify({'epa_source': 'scouted_only'})

    from app.models import ScoutingTeamSettings
    team_settings = ScoutingTeamSettings.query.filter_by(
        scouting_team_number=current_user.scouting_team_number
    ).first()
    source = getattr(team_settings, 'epa_source', 'scouted_only') if team_settings else 'scouted_only'
    return jsonify({'epa_source': source or 'scouted_only'})


# Context processor to make current_user and role functions available in templates
@bp.app_context_processor
def inject_auth_vars():
    return {
        'current_user': current_user,
        'user_has_role': lambda role: current_user.is_authenticated and current_user.has_role(role)
    }
