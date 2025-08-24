import os
import sys

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import User, Role

app = create_app()

with app.app_context():
    # Check if superadmin already exists
    superadmin_user = User.query.filter_by(username='superadmin').first()
    if superadmin_user:
        superadmin_user.scouting_team_number = 5454
        db.session.commit()
        print("Superadmin user updated successfully.")
    else:
        # Create superadmin user
        superadmin_user = User(username='superadmin', scouting_team_number=5454)
        superadmin_user.set_password('kimber1911')

        # Get or create superadmin role
        superadmin_role = Role.query.filter_by(name='superadmin').first()
        if not superadmin_role:
            superadmin_role = Role(name='superadmin', description='Super Administrator')
            db.session.add(superadmin_role)

        superadmin_user.roles.append(superadmin_role)
        db.session.add(superadmin_user)
        db.session.commit()
        print("Superadmin user created successfully.")
