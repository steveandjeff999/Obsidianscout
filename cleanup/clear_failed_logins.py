#!/usr/bin/env python3
"""
Clear Failed Login Attempts
Utility to clear failed login attempts for specific users or all users
"""
import sys
import argparse
from datetime import datetime, timedelta

def clear_failed_attempts(username=None, all_users=False):
    """Clear failed login attempts"""
    try:
        from app import create_app
        from app.models import LoginAttempt, db
        
        app = create_app()
        
        with app.app_context():
            if all_users:
                print(" Clearing all failed login attempts...")
                deleted = LoginAttempt.query.filter_by(success=False).delete()
            elif username:
                print(f" Clearing failed login attempts for user: {username}")
                deleted = LoginAttempt.query.filter(
                    LoginAttempt.username == username,
                    LoginAttempt.success == False
                ).delete()
            else:
                print(" Must specify username or --all")
                return
                
            db.session.commit()
            print(f" Cleared {deleted} failed login attempts")
            
    except Exception as e:
        print(f" Error clearing failed attempts: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clear failed login attempts')
    parser.add_argument('username', nargs='?', help='Username to clear attempts for')
    parser.add_argument('--all', action='store_true', help='Clear all failed attempts')
    
    args = parser.parse_args()
    
    if args.all:
        clear_failed_attempts(all_users=True)
    elif args.username:
        clear_failed_attempts(args.username)
    else:
        print("Usage: python clear_failed_logins.py <username> or python clear_failed_logins.py --all")
        print("Examples:")
        print("  python clear_failed_logins.py superadmin")
        print("  python clear_failed_logins.py --all")
