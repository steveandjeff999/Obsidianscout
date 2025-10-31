#!/usr/bin/env python3
"""
Debug Superadmin Login Issues
Investigates why superadmin and other users are sometimes rejected during login
"""
import os
import sys
from datetime import datetime, timezone, timedelta

def debug_superadmin_login():
    """Debug superadmin login specifically to identify the issue"""
    try:
        from app import create_app
        from app.models import User, LoginAttempt, db
        from app.utils.brute_force_protection import is_login_blocked, record_login_attempt, get_login_status
        from werkzeug.security import check_password_hash
        
        app = create_app()
        
        with app.app_context():
            print(" DEBUGGING SUPERADMIN LOGIN ISSUES")
            print("=" * 60)
            
            # Find the superadmin user
            superadmin = User.query.filter_by(username='superadmin').first()
            
            if not superadmin:
                print(" Superadmin user not found!")
                return
            
            print(f" Found superadmin user:")
            print(f"   Username: {superadmin.username}")
            print(f"   Team Number: {superadmin.scouting_team_number}")
            print(f"   Is Active: {superadmin.is_active}")
            print(f"   Must Change Password: {superadmin.must_change_password}")
            print(f"   Roles: {[role.name for role in superadmin.roles]}")
            print(f"   Last Login: {superadmin.last_login}")
            
            # Test password verification
            print(f"\n TESTING PASSWORD VERIFICATION")
            print("-" * 40)
            
            test_passwords = ['password', 'Password', 'PASSWORD', 'password123']
            for pwd in test_passwords:
                is_valid = superadmin.check_password(pwd)
                print(f"   Password '{pwd}': {' VALID' if is_valid else ' INVALID'}")
            
            # Check brute force protection status
            print(f"\n️ CHECKING BRUTE FORCE PROTECTION")
            print("-" * 40)
            
            # Check current login status
            status = get_login_status('superadmin')
            print(f"   Is Blocked: {status['is_blocked']}")
            print(f"   Remaining Attempts: {status['remaining_attempts']}")
            print(f"   Lockout Minutes Remaining: {status['lockout_minutes_remaining']}")
            
            # Check recent login attempts for superadmin
            recent_attempts = LoginAttempt.query.filter(
                LoginAttempt.username == 'superadmin',
                LoginAttempt.attempt_time >= datetime.now(timezone.utc) - timedelta(hours=24)
            ).order_by(LoginAttempt.attempt_time.desc()).limit(10).all()
            
            print(f"\n RECENT LOGIN ATTEMPTS (Last 24 hours)")
            print("-" * 40)
            if recent_attempts:
                for attempt in recent_attempts:
                    status_icon = "" if attempt.success else ""
                    print(f"   {status_icon} {attempt.attempt_time} | IP: {attempt.ip_address} | Team: {attempt.team_number}")
            else:
                print("   No recent login attempts found")
            
            # Check for any IP blocks that might affect superadmin
            print(f"\n CHECKING IP-BASED BLOCKS")
            print("-" * 40)
            
            # Get all IPs that have failed attempts in last 15 minutes
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=15)
            blocked_ips = db.session.query(LoginAttempt.ip_address).filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff_time
            ).group_by(LoginAttempt.ip_address).having(
                db.func.count(LoginAttempt.id) >= 10
            ).all()
            
            if blocked_ips:
                print("   Currently blocked IPs:")
                for ip in blocked_ips:
                    print(f"     - {ip[0]}")
            else:
                print("   No IPs currently blocked")
            
            # Test the login flow step by step
            print(f"\n TESTING LOGIN FLOW STEP BY STEP")
            print("-" * 40)
            
            # Simulate the exact login process from auth.py
            username = 'superadmin'
            password = 'password'
            team_number = 0
            
            print(f"1. Checking if login is blocked...")
            if is_login_blocked(username):
                print("    Login is currently blocked!")
                return
            else:
                print("    Login not blocked")
            
            print(f"2. Looking up user...")
            user = User.query.filter_by(username=username, scouting_team_number=team_number).first()
            if user:
                print(f"    User found: {user.username}")
            else:
                print("    User not found!")
                return
            
            print(f"3. Checking password...")
            if user.check_password(password):
                print("    Password correct")
            else:
                print("    Password incorrect!")
                return
            
            print(f"4. Checking if account is active...")
            if user.is_active:
                print("    Account is active")
            else:
                print("    Account is deactivated!")
                return
            
            print(f"5. Final block check...")
            if is_login_blocked(username):
                print("    Final block check failed!")
                return
            else:
                print("    Final block check passed")
            
            print(f"\n ALL LOGIN CHECKS PASSED - Login should work!")
            
            # Check for database corruption or issues
            print(f"\n CHECKING DATABASE INTEGRITY")
            print("-" * 40)
            
            try:
                # Test basic database operations
                user_count = User.query.count()
                print(f"   Total users in database: {user_count}")
                
                # Test if we can update the user
                superadmin.last_login = datetime.now(timezone.utc)
                db.session.commit()
                print("    Database write test successful")
                
            except Exception as e:
                print(f"    Database integrity issue: {e}")
            
            # Check for concurrent access issues
            print(f"\n️ POTENTIAL ISSUES TO INVESTIGATE")
            print("-" * 40)
            
            issues = []
            
            # Check if password was recently changed
            if superadmin.must_change_password:
                issues.append("User must change password - might cause redirect issues")
            
            # Check for very recent failed attempts
            very_recent = LoginAttempt.query.filter(
                LoginAttempt.username == 'superadmin',
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= datetime.now(timezone.utc) - timedelta(minutes=1)
            ).count()
            
            if very_recent > 0:
                issues.append(f"{very_recent} failed attempts in last minute - might indicate timing issue")
            
            # Check for session/cookie issues
            if not superadmin.last_login:
                issues.append("User has never successfully logged in")
            
            if issues:
                for issue in issues:
                    print(f"   ️ {issue}")
            else:
                print("   No obvious issues detected")
            
    except Exception as e:
        print(f" Error during debug: {e}")
        import traceback
        traceback.print_exc()

def test_login_flow():
    """Test the actual login endpoint to see what happens"""
    try:
        from app import create_app
        from flask import url_for
        
        app = create_app()
        
        with app.app_context():
            with app.test_client() as client:
                print(f"\n TESTING ACTUAL LOGIN ENDPOINT")
                print("-" * 40)
                
                # Test GET request to login page
                response = client.get('/auth/login')
                print(f"GET /auth/login: {response.status_code}")
                
                # Test POST request with superadmin credentials
                response = client.post('/auth/login', data={
                    'username': 'superadmin',
                    'password': 'password',
                    'team_number': '0',
                    'remember_me': False
                }, follow_redirects=False)
                
                print(f"POST /auth/login: {response.status_code}")
                print(f"Location header: {response.headers.get('Location', 'None')}")
                
                # Check for flash messages in the response
                if hasattr(response, 'data'):
                    response_text = response.data.decode('utf-8')
                    if 'Invalid' in response_text:
                        print("    'Invalid' found in response - credentials rejected")
                    elif 'deactivated' in response_text:
                        print("    'deactivated' found in response - account disabled")
                    elif 'change your password' in response_text:
                        print("   ️ 'change your password' found - password change required")
                    elif 'Welcome back' in response_text:
                        print("    'Welcome back' found - login successful")
                    else:
                        print("    No obvious success/failure messages found")
                
    except Exception as e:
        print(f" Error testing login endpoint: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    debug_superadmin_login()
    test_login_flow()
