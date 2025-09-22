#!/usr/bin/env python3
"""Debug script to investigate user_roles table issues"""

from app import create_app, db
from app.models import User, Role

def main():
    app = create_app()
    with app.app_context():
        print('Debugging user_roles table...')
        
        # Check if there are any triggers or virtual table issues  
        result = db.session.execute(db.text("SELECT type, name FROM sqlite_master WHERE name LIKE '%user_roles%'"))
        related_objects = result.fetchall()
        print(f'user_roles related SQLite objects: {len(related_objects)}')
        for obj in related_objects:
            print(f'  {obj[0]}: {obj[1]}')
        
        # Try raw SQL insert
        print('\nTrying raw SQL insert...')
        try:
            db.session.execute(db.text('INSERT INTO user_roles (user_id, role_id) VALUES (1, 2)'))
            db.session.commit()
            print('Raw SQL insert successful')
            
            # Check if it worked
            result = db.session.execute(db.text('SELECT * FROM user_roles'))
            rows = result.fetchall()
            print(f'user_roles after raw insert: {len(rows)} entries')
            for row in rows:
                print(f'  user_id: {row[0]}, role_id: {row[1]}')
                
        except Exception as e:
            print(f'Raw SQL insert failed: {e}')
            db.session.rollback()
            
        # Check if SQLAlchemy relationship works after raw insert
        print('\nTesting SQLAlchemy relationship after raw insert...')
        user = User.query.get(1)
        if user:
            print(f'User {user.username} roles via relationship: {[r.name for r in user.roles]}')
        
        # Now try SQLAlchemy-based role assignment
        print('\nTrying SQLAlchemy role assignment...')
        try:
            user = User.query.get(1)
            admin_role = Role.query.filter_by(name='admin').first()
            if user and admin_role:
                # Clear and re-add
                user.roles = []
                db.session.flush()
                user.roles.append(admin_role)
                db.session.commit()
                print('SQLAlchemy role assignment successful')
                
                # Check user_roles table
                result = db.session.execute(db.text('SELECT * FROM user_roles'))
                rows = result.fetchall()
                print(f'user_roles after SQLAlchemy: {len(rows)} entries')
                
        except Exception as e:
            print(f'SQLAlchemy role assignment failed: {e}')
            db.session.rollback()

if __name__ == '__main__':
    main()
