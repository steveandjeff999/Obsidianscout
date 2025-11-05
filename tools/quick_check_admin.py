"""
Quick check: what is admin user's scouting_team_number?
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app import create_app
from app.models import User

app = create_app()

with app.app_context():
    print("Checking admin user...")
    admin = User.query.filter_by(username='admin').first()
    if admin:
        print(f"\nAdmin user found:")
        print(f"  ID: {admin.id}")
        print(f"  Username: {admin.username}")
        print(f"  Scouting Team Number: {admin.scouting_team_number}")
        print(f"  Is Active: {admin.is_active}")
        
        if admin.scouting_team_number == 23:
            print(f"\n** WARNING: Admin has scouting_team_number=23 (should be 5454) **")
            print(f"** Updating to 5454... **")
            admin.scouting_team_number = 5454
            from app.models import db
            db.session.commit()
            print(f"** Updated! Admin now has scouting_team_number={admin.scouting_team_number} **")
        elif admin.scouting_team_number == 5454:
            print(f"\n✓ Admin correctly has scouting_team_number=5454")
        else:
            print(f"\n** Admin has scouting_team_number={admin.scouting_team_number} (expected 5454) **")
    else:
        print("\n** ERROR: Admin user not found! **")
