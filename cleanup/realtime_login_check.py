#!/usr/bin/env python3
"""
Real-time Login Status Check
Check current login attempts and clear any that might be blocking
"""
import os
import sys
from datetime import datetime, timezone, timedelta

def check_login_status():
    """Check current login status and clear blocks"""
    try:
        from app import create_app
        from app.models import User, LoginAttempt, Role, db
        
        app = create_app()
        
        with app.app_context():
            print(" REAL-TIME LOGIN STATUS CHECK")
            print("=" * 60)
            
            username = 'superadmin'
            
            # 1. Check user account
            print("1. USER ACCOUNT STATUS")
            print("-" * 30)
            user = User.query.filter_by(username=username).first()
            if user:
                print(f" Username: {user.username}")
                print(f" Team: {user.scouting_team_number}")
                print(f" Active: {user.is_active}")
                print(f" Must change password: {user.must_change_password}")
                print(f" Last login: {user.last_login}")
                print(f" Password works: {user.check_password('JSH1911')}")
            else:
                print(" User not found!")
                return
            
            # 2. Check all login attempts
            print(f"\n2. ALL LOGIN ATTEMPTS FOR '{username}'")
            print("-" * 30)
            
            all_attempts = LoginAttempt.query.filter_by(username=username).order_by(LoginAttempt.attempt_time.desc()).limit(20).all()
            
            if not all_attempts:
                print(" No login attempts found")
            else:
                print(f"Found {len(all_attempts)} recent attempts:")
                for attempt in all_attempts:
                    status = " SUCCESS" if attempt.success else " FAILED"
                    print(f"  {attempt.attempt_time}: {status} from {attempt.ip_address} (Team: {attempt.team_number})")
            
            # 3. Check recent failed attempts that could block login
            print(f"\n3. RECENT FAILED ATTEMPTS (last 15 minutes)")
            print("-" * 30)
            
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
            recent_failed = LoginAttempt.query.filter(
                LoginAttempt.username == username,
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff
            ).all()
            
            if not recent_failed:
                print(" No recent failed attempts")
            else:
                print(f" {len(recent_failed)} recent failed attempts:")
                for attempt in recent_failed:
                    print(f"  {attempt.attempt_time}: from {attempt.ip_address}")
                
                if len(recent_failed) >= 10:
                    print(" USER IS CURRENTLY BLOCKED!")
            
            # 4. Clear all failed attempts to unblock
            print(f"\n4. CLEARING ALL FAILED ATTEMPTS")
            print("-" * 30)
            
            failed_count = LoginAttempt.query.filter(
                LoginAttempt.username == username,
                LoginAttempt.success == False
            ).delete()
            
            db.session.commit()
            
            print(f" Cleared {failed_count} failed login attempts")
            
            # 5. Final status
            print(f"\n5. CURRENT STATUS AFTER CLEANUP")
            print("-" * 30)
            
            remaining_attempts = LoginAttempt.query.filter_by(username=username).all()
            successful_count = sum(1 for attempt in remaining_attempts if attempt.success)
            failed_count_remaining = sum(1 for attempt in remaining_attempts if not attempt.success)
            
            print(f" Successful attempts remaining: {successful_count}")
            print(f" Failed attempts remaining: {failed_count_remaining}")
            
            if failed_count_remaining == 0:
                print(" USER IS NOW UNBLOCKED - LOGIN SHOULD WORK!")
            else:
                print("️  Some failed attempts still remain")
            
            # 6. Test if we can do a simulated login attempt record
            print(f"\n6. TEST LOGIN ATTEMPT RECORDING")
            print("-" * 30)
            
            try:
                # Record a test successful attempt
                test_attempt = LoginAttempt(
                    username=username,
                    team_number=0,
                    ip_address='127.0.0.1',
                    success=True,
                    attempt_time=datetime.now(timezone.utc)
                )
                
                db.session.add(test_attempt)
                db.session.commit()
                print(" Successfully recorded test login attempt")
                
                # Immediately delete it to keep things clean
                db.session.delete(test_attempt)
                db.session.commit()
                print(" Cleaned up test attempt")
                
            except Exception as e:
                print(f" Error recording test attempt: {e}")
    
    except Exception as e:
        print(f" Error during status check: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    check_login_status()
