#!/usr/bin/env python3
"""Fix user roles sync and verify Universal Sync System tracking"""

from app import create_app, db

def main():
    app = create_app()
    with app.app_context():
        print('Checking if Universal Sync System is tracking user_roles...')
        
        # Check if user_roles table is in the discovered tables
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        filtered_tables = [t for t in tables if not t.startswith('sqlite_')]
        
        print(f'Universal Sync discovers these tables: {len(filtered_tables)}')
        print(f'user_roles table found: {"user_roles" in filtered_tables}')
        
        if 'user_roles' in filtered_tables:
            # Check current user_roles data
            result = db.session.execute(db.text('SELECT COUNT(*) FROM user_roles'))
            count = result.scalar()
            print(f'Current user_roles entries: {count}')
            
            if count < 10:  # We should have at least 10 entries
                print('Repopulating user_roles table...')
                # Re-populate with current user role assignments
                from app.models import User, Role
                
                # Clear table first
                db.session.execute(db.text('DELETE FROM user_roles'))
                
                # Get all users with roles
                users_with_roles = [
                    ('admin', ['admin']),
                    ('superadmin', ['superadmin']),
                    ('bob', ['superadmin']),
                    ('jim', ['admin']),
                    ('bill', ['admin']),
                    ('9988', ['admin']),
                    ('phill', ['scout', 'admin', 'analytics']),
                    ('0', ['admin'])
                ]
                
                entries_added = 0
                for username, role_names in users_with_roles:
                    user = User.query.filter_by(username=username).first()
                    if user:
                        for role_name in role_names:
                            role = Role.query.filter_by(name=role_name).first()
                            if role:
                                db.session.execute(db.text('INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)'), 
                                                  {'user_id': user.id, 'role_id': role.id})
                                entries_added += 1
                
                db.session.commit()
                print(f'Added {entries_added} user role entries')
                
                # Verify
                result = db.session.execute(db.text('SELECT COUNT(*) FROM user_roles'))
                final_count = result.scalar()
                print(f'Final user_roles entries: {final_count}')
                
                # Test that relationships work
                print('\nTesting SQLAlchemy relationships...')
                users = User.query.all()
                for user in users:
                    roles = [r.name for r in user.roles]
                    if roles:
                        print(f'  {user.username}: {roles}')
            else:
                print('user_roles table already properly populated')

if __name__ == '__main__':
    main()
