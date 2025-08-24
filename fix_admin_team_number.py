"""
Script to fix the specific 'admin' user that has no team number
"""
import os
import sys

# Add the app to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def fix_admin_user():
    """Fix the admin user that has no team number"""
    try:
        from app import create_app
        from app.models import User, db
        
        app = create_app()
        
        with app.app_context():
            print("🔍 Looking for admin user with missing team number...")
            
            # Find the admin user with no team number
            admin_user = User.query.filter_by(username='admin').first()
            
            if admin_user:
                print(f"Found admin user: {admin_user.username}")
                print(f"Current team number: {admin_user.scouting_team_number}")
                print(f"Roles: {admin_user.get_role_names()}")
                
                if admin_user.scouting_team_number is None:
                    print("❌ Admin user has no team number - this is causing the wipe database error")
                    
                    # Since this is an admin user, we should assign them team 0 (like superadmin)
                    # or a specific team number depending on their purpose
                    print("🔧 Setting admin user to team 0 (administrative access)")
                    admin_user.scouting_team_number = 0
                    
                    db.session.commit()
                    print("✅ Fixed! Admin user now has team number 0")
                else:
                    print("✅ Admin user already has a team number")
            else:
                print("❌ No 'admin' user found")
                
            # Also check for any other users with None team numbers
            users_with_none = User.query.filter(User.scouting_team_number.is_(None)).all()
            
            if users_with_none:
                print(f"\n❌ Found {len(users_with_none)} users with None team numbers:")
                for user in users_with_none:
                    print(f"  - {user.username}: {user.get_role_names()}")
                    
                    # Fix them
                    if user.has_role('superadmin') or user.has_role('admin'):
                        user.scouting_team_number = 0
                        print(f"    ✅ Set {user.username} to team 0 (admin)")
                    else:
                        user.scouting_team_number = 5454  # Default team
                        print(f"    ✅ Set {user.username} to team 5454 (default)")
                
                db.session.commit()
                print("✅ All users fixed!")
            else:
                print("✅ No users with None team numbers found")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    fix_admin_user()
