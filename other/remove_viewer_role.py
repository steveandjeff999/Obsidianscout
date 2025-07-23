import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db
from app.models import Role

app = create_app()

with app.app_context():
    viewer = Role.query.filter_by(name='viewer').first()
    if viewer:
        db.session.delete(viewer)
        db.session.commit()
        print("Viewer role removed from the database.")
    else:
        print("Viewer role does not exist in the database.") 