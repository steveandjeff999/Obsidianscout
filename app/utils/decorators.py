"""
Authentication and authorization decorators for ObsidianScout
Provides role-based access control decorators for routes
"""

from functools import wraps
from flask import redirect, url_for, flash
from flask_login import login_required, current_user


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


def superadmin_required(f):
    """Decorator to require superadmin role only"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        # Only allow superadmin
        if not current_user.has_role('superadmin'):
            flash('You need superadmin privileges to access this page.', 'error')
            return redirect(url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function
