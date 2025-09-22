from app import create_app, db
from app.models import User, Role

app = create_app()

with app.app_context():
    superadmin = User.query.filter_by(username='superadmin').first()
    print(f'Superadmin exists: {superadmin is not None}')
    if superadmin:
        print(f'Team number: {superadmin.scouting_team_number}')
        print(f'Roles: {[role.name for role in superadmin.roles]}')
        print(f'Is active: {superadmin.is_active}')
    
    # Also check the superadmin role exists
    superadmin_role = Role.query.filter_by(name='superadmin').first()
    print(f'Superadmin role exists: {superadmin_role is not None}')
    if superadmin_role:
        print(f'Role description: {superadmin_role.description}')
