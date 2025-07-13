#!/usr/bin/env python3
"""
Create test scout user script for testing scout-only access.
"""

from app import create_app, db
from app.models import User, Role

def create_test_scout():
    """Create a test scout user with scout role only"""
    print("Creating test scout user...")
    
    # Check if scout role exists
    scout_role = Role.query.filter_by(name='scout').first()
    if not scout_role:
        print("Creating scout role...")
        scout_role = Role(name='scout', description='Limited access for scouting data entry only')
        db.session.add(scout_role)
        db.session.commit()
    
    # Scout user details
    scout_username = 'Scout User'
    scout_password = 'scout123'
    
    # Check if scout user exists
    scout_user = User.query.filter_by(username=scout_username).first()
    
    if scout_user:
        print(f"Scout user '{scout_username}' already exists. Resetting password and roles...")
        scout_user.set_password(scout_password)
        
        # Make sure user is active
        scout_user.is_active = True
        
        # Clear and set roles to ensure scout role only
        scout_user.roles = []
        scout_user.roles.append(scout_role)
    else:
        print(f"Creating new scout user: {scout_username}")
        scout_user = User(username=scout_username, email=None)
        scout_user.set_password(scout_password)
        scout_user.roles.append(scout_role)
        db.session.add(scout_user)
    
    # Save changes
    db.session.commit()
    
    print("\nScout user created/updated successfully!")
    print(f"Username: {scout_username}")
    print(f"Password: {scout_password}")
    print("This user can only access the scouting pages.")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        create_test_scout()
