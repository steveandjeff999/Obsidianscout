"""
Script to check and fix scouting team number issues for users
"""
import os
import sys

# Add the app to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_user_scouting_teams():
    """Check all users and their scouting team numbers"""
    try:
        from app import create_app
        from app.models import User, Role
        
        app = create_app()
        
        with app.app_context():
            print("🔍 Checking user scouting team assignments...")
            
            # Get all users
            users = User.query.all()
            print(f"📊 Found {len(users)} users:")
            
            users_without_team = []
            superadmin_users = []
            
            for user in users:
                team_num = getattr(user, 'scouting_team_number', None)
                roles = user.get_role_names()
                
                print(f"  - {user.username}: Team {team_num}, Roles: {roles}")
                
                if user.has_role('superadmin'):
                    superadmin_users.append(user)
                
                if team_num is None:
                    users_without_team.append(user)
            
            if users_without_team:
                print(f"\n❌ Found {len(users_without_team)} users without scouting team numbers:")
                for user in users_without_team:
                    print(f"  - {user.username}")
                
                # For superadmin users, team number 0 is acceptable
                superadmin_without_team = [u for u in users_without_team if u.has_role('superadmin')]
                if superadmin_without_team:
                    print(f"\n💡 Superadmin users can have team number 0, but they should have a team number:")
                    for user in superadmin_without_team:
                        print(f"  - {user.username} (should be team 0)")
                
                return users_without_team
            else:
                print("\n✅ All users have scouting team numbers assigned")
                return []
                
    except Exception as e:
        print(f"❌ Error checking users: {e}")
        import traceback
        traceback.print_exc()
        return []

def fix_user_scouting_teams():
    """Fix missing scouting team numbers"""
    try:
        from app import create_app
        from app.models import User, Role, db
        
        app = create_app()
        
        with app.app_context():
            print("🔧 Fixing user scouting team assignments...")
            
            # Get users without team numbers
            users_without_team = User.query.filter(User.scouting_team_number.is_(None)).all()
            
            if not users_without_team:
                print("✅ No users need fixing")
                return
            
            for user in users_without_team:
                if user.has_role('superadmin'):
                    # Superadmin should have team number 0
                    user.scouting_team_number = 0
                    print(f"✅ Set {user.username} (superadmin) to team 0")
                else:
                    # Regular users need a proper team number
                    # We'll ask the user what team number to assign
                    print(f"❓ User {user.username} needs a team number. What team should they be assigned to?")
                    print("   Common options: 5454, 5568, etc.")
                    
                    # For now, let's assign a default team number (you can change this)
                    default_team = 5454  # Change this to your team number
                    user.scouting_team_number = default_team
                    print(f"✅ Set {user.username} to team {default_team}")
            
            # Commit changes
            db.session.commit()
            print("✅ All user team assignments fixed!")
            
    except Exception as e:
        print(f"❌ Error fixing users: {e}")
        import traceback
        traceback.print_exc()

def show_fix_options():
    """Show available fix options"""
    print("\n🔧 FIX OPTIONS:")
    print("=" * 50)
    
    print("\n1. 🏢 For Superadmin Users:")
    print("   - Should have team number 0")
    print("   - Can access all teams' data")
    print("   - Used for administration")
    
    print("\n2. 👥 For Regular Users:")
    print("   - Should have their actual team number (e.g., 5454, 5568)")
    print("   - Can only access their team's data")
    print("   - Used for normal scouting operations")
    
    print("\n3. 🔄 To Fix Manually:")
    print("   - Use the admin interface to edit users")
    print("   - Or run this script to auto-fix")
    
    print("\n4. 🗑️ For Wipe Database:")
    print("   - Only works when user has a valid team number")
    print("   - Wipes data for that specific team only")
    print("   - Superadmin (team 0) would wipe admin data")

if __name__ == '__main__':
    print("🧪 Checking user scouting team assignments...")
    
    users_needing_fix = check_user_scouting_teams()
    
    if users_needing_fix:
        show_fix_options()
        
        print(f"\n❌ DIAGNOSIS: {len(users_needing_fix)} users don't have scouting team numbers")
        print("   This is why the 'wipe database' function fails")
        
        response = input("\n🔧 Do you want to auto-fix these users? (y/n): ")
        if response.lower() == 'y':
            fix_user_scouting_teams()
            print("\n✅ Users fixed! Try the wipe database function again.")
        else:
            print("\n💡 Please assign team numbers manually through the admin interface")
    else:
        print("\n✅ All users have team numbers - wipe database should work correctly")
