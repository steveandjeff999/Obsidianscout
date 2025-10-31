#!/usr/bin/env python3
"""
Setup SuperAdmin Account Script

This script creates or updates a superadmin account with the specified credentials.
- Username: superadmin
- Password: password
- Team Number: 0
- Must change password on first login: True
"""

import os
import sys

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from app import create_app, db
from app.models import User, Role

app = create_app()

with app.app_context():
    print("Setting up SuperAdmin account...")
    
    # Get or create superadmin role
    superadmin_role = Role.query.filter_by(name='superadmin').first()
    if not superadmin_role:
        superadmin_role = Role(name='superadmin', description='Super Administrator with database access')
        db.session.add(superadmin_role)
        print("Created superadmin role.")
    
    # Check if superadmin user already exists
    superadmin_user = User.query.filter_by(username='superadmin').first()
    
    if superadmin_user:
        print("SuperAdmin user already exists. Updating credentials...")
        # Update existing user
        superadmin_user.set_password('password')
        superadmin_user.scouting_team_number = 0
        superadmin_user.must_change_password = True
        superadmin_user.is_active = True
        
        # Ensure user has superadmin role
        if superadmin_role not in superadmin_user.roles:
            superadmin_user.roles.append(superadmin_role)
        
        # Remove other roles to keep it clean
        superadmin_user.roles = [superadmin_role]
        
    else:
        print("Creating new SuperAdmin user...")
        # Create new superadmin user
        superadmin_user = User(
            username='superadmin',
            scouting_team_number=0,
            must_change_password=True,
            is_active=True
        )
        superadmin_user.set_password('password')
        superadmin_user.roles.append(superadmin_role)
        db.session.add(superadmin_user)
    
    try:
        db.session.commit()
        print(" SuperAdmin account setup complete!")
        print(f"   Username: superadmin")
        print(f"   Password: password")
        print(f"   Team Number: 0")
        print(f"   Must Change Password: True")
        print(f"   Role: superadmin")
        print("")
        print("️  The superadmin will be required to change their password on first login.")
        print("   Only superadmin users can access the Database Admin interface.")
        
    except Exception as e:
        print(f" Error setting up SuperAdmin account: {e}")
        db.session.rollback()
        sys.exit(1)
