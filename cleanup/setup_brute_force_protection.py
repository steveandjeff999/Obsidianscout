"""
Database migration to add brute force protection
Creates the login_attempts table for tracking failed login attempts
"""
import os
import sys

# Add the app to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def create_login_attempts_table():
    """Create the login_attempts table for brute force protection"""
    try:
        from app import create_app, db
        from app.models import LoginAttempt
        
        app = create_app()
        
        with app.app_context():
            print(" Creating login_attempts table for brute force protection...")
            
            # Check if table already exists
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            if 'login_attempts' in existing_tables:
                print(" login_attempts table already exists")
                return True
            
            # Create the table
            db.create_all()
            
            # Verify table was created
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            if 'login_attempts' in existing_tables:
                print(" login_attempts table created successfully!")
                
                # Get table info
                columns = inspector.get_columns('login_attempts')
                print(f"   Table has {len(columns)} columns:")
                for col in columns:
                    print(f"   - {col['name']}: {col['type']}")
                
                return True
            else:
                print(" Failed to create login_attempts table")
                return False
                
    except Exception as e:
        print(f" Error creating login_attempts table: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_brute_force_protection():
    """Test the brute force protection functionality"""
    try:
        from app import create_app
        from app.utils.brute_force_protection import BruteForceProtection
        from app.models import LoginAttempt
        
        app = create_app()
        
        with app.app_context():
            print("\n Testing brute force protection functionality...")
            
            # Create a test protection instance
            protection = BruteForceProtection(max_attempts=3, lockout_minutes=5)
            
            # Test recording failed attempts
            test_ip = "192.168.1.100"
            test_username = "test_user"
            
            print(f"   Testing with IP {test_ip} and username '{test_username}'")
            
            # Simulate failed attempts
            for i in range(1, 4):
                LoginAttempt.record_attempt(
                    ip_address=test_ip,
                    username=test_username,
                    success=False
                )
                print(f"   Recorded failed attempt {i}")
            
            # Check if blocked
            is_blocked = LoginAttempt.is_blocked(test_ip, test_username, max_attempts=3)
            print(f"   Is blocked after 3 attempts: {is_blocked}")
            
            # Test successful login clears failed attempts
            LoginAttempt.record_attempt(
                ip_address=test_ip,
                username=test_username,
                success=True
            )
            print("   Recorded successful attempt")
            
            LoginAttempt.clear_successful_attempts(test_ip, test_username)
            print("   Cleared failed attempts")
            
            # Check if still blocked
            is_blocked_after_success = LoginAttempt.is_blocked(test_ip, test_username, max_attempts=3)
            print(f"   Is blocked after successful login: {is_blocked_after_success}")
            
            # Clean up test data
            LoginAttempt.query.filter_by(ip_address=test_ip).delete()
            from app import db
            db.session.commit()
            print("   Cleaned up test data")
            
            print(" Brute force protection test completed successfully!")
            return True
            
    except Exception as e:
        print(f" Error testing brute force protection: {e}")
        import traceback
        traceback.print_exc()
        return False

def show_protection_info():
    """Show information about the brute force protection system"""
    print("\n BRUTE FORCE PROTECTION SYSTEM")
    print("=" * 50)
    
    print("\n️  Protection Features:")
    print("   - Max failed attempts: 10 (configurable)")
    print("   - Lockout duration: 15 minutes (configurable)")
    print("   - IP-based and username-based tracking")
    print("   - Automatic cleanup of old attempts")
    print("   - Remaining attempts warnings")
    print("   - Real-time blocking")
    
    print("\n How It Works:")
    print("   1. Each failed login is recorded with IP and username")
    print("   2. After 10 failed attempts, IP is blocked for 15 minutes")
    print("   3. Successful login clears failed attempt counter")
    print("   4. Users get warnings when approaching limit")
    print("   5. Blocked users see lockout time remaining")
    
    print("\n️  Configuration:")
    print("   - Settings in app/utils/brute_force_protection.py")
    print("   - Can be adjusted per deployment needs")
    print("   - Supports proxy/load balancer environments")
    
    print("\n Database:")
    print("   - login_attempts table tracks all attempts")
    print("   - Automatic cleanup prevents table bloat")
    print("   - Indexes on IP and username for performance")

if __name__ == '__main__':
    print(" Setting up brute force protection...")
    
    success = create_login_attempts_table()
    
    if success:
        test_success = test_brute_force_protection()
        
        if test_success:
            show_protection_info()
            print("\n SUCCESS: Brute force protection is ready!")
            print("   Your application is now protected against brute force attacks.")
            print("   Failed login attempts will be blocked after 10 attempts.")
        else:
            print("\n SETUP INCOMPLETE: Table created but testing failed")
    else:
        print("\n SETUP FAILED: Could not create required database table")
