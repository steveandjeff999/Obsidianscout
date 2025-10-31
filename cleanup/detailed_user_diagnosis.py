"""
Detailed diagnostic script for user team number issues
"""
import os
import sys

# Add the app to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def detailed_user_diagnosis():
    """Detailed analysis of user team number issues"""
    try:
        from app import create_app
        from app.models import User, db
        
        app = create_app()
        
        with app.app_context():
            print(" DETAILED USER ANALYSIS")
            print("=" * 50)
            
            # Get all users
            users = User.query.all()
            
            for user in users:
                print(f"\n User: {user.username}")
                print(f"   ID: {user.id}")
                print(f"   Raw team number: {repr(user.scouting_team_number)}")
                print(f"   Type: {type(user.scouting_team_number)}")
                print(f"   Is None: {user.scouting_team_number is None}")
                print(f"   Is Empty String: {user.scouting_team_number == ''}")
                print(f"   Is Zero: {user.scouting_team_number == 0}")
                print(f"   Boolean value: {bool(user.scouting_team_number)}")
                print(f"   Roles: {user.get_role_names()}")
                
                # Check if this would cause the wipe database error
                if not user.scouting_team_number:
                    print(f"    THIS USER WOULD CAUSE WIPE DATABASE ERROR")
                else:
                    print(f"    This user's team number is valid")
            
            # Now let's simulate what happens in the wipe database function
            print(f"\n SIMULATING WIPE DATABASE FUNCTION")
            print("=" * 50)
            
            for user in users:
                print(f"\n Testing user: {user.username}")
                
                # This is the exact code from the wipe database function
                scouting_team_number = user.scouting_team_number
                
                if not scouting_team_number:
                    print(f"    ERROR: No scouting team number found for {user.username}")
                    print(f"   Raw value: {repr(scouting_team_number)}")
                    print(f"   This user would get the error message")
                else:
                    print(f"    User {user.username} has valid team number: {scouting_team_number}")
                
    except Exception as e:
        print(f" Error: {e}")
        import traceback
        traceback.print_exc()

def fix_problematic_users():
    """Fix users that would cause the wipe database error"""
    try:
        from app import create_app
        from app.models import User, db
        
        app = create_app()
        
        with app.app_context():
            print("\n FIXING PROBLEMATIC USERS")
            print("=" * 50)
            
            users = User.query.all()
            fixed_count = 0
            
            for user in users:
                if not user.scouting_team_number:
                    print(f"\n Fixing user: {user.username}")
                    print(f"   Current value: {repr(user.scouting_team_number)}")
                    
                    # Determine appropriate team number
                    if user.has_role('superadmin') or user.has_role('admin'):
                        new_team_number = 0
                        print(f"   Setting admin/superadmin to team 0")
                    else:
                        new_team_number = 5454  # Default team - change this as needed
                        print(f"   Setting regular user to team {new_team_number}")
                    
                    user.scouting_team_number = new_team_number
                    fixed_count += 1
                    print(f"    Fixed: {user.username} now has team {new_team_number}")
            
            if fixed_count > 0:
                db.session.commit()
                print(f"\n Fixed {fixed_count} users!")
                print("   Wipe database should now work correctly")
            else:
                print("\n No users needed fixing")
                
    except Exception as e:
        print(f" Error fixing users: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    detailed_user_diagnosis()
    
    response = input("\n Do you want to fix any problematic users? (y/n): ")
    if response.lower() == 'y':
        fix_problematic_users()
    else:
        print(" Run this script again with 'y' to fix users when ready")
