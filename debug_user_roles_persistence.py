#!/usr/bin/env python3
"""Debug script to investigate user_roles table persistence issues"""

from app import create_app, db
from app.models import User, Role

def main():
    app = create_app()
    with app.app_context():
        print('Investigating why user_roles table isn\'t being populated...')
        
        # Check for any triggers on user_roles
        result = db.session.execute(db.text('SELECT sql FROM sqlite_master WHERE type="trigger" AND tbl_name="user_roles"'))
        triggers = result.fetchall()
        print(f'Triggers on user_roles: {len(triggers)}')
        for trigger in triggers:
            print(f'  {trigger[0]}')
        
        # Check if CRSQLite is creating issues with user_roles
        result = db.session.execute(db.text('SELECT sql FROM sqlite_master WHERE name LIKE "%user_roles%"'))
        user_roles_objects = result.fetchall()
        print(f'\nAll user_roles related objects:')
        for obj in user_roles_objects:
            print(f'  {obj[0]}')
        
        # Let's manually insert multiple role assignments and see what happens
        print('\nManually inserting multiple user role assignments...')
        
        # Clear the table first
        db.session.execute(db.text('DELETE FROM user_roles'))
        db.session.commit()
        
        # Insert multiple role assignments manually
        assignments = [
            (1, 2),  # admin -> admin role
            (2, 1),  # superadmin -> superadmin role  
            (3, 1),  # bob -> superadmin role
            (6, 2),  # jim -> admin role
            (8, 2),  # bill -> admin role
            (9, 2),  # 9988 -> admin role
            (10, 4), # phill -> scout role
            (10, 2), # phill -> admin role
            (10, 3), # phill -> analytics role
            (11, 2), # 0 -> admin role
        ]
        
        for user_id, role_id in assignments:
            try:
                db.session.execute(db.text('INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)'), 
                                  {'user_id': user_id, 'role_id': role_id})
            except Exception as e:
                print(f'Failed to insert user_id={user_id}, role_id={role_id}: {e}')
        
        db.session.commit()
        
        # Check the result
        result = db.session.execute(db.text('SELECT * FROM user_roles'))
        user_roles = result.fetchall()
        print(f'\nuser_roles entries after manual inserts: {len(user_roles)}')
        for ur in user_roles:
            print(f'  user_id: {ur[0]}, role_id: {ur[1]}')
            
        # Now test if SQLAlchemy can see these relationships
        print('\nTesting if SQLAlchemy can see manually inserted relationships...')
        users = User.query.all()
        for user in users:
            roles = [r.name for r in user.roles]
            if roles:  # Only show users with roles
                print(f'  {user.username}: {roles}')

if __name__ == '__main__':
    main()
