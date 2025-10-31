"""
Test script to verify brute force protection is working in the actual login system
"""
import os
import sys
import requests
from time import sleep

# Add the app to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_actual_login_protection():
    """Test the actual login endpoint for brute force protection"""
    try:
        from app import create_app
        from app.models import LoginAttempt, db
        
        app = create_app()
        
        with app.app_context():
            print(" TESTING ACTUAL LOGIN BRUTE FORCE PROTECTION")
            print("=" * 60)
            
            # Clean up any existing test data
            test_ip = "127.0.0.1"
            LoginAttempt.query.filter_by(ip_address=test_ip).delete()
            db.session.commit()
            
            print(f"Testing with IP: {test_ip}")
            print("Starting failed login attempts...")
            
            # Test the actual protection logic used in auth.py
            from app.utils.brute_force_protection import is_login_blocked, record_login_attempt, get_login_status
            
            test_username = "nonexistent_user"
            test_team = 9999
            
            for attempt in range(1, 15):
                print(f"\n--- Attempt {attempt} ---")
                
                # Check if blocked BEFORE recording attempt
                blocked_before = is_login_blocked(test_username)
                print(f"Blocked before attempt: {blocked_before}")
                
                if blocked_before:
                    status = get_login_status(test_username)
                    print(f"Lockout minutes remaining: {status['lockout_minutes_remaining']}")
                    print(f"Max attempts: {status['max_attempts']}")
                    break
                
                # Record a failed attempt (simulating the auth.py logic)
                record_login_attempt(username=test_username, team_number=test_team, success=False)
                
                # Check status after recording
                status = get_login_status(test_username)
                failed_count = LoginAttempt.get_failed_attempts_count(test_ip, test_username, since_minutes=15)
                
                print(f"Failed attempts count: {failed_count}")
                print(f"Remaining attempts: {status['remaining_attempts']}")
                print(f"Is blocked after: {status['is_blocked']}")
                
                if status['is_blocked']:
                    print(f" BLOCKED after {attempt} attempts!")
                    break
                elif status['remaining_attempts'] <= 3:
                    print(f"️  Warning: Only {status['remaining_attempts']} attempts remaining")
            
            # Test what happens with successful login
            print(f"\n--- Testing Successful Login Clears Attempts ---")
            record_login_attempt(username=test_username, team_number=test_team, success=True)
            
            status_after_success = get_login_status(test_username)
            print(f"Blocked after successful login: {status_after_success['is_blocked']}")
            print(f"Remaining attempts after success: {status_after_success['remaining_attempts']}")
            
            # Clean up
            LoginAttempt.query.filter_by(ip_address=test_ip).delete()
            db.session.commit()
            print("\n Test data cleaned up")
            
    except Exception as e:
        print(f" Error during testing: {e}")
        import traceback
        traceback.print_exc()

def check_current_protection_settings():
    """Check the current protection settings"""
    try:
        from app import create_app
        from app.utils.brute_force_protection import brute_force_protection
        
        app = create_app()
        
        with app.app_context():
            print("\n CURRENT PROTECTION SETTINGS")
            print("=" * 40)
            print(f"Max attempts: {brute_force_protection.max_attempts}")
            print(f"Lockout minutes: {brute_force_protection.lockout_minutes}")
            print(f"Cleanup days: {brute_force_protection.cleanup_days}")
            
            # Check if there are any current login attempts in the database
            from app.models import LoginAttempt
            total_attempts = LoginAttempt.query.count()
            failed_attempts = LoginAttempt.query.filter_by(success=False).count()
            recent_attempts = LoginAttempt.query.filter(
                LoginAttempt.attempt_time >= LoginAttempt.query.with_entities(
                    LoginAttempt.attempt_time
                ).order_by(LoginAttempt.attempt_time.desc()).first()[0] - 
                __import__('datetime').timedelta(minutes=15)
            ).count() if total_attempts > 0 else 0
            
            print(f"\nDatabase status:")
            print(f"Total login attempts: {total_attempts}")
            print(f"Failed attempts: {failed_attempts}")
            print(f"Recent attempts (15min): {recent_attempts}")
            
    except Exception as e:
        print(f" Error checking settings: {e}")
        import traceback
        traceback.print_exc()

def debug_auth_route():
    """Debug the auth route to see if protection is actually integrated"""
    try:
        from app import create_app
        
        app = create_app()
        
        with app.app_context():
            print("\n DEBUGGING AUTH ROUTE INTEGRATION")
            print("=" * 40)
            
            # Check if the auth route file has our protection code
            auth_file = os.path.join(os.path.dirname(__file__), 'app', 'routes', 'auth.py')
            
            if os.path.exists(auth_file):
                with open(auth_file, 'r') as f:
                    content = f.read()
                
                print("Checking for brute force protection integration:")
                
                checks = {
                    'Import statement': 'from app.utils.brute_force_protection import' in content,
                    'is_login_blocked check': 'is_login_blocked(' in content,
                    'record_login_attempt call': 'record_login_attempt(' in content,
                    'get_login_status call': 'get_login_status(' in content,
                    'Lockout message': 'Too many failed login attempts' in content
                }
                
                for check, found in checks.items():
                    status = "" if found else ""
                    print(f"  {status} {check}: {'Found' if found else 'Missing'}")
                
                if not all(checks.values()):
                    print("\n Protection code is missing from auth route!")
                    return False
                else:
                    print("\n Protection code is properly integrated")
                    return True
            else:
                print(" Auth route file not found")
                return False
                
    except Exception as e:
        print(f" Error debugging auth route: {e}")
        return False

if __name__ == '__main__':
    print(" Debugging brute force protection...")
    
    # Check settings first
    check_current_protection_settings()
    
    # Check if code is integrated
    if debug_auth_route():
        # Test the actual protection
        test_actual_login_protection()
    else:
        print("\n ISSUE: Protection code not properly integrated into auth route")
        print("   This is likely why the lockout isn't working")
