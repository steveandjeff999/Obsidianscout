#!/usr/bin/env python3
"""
Login Flow Test
Simulate the exact login flow from auth.py to identify the failure point
"""
import os
import sys
from datetime import datetime

def test_login_flow():
    """Test the exact login flow step by step"""
    try:
        from app import create_app
        from app.models import User, LoginAttempt, Role, db
        from app.utils.brute_force_protection import is_login_blocked, record_login_attempt, get_login_status
        from flask import request
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        
        app = create_app()
        
        with app.app_context():
            print("🔍 LOGIN FLOW TEST")
            print("=" * 60)
            
            # Test credentials
            username = 'superadmin'
            password = 'JSHkimber1911'
            team_number = 0
            
            print(f"Testing login with:")
            print(f"  Username: {username}")
            print(f"  Password: {password}")
            print(f"  Team Number: {team_number}")
            print()
            
            # Step 1: Check if blocked
            print("STEP 1: Checking if user is blocked...")
            blocked = is_login_blocked(username)
            print(f"  Result: {'BLOCKED' if blocked else 'NOT BLOCKED'}")
            if blocked:
                status = get_login_status(username)
                print(f"  Block details: {status}")
                print("❌ LOGIN WOULD FAIL HERE - User is blocked")
                return
            print("✅ Step 1 passed")
            print()
            
            # Step 2: Team number validation
            print("STEP 2: Team number validation...")
            if not team_number and team_number != 0:
                print("❌ LOGIN WOULD FAIL HERE - Team number is required")
                return
            print("✅ Step 2 passed - Team number provided")
            print()
            
            # Step 3: Team number conversion
            print("STEP 3: Team number conversion...")
            try:
                team_number_int = int(team_number)
                print(f"  Converted '{team_number}' to {team_number_int} (type: {type(team_number_int)})")
                print("✅ Step 3 passed")
            except ValueError:
                print("❌ LOGIN WOULD FAIL HERE - Team number is not a valid number")
                return
            print()
            
            # Step 4: User lookup
            print("STEP 4: User database lookup...")
            print(f"  Query: User.query.filter_by(username='{username}', scouting_team_number={team_number_int})")
            
            user = User.query.filter_by(username=username, scouting_team_number=team_number_int).first()
            if user is None:
                print("❌ LOGIN WOULD FAIL HERE - User not found with exact query")
                
                # Try alternative queries to debug
                print("  Debugging alternative queries:")
                alt_user = User.query.filter_by(username=username).first()
                if alt_user:
                    print(f"    Found user '{username}' with team {alt_user.scouting_team_number} (type: {type(alt_user.scouting_team_number)})")
                    print(f"    Comparison: {team_number_int} == {alt_user.scouting_team_number} = {team_number_int == alt_user.scouting_team_number}")
                else:
                    print(f"    No user found with username '{username}' at all")
                return
            
            print(f"✅ Step 4 passed - Found user: {user.username} (Team: {user.scouting_team_number})")
            print()
            
            # Step 5: Password check
            print("STEP 5: Password verification...")
            if not user.check_password(password):
                print("❌ LOGIN WOULD FAIL HERE - Password check failed")
                print("  Debugging password:")
                
                # Test the password hash directly
                from werkzeug.security import check_password_hash
                direct_check = check_password_hash(user.password_hash, password)
                print(f"    Direct hash check: {direct_check}")
                print(f"    Hash preview: {user.password_hash[:50]}...")
                
                return
            
            print("✅ Step 5 passed - Password verification successful")
            print()
            
            # Step 6: Active account check
            print("STEP 6: Account active check...")
            if not user.is_active:
                print("❌ LOGIN WOULD FAIL HERE - Account is deactivated")
                return
            
            print("✅ Step 6 passed - Account is active")
            print()
            
            # Step 7: Final block check (double-check)
            print("STEP 7: Final brute force block check...")
            blocked_final = is_login_blocked(username)
            if blocked_final:
                print("❌ LOGIN WOULD FAIL HERE - User became blocked during login process")
                return
            
            print("✅ Step 7 passed - Still not blocked")
            print()
            
            # Step 8: Must change password check
            print("STEP 8: Must change password check...")
            if user.must_change_password:
                print("⚠️  User must change password - would redirect")
            else:
                print("✅ No password change required")
            print()
            
            # Step 9: Role check
            print("STEP 9: Role check...")
            if not user.roles:
                print("⚠️  User has no roles - would redirect to role selection")
            else:
                role_names = [role.name for role in user.roles]
                print(f"✅ User has roles: {role_names}")
            print()
            
            print("🎉 LOGIN FLOW COMPLETE - ALL CHECKS PASSED!")
            print("   Login should be successful")
            
            # Test the actual record_login_attempt function
            print("\nTesting record_login_attempt function...")
            try:
                record_login_attempt(username=username, team_number=team_number_int, success=True)
                print("✅ Successfully recorded login attempt")
            except Exception as e:
                print(f"❌ Failed to record login attempt: {e}")
            
            # Final status check
            print("\nFinal login status check...")
            status = get_login_status(username)
            print(f"Login status: {status}")
            
    except Exception as e:
        print(f"❌ Error during login flow test: {e}")
        import traceback
        traceback.print_exc()

def test_actual_http_login():
    """Test login using actual HTTP request simulation"""
    try:
        from app import create_app
        
        app = create_app()
        
        with app.test_client() as client:
            print("\n🌐 HTTP LOGIN TEST")
            print("=" * 60)
            
            # First get the login page to establish session
            print("Getting login page...")
            response = client.get('/auth/login')
            print(f"  Status: {response.status_code}")
            
            # Submit login form
            print("Submitting login form...")
            login_data = {
                'username': 'superadmin',
                'password': 'JSHkimber1911',
                'team_number': '0'
            }
            
            response = client.post('/auth/login', data=login_data, follow_redirects=False)
            print(f"  Status: {response.status_code}")
            print(f"  Location: {response.headers.get('Location', 'None')}")
            
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                if 'lockout' in location:
                    print("❌ Redirected to lockout page - user is blocked")
                elif 'change_password' in location:
                    print("⚠️  Redirected to change password page")
                elif 'select_role' in location:
                    print("⚠️  Redirected to role selection page")
                elif 'main' in location or 'scouting' in location:
                    print("✅ Redirected to main page - LOGIN SUCCESSFUL!")
                else:
                    print(f"❓ Redirected to unexpected location: {location}")
            else:
                print("❌ No redirect - login likely failed")
                
                # Get response data to see flash messages
                response_text = response.get_data(as_text=True)
                if 'Invalid username' in response_text:
                    print("   Error message found: Invalid username/password/team")
                elif 'deactivated' in response_text:
                    print("   Error message found: Account deactivated")
                else:
                    print("   No specific error message found in response")
    
    except Exception as e:
        print(f"❌ Error during HTTP login test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_login_flow()
    test_actual_http_login()
