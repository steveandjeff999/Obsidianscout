#!/usr/bin/env python3
"""
Database initialization script for authentication system.
Creates roles and the initial admin user.
"""

from app import create_app, db
from app.models import User, Role

def init_auth_system():
    """Initialize the authentication system with roles and admin user"""
    print("Initializing authentication system...")
    
    # Create roles
    roles_data = [
        {
            'name': 'admin',
            'description': 'Full system access including user management and configuration'
        },
        {
            'name': 'analytics', 
            'description': 'Access to data analysis, visualizations, and reporting features'
        },
        {
            'name': 'scout',
            'description': 'Limited access for scouting data entry only'
        }
    ]
    
    created_roles = {}
    for role_data in roles_data:
        role = Role.query.filter_by(name=role_data['name']).first()
        if not role:
            role = Role(name=role_data['name'], description=role_data['description'])
            db.session.add(role)
            print(f"Created role: {role_data['name']}")
        else:
            print(f"Role already exists: {role_data['name']}")
        
        created_roles[role_data['name']] = role
    
    # Commit roles first
    db.session.commit()
    
    # Create admin user: admin with password password
    admin_username = 'admin'
    admin_password = 'password'
    
    admin_user = User.query.filter_by(username=admin_username).first()
    if not admin_user:
        admin_user = User(username=admin_username)
        admin_user.set_password(admin_password)
        
        # Add admin role
        admin_role = Role.query.filter_by(name='admin').first()
        if admin_role:
            admin_user.roles.append(admin_role)
        
        db.session.add(admin_user)
        db.session.commit()
        
        print(f"Created admin user: {admin_username}")
        print(f"Admin password: {admin_password}")
    else:
        print(f"Admin user already exists: {admin_username}")
    
    print("Authentication system initialization complete!")
    print("\nRoles created:")
    for role in Role.query.all():
        print(f"  - {role.name}: {role.description}")
    
    print(f"\nAdmin login:")
    print(f"  Username: {admin_username}")
    print(f"  Password: {admin_password}")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        # Create all database tables
        db.create_all()
        
        # Initialize authentication system
        init_auth_system()
