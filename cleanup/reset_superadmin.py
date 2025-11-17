#!/usr/bin/env python3
"""
Create or reset the superadmin user for Obsidianscout.

This script will ensure there is a user with username "superadmin",
scouting_team_number 0, and password "0" and that the user has the
`superadmin` role.
"""
import sys
import os

# Make sure repo root is on path so imports work when running this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Role


def reset_superadmin_user():
    print("Resetting superadmin user...")

    # Ensure the superadmin role exists
    super_role = Role.query.filter_by(name='superadmin').first()
    if not super_role:
        print("Creating 'superadmin' role...")
        super_role = Role(name='superadmin', description='Limited superadmin role for user management')
        db.session.add(super_role)
        db.session.commit()

    username = 'superadmin'
    password = '0'

    user = User.query.filter_by(username=username).first()

    if user:
        print(f"User '{username}' exists. Resetting password, team number, and roles...")
        user.set_password(password)
        user.scouting_team_number = 0
        user.is_active = True
        # Ensure only has superadmin role (clear others)
        user.roles = []
        user.roles.append(super_role)
    else:
        print(f"Creating new user '{username}'...")
        user = User(username=username, email=None, scouting_team_number=0)
        user.set_password(password)
        user.roles.append(super_role)
        db.session.add(user)

    db.session.commit()

    print("\nSuperadmin user is ready:")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print("  scouting_team_number: 0")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        reset_superadmin_user()
