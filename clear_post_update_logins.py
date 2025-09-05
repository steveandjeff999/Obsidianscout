#!/usr/bin/env python3
"""
Post-Update Login Cleanup
Specifically designed to run after server updates to prevent login issues
"""
import os
import sys
from datetime import datetime, timedelta

def clear_post_update_failed_logins():
    """Clear failed login attempts after server update/restart"""
    try:
        # Add the app directory to Python path if needed
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        from app import create_app
        from app.models import LoginAttempt, db
        
        app = create_app()
        
        with app.app_context():
            print("🧹 POST-UPDATE LOGIN CLEANUP")
            print("=" * 50)
            
            # Clear all failed login attempts (aggressive cleanup after updates)
            total_failed = LoginAttempt.query.filter_by(success=False).count()
            
            if total_failed > 0:
                print(f"Found {total_failed} failed login attempts to clear...")
                
                # Delete all failed attempts
                deleted_count = LoginAttempt.query.filter_by(success=False).delete()
                db.session.commit()
                
                print(f"✅ Cleared {deleted_count} failed login attempts")
                print("✅ All users can now login without brute force blocks")
            else:
                print("✅ No failed login attempts found - system clean")
            
            # Show remaining stats
            successful_attempts = LoginAttempt.query.filter_by(success=True).count()
            print(f"ℹ️ Remaining successful login records: {successful_attempts}")
            
    except Exception as e:
        print(f"❌ Error during post-update cleanup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    clear_post_update_failed_logins()
