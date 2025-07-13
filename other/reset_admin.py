#!/usr/bin/env python3
"""
Reset admin user script for 5454Scout authentication system.
This script creates or resets the admin user with default credentials.
"""

import sys
import os

# Add the parent directory to the Python path so we can import the app module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, Role

def reset_admin_user():
    """Create or reset the admin user account"""
    print("Resetting admin user...")
    
    # Check if admin role exists
    admin_role = Role.query.filter_by(name='admin').first()
    if not admin_role:
        print("Creating admin role...")
        admin_role = Role(name='admin', description='Full system access including user management and configuration')
        db.session.add(admin_role)
        db.session.commit()
    
    # Admin user details
    admin_username = 'admin'
    admin_password = 'password'
    
    # Check if admin user exists
    admin_user = User.query.filter_by(username=admin_username).first()
    
    if admin_user:
        print(f"Admin user '{admin_username}' already exists. Resetting password and roles...")
        admin_user.set_password(admin_password)
        
        # Make sure user is active
        admin_user.is_active = True
        
        # Clear and set roles to ensure admin role is present
        admin_user.roles = []
        admin_user.roles.append(admin_role)
    else:
        print(f"Creating new admin user: {admin_username}")
        admin_user = User(username=admin_username, email=None)
        admin_user.set_password(admin_password)
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
    
    # Save changes
    db.session.commit()
    
    print("\nAdmin user reset successfully!")
    print(f"Username: {admin_username}")
    print(f"Password: {admin_password}")
    print("You can now log in with these credentials.")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        reset_admin_user()
