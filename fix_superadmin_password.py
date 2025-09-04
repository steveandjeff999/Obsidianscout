#!/usr/bin/env python3
"""
Fix Superadmin Password Issue
The debug shows that the superadmin password is not 'password' as expected
"""
import os
import sys
from datetime import datetime

def fix_superadmin_password():
    """Fix the superadmin password issue"""
    try:
        from app import create_app
        from app.models import User, Role, db
        
        app = create_app()
        
        with app.app_context():
            print("🔧 FIXING SUPERADMIN PASSWORD ISSUE")
            print("=" * 60)
            
            # Find the superadmin user
            superadmin = User.query.filter_by(username='superadmin').first()
            
            if not superadmin:
                print("❌ Superadmin user not found!")
                return
            
            print(f"Found superadmin user:")
            print(f"   Username: {superadmin.username}")
            print(f"   Team Number: {superadmin.scouting_team_number}")
            print(f"   Is Active: {superadmin.is_active}")
            print(f"   Current password hash: {superadmin.password_hash[:50]}...")
            
            # Test some common passwords that might have been set
            test_passwords = [
                'JSHkimber1911', # Current actual password
                'password',      # Expected default
                'Password',      # Capitalized
                'password123',   # With numbers
                'admin',         # Simple admin
                'superadmin',    # Username as password
                'Password123',   # Common pattern
                '5454',          # Team number based
                'team5454',      # Team based
                'scout',         # App based
                '',              # Empty password (shouldn't work but worth checking)
            ]
            
            print(f"\n🔍 TESTING POSSIBLE PASSWORDS")
            print("-" * 40)
            
            working_password = None
            for pwd in test_passwords:
                if superadmin.check_password(pwd):
                    print(f"   ✅ Password '{pwd}': WORKS!")
                    working_password = pwd
                    break
                else:
                    print(f"   ❌ Password '{pwd}': Invalid")
            
            if not working_password:
                print(f"\n⚠️ NO WORKING PASSWORD FOUND - RESETTING TO 'password'")
                print("-" * 40)
                
                # Reset password to the expected default
                superadmin.set_password('password')
                superadmin.must_change_password = True  # Force password change on next login
                
                try:
                    db.session.commit()
                    print("✅ Password reset to 'password' successfully!")
                    print("✅ User must change password on next login")
                    
                    # Verify the reset worked
                    if superadmin.check_password('password'):
                        print("✅ Password reset verified - 'password' now works!")
                    else:
                        print("❌ Password reset verification failed!")
                        
                except Exception as e:
                    print(f"❌ Error resetting password: {e}")
                    db.session.rollback()
            else:
                print(f"\n✅ FOUND WORKING PASSWORD: '{working_password}'")
                print("No reset needed!")
            
            # Also check and fix any other users that might have similar issues
            print(f"\n🔍 CHECKING OTHER USERS FOR SIMILAR ISSUES")
            print("-" * 40)
            
            all_users = User.query.all()
            problem_users = []
            
            for user in all_users:
                if user.username == 'superadmin':
                    continue  # Already handled
                
                # Test common passwords for each user
                user_passwords = [
                    'password',
                    'Password', 
                    user.username,  # Username as password
                    str(user.scouting_team_number),  # Team number as password
                ]
                
                has_working_password = False
                for pwd in user_passwords:
                    if user.check_password(pwd):
                        has_working_password = True
                        break
                
                if not has_working_password:
                    problem_users.append(user)
            
            if problem_users:
                print(f"⚠️ Found {len(problem_users)} users with unknown passwords:")
                for user in problem_users[:5]:  # Show first 5
                    print(f"   - {user.username} (team {user.scouting_team_number})")
                if len(problem_users) > 5:
                    print(f"   ... and {len(problem_users) - 5} more")
            else:
                print("✅ All other users have recognizable passwords")
            
            # Clear any failed login attempts for superadmin to prevent lockout
            print(f"\n🧹 CLEARING FAILED LOGIN ATTEMPTS")
            print("-" * 40)
            
            try:
                from app.models import LoginAttempt
                failed_attempts = LoginAttempt.query.filter(
                    LoginAttempt.username == 'superadmin',
                    LoginAttempt.success == False
                ).delete()
                
                db.session.commit()
                print(f"✅ Cleared {failed_attempts} failed login attempts for superadmin")
                
            except Exception as e:
                print(f"⚠️ Could not clear login attempts: {e}")
            
    except Exception as e:
        print(f"❌ Error during fix: {e}")
        import traceback
        traceback.print_exc()

def test_fixed_login():
    """Test that the login now works"""
    try:
        from app import create_app
        
        app = create_app()
        
        with app.app_context():
            with app.test_client() as client:
                print(f"\n🧪 TESTING FIXED LOGIN")
                print("-" * 40)
                
                # Test POST request with superadmin credentials
                response = client.post('/auth/login', data={
                    'username': 'superadmin',
                    'password': 'JSHkimber1911',  # Use actual password
                    'team_number': '0',
                    'remember_me': False
                }, follow_redirects=False)
                
                print(f"POST /auth/login: {response.status_code}")
                location = response.headers.get('Location', 'None')
                print(f"Redirect location: {location}")
                
                if response.status_code == 302:
                    if '/auth/login' in location:
                        print("❌ Still redirecting to login - credentials still invalid")
                    elif '/auth/change_password' in location:
                        print("⚠️ Redirecting to change password - this is expected!")
                    elif '/main' in location or location == '/':
                        print("✅ Redirecting to main page - login successful!")
                    else:
                        print(f"🤔 Redirecting to unexpected location: {location}")
                else:
                    print(f"🤔 Unexpected response code: {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error testing login: {e}")

if __name__ == '__main__':
    fix_superadmin_password()
    test_fixed_login()
