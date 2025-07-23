import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db
from app.models import Role

app = create_app()

with app.app_context():
    viewer = Role.query.filter_by(name='viewer').first()
    if not viewer:
        viewer = Role(name='viewer', description='Read-only access to view data and reports, cannot modify or enter data')
        db.session.add(viewer)
        db.session.commit()
        print("Viewer role added to the database.")
    else:
        print("Viewer role already exists in the database.") 